"""Fixed new-case SDK protocol. No Compile, Runtime, rack or general RPC entry."""
from pathlib import Path
import math
import re
import time

from ..safety import ToolSafetyError, sha256_file
from .native_edit import paste_ids, values_equal
from .native_rebuild import reconstruction_plan, compare_reconstruction, preserve_empty_runtime
from .topology_parser import parse_rtfx_topology, parse_parameter_schema
from .structured_patch import archive_snapshot
from .native_temp import capture_temp_inventory, verify_new_temp


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
    if suffix == journal.value.get("empty_page_suffix"):
        return method == "getComponentByIndex" and args == [journal.value["empty_page_id"],0]
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
    from ..model_editor import _definitions
    name_fields = {kind:{name for name,spec in parse_parameter_schema(text).items() if spec["data_type"] == "NAME"}
                   for kind,text in _definitions(before).items()} if strategy == "insert" else {}
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

    def own(value, expected=None, temp_inventory=None, returned_ns=None):
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
        if expected is None:
            try:
                journal.value["new_case_provenance"] = verify_new_temp(observed,temp_inventory,returned_ns)
                journal.flush()
            except Exception:
                journal.lost_identity(); raise
        expected_file = str(expected) if expected is not None else observed
        journal.value["case_history"][-1]["expected_file"] = expected_file
        identity(clean=True)

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

    def placement(c):
        return {"location":list(c.location),"orientation":c.orientation,"mirrored":c.mirrored}

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
        grouped_values = {}
        if strategy == "clipboard":
            # GROUP children are stored in Draft coordinates, but the installed
            # API returns coordinates relative to the group. Bind the source's
            # observed placement instead of inventing a coordinate transform.
            grouped = {(m["context"],m["uuid"]) for g in before.get("groups",[]) for m in g["members"] if m["kind"] == "component"}
            for row in before["components"]:
                key = (row["context"],row["uuid"])
                if key in grouped:
                    grouped_values[key] = placement(component(row))
            journal.value["grouped_source_readbacks"] = [{"context":k[0],"id":k[1],**v} for k,v in grouped_values.items()]
            journal.flush()
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
        inventory = capture_temp_inventory()
        journal.value["new_case_inventory"] = inventory; journal.flush()
        created = call("new_case",app,"newCase",[],app.new_case)
        returned_ns = time.time_ns()
        own(created,temp_inventory=inventory,returned_ns=returned_ns)
        if case.draft.num_subpages() != 1: raise ToolSafetyError("Unexpected new-case Draft subpages")
        target = case.draft.get_subpage(index=0)
        journal.value.update(empty_page_suffix=".draft.subpage:"+str(target.identifier),empty_page_id=target.identifier)
        try:
            next(iter(target))
            raise ToolSafetyError("New native Draft is not empty")
        except StopIteration:
            journal.value["new_case_provenance"]["empty_live_draft"] = True; journal.flush()
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
                    # Native getters expand NAME '#' placeholders. An apparently
                    # equal getter must not hide different stored naming semantics.
                    stored_name = name in name_fields.get(row["component_type"],set())
                    write_value = row["parameters"][name] if stored_name else value
                    if stored_name or not values_equal(old,value,numeric):
                        call("set_parameter",c,"setParameter",[name,write_value],lambda:c.set_parameter(name,write_value))
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
        journal.value['empty_runtime_preservation']=preserve_empty_runtime(inp,out,journal)
        digest = sha256_file(out)
        after = parse_rtfx_topology(out,definition_root).document
        comparison = compare_reconstruction(before,after)
        source_keys = {(m["candidate_context"],m["candidate_id"]):(m["source_context"],m["source_id"]) for m in comparison["uuid_mapping"]}
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
            key = source_keys[(row["context"],row["uuid"])]
            expected = grouped_values.get(key,{k:row[k] for k in ("location","orientation","mirrored")})
            actual = placement(c)
            journal.value.setdefault("reopened_placements",[]).append({"context":row["context"],"id":row["uuid"],"basis":"source_group_local" if key in grouped_values else "saved_draft","expected":expected,"actual":actual,"matches":actual==expected})
            journal.flush()
            if actual != expected:
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
