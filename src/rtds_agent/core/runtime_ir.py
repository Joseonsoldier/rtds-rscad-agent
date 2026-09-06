"""Saved Runtime semantic IR. References are not live execution targets."""
from collections import defaultdict
import json
from .state_machine import sha256_json
from ..safety import ToolSafetyError

ATTRIBUTES={"SLIDER":"value","BINARY_SWITCH":"value","SWITCH":"position","DIAL":"position",
            "PUSHBUTTON":"position","BUTTON":"position","DRAFT_VARIABLE":"position"}


def runtime_ir(parsed, document, *, snapshot_id, member, member_sha256):
    draft=defaultdict(list)
    for row in document["components"]:draft[row["uuid"]].append(row)
    rows=parsed["records"]
    result={"schema_version":"1.0","representation":"saved_runtime_semantic_subset","snapshot_id":snapshot_id,
            "source":{"project_snapshot_id":document["snapshot_id"],"project_sha256":document["source"]["rtfx_sha256"],
                      "member":member,"member_sha256":member_sha256},
            "pages":[],"groups":[],"controls":[],"displays":[],"plots":[],"signal_references":[],"unknown_records":[],
            "live_target_verified":False,"authoring_supported":False,"warnings":parsed["warnings"],"status":parsed["status"]}
    key=lambda kind,index:sha256_json({"snapshot_id":snapshot_id,"kind":kind,"index":index})
    children=defaultdict(list);page_children=defaultdict(list)
    for row in rows:
        children[row["parent_index"]].append(key("record",row["record_index"]))
        if row["parent_index"] is None:page_children[row["page_index"]].append(key("record",row["record_index"]))
    for page in parsed["pages"]:
        result["pages"].append({"type":"RuntimePage","key":key("page",page["page_index"]),**page,
                               "live_subpage_name":None,"children":page_children[page["page_index"]]})
    def refs(items,owner):
        keys=[]
        for ref in items:
            uid=ref["draft_component_id"];matches=draft.get(uid,[]) if uid is not None and not ref["field_ambiguities"] else []
            candidates=[{"context":r["context"],"component_id":r["uuid"],"component_type":r["component_type"]} for r in matches]
            # COMP_ID explicitly refers to a saved Draft record. No label or
            # Runtime UUID fallback, and no context guessed from display groups.
            binding={"status":"unique_saved_reference" if len(candidates)==1 else "ambiguous" if candidates else "unresolved",
                     "basis":"explicit_stored_COMP_ID","stored_component_id":uid,"candidates":candidates,
                     "live_target_verified":False}
            if binding["status"]!="unique_saved_reference":result["status"]="partial"
            identity=key("signal",len(result["signal_references"]))
            result["signal_references"].append({"type":"RuntimeSignalReference","key":identity,"owner_key":owner,
                                                **ref,"draft_source":binding,"units":None,"live_target_verified":False})
            keys.append(identity)
        return keys
    for row in rows:
        identity=key("record",row["record_index"])
        common={"key":identity,"record_index":row["record_index"],"component_id":row["component_id"],"kind":row["kind"],
                "stored_type":row["stored_type"],"name":row["name"],"identity_status":row["identity_status"],
                "page_key":key("page",row["page_index"]) if row["page_index"] is not None else None,
                "parent_key":key("record",row["parent_index"]) if row["parent_index"] is not None else None,
                "source_line":row["source_line"],"end_line":row["end_line"],"stored_configuration":row["stored_configuration"],
                "field_ambiguities":row["field_ambiguities"],"units":None,"stored_units":row["stored_units"],
                "current_value":None,"live_target_verified":False,"signal_keys":refs(row["signal_references"],identity)}
        kind=row["kind"]
        if kind in ATTRIBUTES:
            result["controls"].append({"type":"RuntimeControl",**common,"control_semantics":{"attribute":ATTRIBUTES[kind],
                "stored_positions":row["stored_positions"],"expected_current_value":None,"basis":"SDK control type; saved configuration is not a live value"},
                "binding_requirements":["exact case/hash","operator-specified live subpage","unique live type/name lookup","matching Runtime object ID","expected current value"]})
        elif kind in {"FRAME","BOX","CONTAINER"}:
            result["groups"].append({"type":"RuntimeGroup",**common,"children":children[row["record_index"]]})
        elif kind=="PLOT":
            graphs=[]
            for graph in row["graphs"]:
                gkey=key("graph",[row["record_index"],graph["graph_index"]])
                graphs.append({"key":gkey,"component_id":graph["component_id"],"source_line":graph["source_line"],"end_line":graph["end_line"],
                               "stored_fields":graph["fields"],"field_ambiguities":graph["field_ambiguities"],"identity_status":graph["identity_status"],
                               "curves":[{"curve_index":c["curve_index"],"source_line":c["source_line"],"end_line":c["end_line"],
                                          "stored_fields":c["fields"],"field_ambiguities":c["field_ambiguities"],"signal_keys":refs(c["references"],gkey)} for c in graph["curves"]]})
            result["plots"].append({"type":"RuntimePlot",**common,"graphs":graphs,"parse_status":row["plot_parse_status"]})
        elif row["role"]=="display":result["displays"].append({"type":"RuntimeDisplay",**common})
        else:result["unknown_records"].append({"type":"RuntimeUnknown",**common,"reason":"unsupported stored record type"})
    result["limitations"]=["Saved records, legacy duplicates and explicit COMP_ID references only; no Runtime/Draft UUID equivalence",
        "Display group paths do not establish Draft hierarchy or live subpage names",
        "Plot graph/curve subset excludes numeric samples, scripts and undocumented options",
        "Stored units, ranges and positions are not validated live values or execution approval",
        "Runtime overlay authoring has no qualified adapter; no RTX writer is provided"]
    result["ir_sha256"]=sha256_json(result)
    if len(json.dumps(result,allow_nan=False).encode("utf-8"))>10*1024*1024:raise ToolSafetyError("Runtime IR exceeds 10 MiB")
    return result
