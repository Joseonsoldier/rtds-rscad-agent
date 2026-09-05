"""Fixed new-case SDK protocol. No Compile, Runtime, rack or general RPC entry."""
from pathlib import Path
import math
import re

from ..safety import ToolSafetyError, sha256_file
from .native_edit import paste_ids, values_equal
from .native_rebuild import reconstruction_plan, compare_reconstruction
from .topology_parser import parse_rtfx_topology
from .structured_patch import archive_snapshot


def allow_rebuild_rpc(path, method, args, journal, inp, out):
    """Independent read allowlist; each mutation needs exact durable local intent."""
    pending = journal.value.get("permitted_rpc")
    call = journal.value["native_calls"][-1] if journal.value["native_calls"] else {}
    # disconnect(terminate=False) pings the transport before releasing it. This
    # read does not address a case and must remain possible during recovery.
    if path == "rscad" and method == "ping" and not args: return True
    if journal.value["status"] == "operator_recovery_required": return False
    if pending and pending == [path, method, args] and call.get("status") == "started": return True
    if path == "rscad":
        if method in {"ping", "getMinimumApiVersion", "getApiVersion", "getVersion"}: return not args
        return method == "getCaseNamed" and args in ([str(inp),False],[str(out),False])
    match = re.fullmatch(r"rscad\.case:(\d+)(.*)",path)
    if not match or int(match[1]) != journal.value["owned_case"]: return False
    suffix = match[2]
    if not suffix: return method in {"getFile","getRunState","getModified"} and not args
    if suffix == ".settings": return method in {"getTimestep","getTitle","getRealtime"} and not args
    if suffix == ".draft":
        if method == "numSubpages": return not args
        if method == "getSubpage": return args == [0]
        if method == "getComponent": return len(args)==1 and type(args[0]) is int and args[0] in journal.value.get("read_ids",[])
    comp = re.fullmatch(r"\.draft\.comp_id:(\d+)",suffix)
    if comp and int(comp[1]) in journal.value.get("read_ids",[]):
        if method in {"getComponentType","getLocation","getOrientation","getMirrored","getParameters"}: return not args
        if method == "getParameter": return len(args)==1 and args[0] in journal.value.get("read_parameters",{}).get(str(int(comp[1])),[])
    return False


def rebuild_case(app, inp, out, strategy, journal, definition_root):
    inp, out = Path(inp).resolve(), Path(out).resolve()
    if inp == out or out.exists(): raise ToolSafetyError("Native reconstruction output must be new")
    before = parse_rtfx_topology(inp,definition_root).document
    plan = reconstruction_plan(inp,before,strategy)
    protected = sha256_file(inp)
    case = None
    expected_file = None
    connected = closed = disconnected = False

    def call(name,obj,method,args,fn,mutation=True):
        journal.value["permitted_rpc"] = [obj.get_path(),method,args]
        try: return journal.call(name,fn,mutation=mutation,arguments={"method":method,"args":args})
        finally:
            journal.value.pop("permitted_rpc",None); journal.flush()

    def identity(clean=False):
        try:
            if case.caseid != journal.value["owned_case"] or case.file != expected_file or case.state.run_state != "stopped":
                raise ToolSafetyError("Native reconstruction case identity/state mismatch")
            if clean and case.state.modified is not False: raise ToolSafetyError("Native reconstruction has unsaved changes")
            journal.value["identity_verified"] = True; journal.flush()
        except Exception:
            journal.lost_identity(); raise

    def own(value, expected=None):
        nonlocal case,expected_file,closed
        if value is None or type(value.caseid) is not int or value.caseid < 0:
            journal.lost_identity(); raise ToolSafetyError("Unconfirmed native case creation/open")
        case = value; closed = False
        journal.value.update(owned_case=case.caseid,identity_verified=False,read_ids=[],read_parameters={})
        # The freshly returned newCase identity is authoritative only in this connection.
        observed = case.file
        journal.value.setdefault("case_history",[]).append({"case_id":case.caseid,"observed_file":observed if isinstance(observed,str) else {"unsupported_type":type(observed).__name__},"requested_file":str(expected) if expected is not None else None})
        journal.flush()
        if not isinstance(observed,str):
            journal.lost_identity(); raise ToolSafetyError("Unsupported native file identity type")
        if expected is None and observed and Path(observed).exists():
            journal.lost_identity(); raise ToolSafetyError("New case unexpectedly refers to an existing file")
        expected_file = str(expected) if expected is not None else observed
        journal.value["case_history"][-1]["expected_file"] = expected_file
        identity(clean=expected is not None)

    def close():
        nonlocal case,closed
        identity(clean=True)
        try:
            result = call("close",case,"close",[False],lambda:case.close(force=False),False)
            if result is not True: raise ToolSafetyError("Native reconstruction close unconfirmed")
        except Exception:
            journal.lost_identity(); raise
        closed = True; case = None
        if expected_file in {str(inp),str(out)} and app.get_case(file=expected_file,open_file=False) is not None:
            closed = False; journal.lost_identity(); raise ToolSafetyError("Closed reconstruction case is still open")
        journal.value["cleanup"].append({"action":"close","case_id":journal.value["owned_case"],"verified":True})
        journal.value.update(owned_case=None,identity_verified=False)
        journal.flush()

    def component(row, uid=None):
        uid = row["uuid"] if uid is None else uid
        journal.value["read_ids"].append(uid)
        journal.value["read_parameters"][str(uid)] = list(row["parameters"])
        c = case.draft.get_object(uid)
        if c is None or c.unique_id != uid or c.component_type != row["component_type"]:
            raise ToolSafetyError("Native reconstruction component identity mismatch")
        return c

    try:
        connected = True; journal.call("connect",app.connect)
        journal.value["observed_rscad_version"] = app.get_version()
        if str(journal.value["observed_rscad_version"]) not in {"2.7","2.7.3"}: raise ToolSafetyError("Unreviewed RSCAD version")
        for path in (inp,out):
            if app.get_case(file=str(path),open_file=False) is not None: raise ToolSafetyError("Reconstruction path already open")
        own(call("open_case",app,"openCase",[str(inp)],lambda:app.open_case(str(inp))),inp)
        if case.draft.num_subpages() != 1: raise ToolSafetyError("Only one native Draft subpage supported")
        settings = {name:getattr(case.settings,name) for name in ("timestep","title","realtime")}
        values = {}
        if strategy == "clipboard":
            page = case.draft.get_subpage(index=0)
            lo,hi = plan["selection"]
            call("select_area",page,"selectArea",[lo,hi,page.identifier],lambda:page.select_area(tuple(lo),tuple(hi)))
            call("copy",page,"copy",[[],page.identifier],lambda:page.copy())
        else:
            for row in before["components"]:
                if row["component_type"] in {"WIRE","BUS"}: continue
                c = component(row)
                names = c.parameters
                if not isinstance(names,list) or len(names)>500 or any(n not in row["parameters"] for n in names):
                    raise ToolSafetyError("Native source parameter inventory differs from saved source")
                values[row["uuid"]] = {n:c.get_parameter(n) for n in names}
                if any(type(v) not in {str,int,float,bool} or (isinstance(v,str) and len(v)>10000) or
                       (type(v) is float and not math.isfinite(v)) for v in values[row["uuid"]].values()):
                    raise ToolSafetyError("Unsupported native source parameter value")
        close()
        own(call("new_case",app,"newCase",[],app.new_case))
        if case.draft.num_subpages() != 1: raise ToolSafetyError("Unexpected new-case Draft subpages")
        target = case.draft.get_subpage(index=0)
        if strategy == "clipboard":
            journal.value["permitted_rpc"] = [target.get_path(),"paste",[plan["paste_location"],target.identifier]]
            try: journal.value["paste_result"] = paste_ids(target,plan["paste_location"],journal)
            finally: journal.value.pop("permitted_rpc",None); journal.flush()
        else:
            for row in before["components"]:
                identity()
                if row["component_type"] in {"WIRE","BUS"}: continue
                x,y = row["location"]
                uid = call("insert_component",target,"insertComponent",[row["component_type"],x,y,target.identifier],
                           lambda:target._insert_component(row["component_type"],x,y,target.identifier))
                if type(uid) is not int or uid<0 or uid in journal.value["read_ids"]: raise ToolSafetyError("Invalid inserted component identity")
                c = component(row,uid)
                for attr,method in (("orientation","setOrientation"),("mirrored","setMirrored")):
                    if getattr(c,attr) != row[attr]: call(attr,c,method,[row[attr]],lambda:setattr(c,attr,row[attr]))
                for name,value in values[row["uuid"]].items():
                    old = c.get_parameter(name)
                    numeric = type(value) in {float,int}
                    if not values_equal(old,value,numeric):
                        call("set_parameter",c,"setParameter",[name,value],lambda:c.set_parameter(name,value))
                    actual = c.get_parameter(name)
                    matched = values_equal(actual,value,numeric)
                    journal.value["readbacks"].append({"source_id":row["uuid"],"component_id":uid,"field":name,"matches":matched})
                    if not matched: raise ToolSafetyError("Inserted parameter readback mismatch")
                if list(c.location)!=row["location"] or c.orientation!=row["orientation"] or c.mirrored!=row["mirrored"]:
                    raise ToolSafetyError("Inserted placement readback mismatch")
            for wire in plan["wires"]:
                identity()
                call("create_wire",target,"createWire",[wire["phase"],wire["coordinates"],target.identifier],
                     lambda:target.create_wire(wire["phase"],[tuple(p) for p in wire["coordinates"]]))
        for attr,method in (("timestep","setTimestep"),("title","setTitle"),("realtime","setRealtime")):
            value = settings[attr]
            if getattr(case.settings,attr) != value: call(attr,case.settings,method,[value],lambda:setattr(case.settings,attr,value))
            if getattr(case.settings,attr) != value: raise ToolSafetyError("Reconstruction settings readback mismatch")
        identity()
        call("save_as",case,"saveAs",[str(out)],lambda:case.save(str(out)))
        expected_file = str(out); identity(clean=True)
        digest = sha256_file(out)
        close()
        after = parse_rtfx_topology(out,definition_root).document
        comparison = compare_reconstruction(before,after)
        # New-case save must retain empty Runtime and every non-DFX byte exactly.
        a,b = archive_snapshot(inp),archive_snapshot(out)
        if set(a["members"]) != set(b["members"]) or a["archive_comment_sha256"] != b["archive_comment_sha256"]:
            raise ToolSafetyError("Reconstruction changed archive members/comment")
        if any(b["member_sha256"][n]!=h for n,h in a["member_sha256"].items() if n!=a["dfx_member"]):
            raise ToolSafetyError("Reconstruction changed non-DFX archive data")
        own(call("reopen",app,"openCase",[str(out)],lambda:app.open_case(str(out))),out)
        # Every saved UUID is resolved once, including GROUP children; never -1.
        for row in after["components"]:
            c = component(row)
            if list(c.location)!=row["location"] or c.orientation!=row["orientation"] or c.mirrored!=row["mirrored"]:
                raise ToolSafetyError("Reopened reconstructed component readback mismatch")
        identity(clean=True)
        if sha256_file(out)!=digest or sha256_file(inp)!=protected: raise ToolSafetyError("Reconstruction source/reopen bytes changed")
        if "paste_result" in journal.value: journal.value["paste_result"]["structure_verified"] = True
        journal.value.update(status="verified_edit",candidate_sha256=digest,reopened=True,closed_before_reopen=True,reconstruction=comparison,plan=plan)
    except Exception as exc:
        journal.value.update(error_type=type(exc).__name__,error=str(exc))
        if journal.value["status"] != "operator_recovery_required": journal.value["status"] = "failed"
        raise
    finally:
        if case is not None and journal.value["status"] != "operator_recovery_required":
            try: close()
            except Exception as exc: journal.value["cleanup"].append({"action":"close","verified":False,"error":str(exc)})
        if connected:
            try:
                app.disconnect(terminate=False); disconnected=True
                journal.value["cleanup"].append({"action":"disconnect","verified":True,"terminate":False})
            except Exception as exc: journal.value["cleanup"].append({"action":"disconnect","verified":False,"error":str(exc)})
        uncertain = any(c["status"] == "failed" and c["operation"] in {"open_case","new_case","reopen"} for c in journal.value["native_calls"])
        journal.value["cleanup_verified"] = closed and disconnected and not uncertain and journal.value["status"] != "operator_recovery_required"
        if journal.value["native_mutation_possible"] and not journal.value["cleanup_verified"]: journal.value["status"]="operator_recovery_required"
        journal.flush()
    if not journal.value["cleanup_verified"]: raise ToolSafetyError("Reconstruction cleanup unconfirmed")
    return journal.value
