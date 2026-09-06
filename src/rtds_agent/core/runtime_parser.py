"""Bounded saved RTX subset parser. No serialization, SDK or live identities."""
from collections import Counter
import re
from ..safety import ToolSafetyError

SUPPORTED = {"METER", "SLIDER", "SWITCH", "DIAL", "PUSHBUTTON", "BUTTON", "BINARY_SWITCH", "DRAFT_VARIABLE", "PLOT", "FRAME", "BOX", "CONTAINER", "LIGHT"}
CONTROLS = {"SLIDER", "SWITCH", "DIAL", "PUSHBUTTON", "BUTTON", "BINARY_SWITCH", "DRAFT_VARIABLE"}
FIELDS = {"UUID", "NAME", "UNITS", "MIN", "MAX", "VALUE", "POSITION", "POSITIONS", "UPDATE", "USE_TEXT_OVERRIDES",
          "comp_locX", "comp_locY", "comp_width", "comp_height", "inFrameRowIndex", "inFrameColIndex"}
GRAPH_FIELDS = {"UUID", "NAME", "X LABEL", "Y LABEL", "X SCALE", "Y SCALE", "X RANGE", "Y MIN", "Y MAX"}


def stored_id(value):
    return int(value) if isinstance(value,str) and re.fullmatch(r"[0-9]{1,16}",value) else None


def parse_runtime_layout(text):
    if len(text.encode("utf-8")) > 16*1024*1024:
        raise ToolSafetyError("Runtime layout exceeds 16 MiB")
    records, pages, warnings, stack = [], [], [], []
    page = graph = curve = None
    graph_total = reference_total = 0

    def field(obj,key,value):
        if key in obj["fields"]: obj["field_ambiguities"].append(key)
        obj["fields"][key] = value

    def reference(obj,key,value,line_no):
        nonlocal reference_total
        if key == "GROUP":
            obj["pending_group"] = value
            obj["last_reference"] = None
        elif key == "DESC":
            reference_total += 1
            if reference_total>20000:raise ToolSafetyError("Runtime signal reference limit exceeded")
            group = obj.get("pending_group")
            ref = {"group":group,"description":value,"stored_signal_path":group+"|"+value if group and group!="(NONE)" and value else None,
                   "draft_component_id":None,"source_line":line_no,"field_ambiguities":[]}
            obj["references"].append(ref);obj["last_reference"]=ref
        elif key == "COMP_ID":
            ref = obj.get("last_reference")
            if ref is None: warnings.append(f"line {line_no}: orphan COMP_ID")
            else:
                if "stored_comp_id" in ref:ref["field_ambiguities"].append("COMP_ID")
                ref["stored_comp_id"] = value;ref["draft_component_id"] = stored_id(value)
                if ref["draft_component_id"] is None:ref["field_ambiguities"].append("COMP_ID")

    def holder(**extra):
        return {"fields":{},"field_ambiguities":[],"references":[],"pending_group":None,"last_reference":None,**extra}

    lines=text.splitlines()
    for line_no,raw in enumerate(lines,1):
        line=raw.strip()
        if len(line)>10000:raise ToolSafetyError("Runtime line exceeds limit")
        if line.startswith("VIEW-START:"):
            if stack:raise ToolSafetyError("Runtime view starts inside an unclosed component")
            if len(pages)>=256:raise ToolSafetyError("Runtime page limit exceeded")
            if page is not None:pages[page]["end_line"]=line_no-1
            match=re.search(r'VIEW-ID:\s*"([^"\r\n]+)"',line)
            size=re.search(r'VIEW-CANVAS-SIZE:\s*([0-9]+),([0-9]+)',line)
            page=len(pages)
            pages.append({"page_index":page,"view_id":match.group(1) if match else None,"source_line":line_no,
                          "end_line":None,"stored_canvas_size":[int(size[1]),int(size[2])] if size else None})
            if match is None:warnings.append(f"line {line_no}: unsupported view identity")
            continue
        if line in {"VIEW-END:","VIEW-END"}:
            if stack or page is None:raise ToolSafetyError("Unbalanced Runtime view end")
            pages[page]["end_line"]=line_no;page=None;continue
        if line.startswith("COMPONENT:"):
            if graph is not None or curve is not None:raise ToolSafetyError("Component inside an unclosed Runtime plot graph")
            if len(records)>=10000 or len(stack)>=32:raise ToolSafetyError("Runtime layout component/depth limit exceeded")
            kind=line.split(":",1)[1].strip()
            if stack:records[stack[-1]]["header_closed"]=True
            records.append(holder(index=len(records),parent_index=stack[-1] if stack else None,page_index=page,
                                  view_id=pages[page]["view_id"] if page is not None else None,
                                  stored_type=kind,kind=kind.removeprefix("TAGGED_V2.2_"),source_line=line_no,
                                  header_closed=False,graphs=[],positions=[],data_blocks=[],open_blocks=[]))
            stack.append(len(records)-1);continue
        if line == "COMPONENT-END:":
            if not stack or graph is not None or curve is not None:raise ToolSafetyError("Unbalanced Runtime component end")
            if records[stack[-1]]["open_blocks"]:raise ToolSafetyError("Unclosed Runtime data block")
            records[stack.pop()]["end_line"]=line_no;continue
        if not stack:continue
        record=records[stack[-1]]
        block=re.fullmatch(r"([A-Z-]+(?:DATA|OPTIONS-PRE|OPTIONS-POST))-(START|END):?",line)
        if block:
            name,edge=block.groups()
            record["header_closed"]=True
            if edge=="START":
                if len(record["open_blocks"])>=32:raise ToolSafetyError("Runtime data block depth limit exceeded")
                if name=="GRAPH-DATA" and graph is None:raise ToolSafetyError("Graph data outside a graph")
                record["open_blocks"].append(name);record["data_blocks"].append(line)
                if name not in {"PLOT-DATA","GRAPH-DATA","GUI-DATA","PLOT-OPTIONS-PRE","PLOT-OPTIONS-POST"}:
                    warnings.append(f"line {line_no}: unsupported data block {name}")
            else:
                if not record["open_blocks"] or record["open_blocks"].pop()!=name:raise ToolSafetyError("Unbalanced Runtime data block")
            continue
        if line.startswith("GRAPH-START"):
            if record["kind"]!="PLOT" or graph is not None or curve is not None:raise ToolSafetyError("Invalid Runtime graph start")
            if any(b!="PLOT-DATA" for b in record["open_blocks"]):raise ToolSafetyError("Graph inside an unsupported data scope")
            graph_total+=1
            if graph_total>2000:raise ToolSafetyError("Runtime graph limit exceeded")
            record["header_closed"]=True
            graph=holder(graph_index=len(record["graphs"]),source_line=line_no,curves=[],declared_header=line)
            record["graphs"].append(graph);continue
        if line in {"GRAPH-END","GRAPH-END:"}:
            if graph is None or curve is not None:raise ToolSafetyError("Unbalanced Runtime graph end")
            if any(b!="PLOT-DATA" for b in record["open_blocks"]):raise ToolSafetyError("Unclosed graph data block")
            graph["end_line"]=line_no;graph=None;continue
        if line in {"CURVE-START","CURVE-START:"}:
            if record["kind"]!="PLOT" or curve is not None:raise ToolSafetyError("Invalid Runtime curve start")
            if any(b!="PLOT-DATA" for b in record["open_blocks"]):raise ToolSafetyError("Curve inside an unsupported data scope")
            if graph is None:
                # Legacy single-curve data remains an unparsed partial block;
                # never fabricate a graph UUID or claim complete plot grammar.
                warnings.append(f"line {line_no}: curve outside an explicit graph")
                continue
            if len(graph["curves"])>=256:raise ToolSafetyError("Runtime curve limit exceeded")
            curve=holder(curve_index=len(graph["curves"]),source_line=line_no);graph["curves"].append(curve);continue
        if line in {"CURVE-END","CURVE-END:"}:
            if curve is not None:curve["end_line"]=line_no;curve=None
            elif graph is not None:raise ToolSafetyError("Unbalanced Runtime curve end")
            continue
        if ":" not in line:continue
        key,value=(p.strip() for p in line.split(":",1))
        if len(value)>4096:raise ToolSafetyError("Runtime header value exceeds limit")
        if curve is not None:
            if any(b!="PLOT-DATA" for b in record["open_blocks"]):continue
            if key in {"GROUP","DESC","COMP_ID"}:reference(curve,key,value,line_no)
            elif key in {"LABEL","STYLE","THICKNESS","COLOR"}:field(curve,key,value)
        elif graph is not None:
            if record["open_blocks"] and record["open_blocks"][-1]=="GRAPH-DATA" and key in GRAPH_FIELDS:field(graph,key,value)
        elif not record["header_closed"]:
            if key in {"GROUP","DESC","COMP_ID"}:reference(record,key,value,line_no)
            elif key in FIELDS:field(record,key,value)
            elif re.fullmatch(r"POSITION [0-9]+ DATA",key):record["positions"].append({"key":key,"stored_value":value,"source_line":line_no})
    if stack:raise ToolSafetyError("Unclosed Runtime component; inventory is incomplete")
    if page is not None:pages[page]["end_line"]=len(lines)
    # Some installed versions terminate a view at EOF, without VIEW-END.
    ids=Counter(stored_id(r["fields"].get("UUID")) for r in records)
    graph_ids=Counter(stored_id(g["fields"].get("UUID")) for r in records for g in r["graphs"])
    ids.update(graph_ids)
    page_ids=Counter(p["view_id"] for p in pages)
    def clean(obj):
        return {k:v for k,v in obj.items() if k not in {"pending_group","last_reference"}}
    result=[]
    for record in records:
        fields=record["fields"];uid=stored_id(fields.get("UUID"));kind=record["kind"]
        graphs=[]
        for g in record["graphs"]:
            gid=stored_id(g["fields"].get("UUID"))
            graphs.append({**clean(g),"component_id":gid,"identity_status":"stored_unique" if gid is not None and ids[gid]==1 and not g["field_ambiguities"] else "ambiguous",
                           "curves":[clean(c) for c in g["curves"]]})
            if g["field_ambiguities"] or any(c["field_ambiguities"] or any(ref["field_ambiguities"] for ref in c["references"]) for c in g["curves"]):
                warnings.append(f"line {g['source_line']}: ambiguous graph/curve fields")
        if any(ref["field_ambiguities"] for ref in record["references"]):warnings.append(f"line {record['source_line']}: ambiguous signal reference fields")
        if record["page_index"] is None:warnings.append(f"line {record['source_line']}: record has no saved page")
        ambiguous=bool(record["field_ambiguities"]) or uid is None or ids[uid]>1
        result.append({"record_index":record["index"],"parent_index":record["parent_index"],"page_index":record["page_index"],
            "view_id":record["view_id"],"component_id":uid,"stored_type":record["stored_type"],"kind":kind,
            "role":"control" if kind in CONTROLS else "display" if kind in SUPPORTED else "unknown",
            "parse_status":"supported_header" if kind in SUPPORTED else "unsupported_type","identity_status":"ambiguous" if ambiguous else "stored_unique",
            "field_ambiguities":record["field_ambiguities"],"name":fields.get("NAME"),"stored_units":fields.get("UNITS"),
            "observed_units":None,"observed_value":None,"stored_configuration":{k:v for k,v in fields.items() if k not in {"UUID","NAME","UNITS"}},
            "signal_references":record["references"],"stored_positions":record["positions"],"graphs":graphs,
            "plot_parse_status":"parsed_graph_subset" if graphs else "unparsed_data" if record["data_blocks"] else "no_graphs",
            "source_line":record["source_line"],"end_line":record["end_line"],"evidence_level":"saved_runtime_layout","live_target_verified":False})
    for p in pages:p["identity_status"]="stored_unique" if p["view_id"] and page_ids[p["view_id"]]==1 else "ambiguous"
    unsupported=sum(r["parse_status"]!="supported_header" for r in result)
    return {"records":result,"pages":pages,"warnings":warnings,"unsupported_count":unsupported,
            "status":"partial" if unsupported or warnings or any(r["identity_status"]=="ambiguous" or any(g["identity_status"]=="ambiguous" for g in r["graphs"]) for r in result) or any(p["identity_status"]=="ambiguous" for p in pages) else "available"}
