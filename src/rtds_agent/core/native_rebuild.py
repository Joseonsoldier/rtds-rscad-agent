"""Bounded source-derived Draft reconstruction and explicit native UUID mapping.

No guessed UUIDs, hierarchy-name collapsing or electrical-equivalence claim.
The SDK runner is private; public use still requires a reviewed component policy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
from pathlib import Path
import zipfile

from ..safety import ToolSafetyError, sha256_file
from .state_machine import sha256_json
from .topology_parser import world
from .static_comparison import topology_signature


def wire_points(row):
    points = [world(row, (int(row["parameters"][f"x{i}"]), int(row["parameters"][f"y{i}"]))) for i in (1, 2)]
    if points[0] == points[1]: raise ToolSafetyError("Zero-length native wire")
    return [list(p) for p in points]


def reconstruction_plan(source, document, strategy):
    """Read-only plan. No Runtime layout dropping or arbitrary component definitions."""
    from ..runtime_layout import parse_runtime_layout
    from .structured_patch import archive_snapshot
    if strategy not in {"insert", "clipboard"}: raise ToolSafetyError("Unsupported native reconstruction strategy")
    rows = document["components"]
    if not 1 <= len(rows) <= 500 or len({(r["context"], r["uuid"]) for r in rows}) != len(rows):
        raise ToolSafetyError("Reconstruction requires 1..500 uniquely identified components")
    if len({r["uuid"] for r in rows}) != len(rows):
        raise ToolSafetyError("Native SDK handles require globally unique saved component IDs")
    if any(r["context"].split("/", 1)[0] != "subsystem:0" for r in rows):
        raise ToolSafetyError("Reconstruction supports one Draft subsystem")
    if any(abs(v) > 1000000 for r in rows for v in r["location"]):
        raise ToolSafetyError("Reconstruction coordinate bounds exceeded")
    if strategy == "insert" and (document.get("groups") or any(r["context"] != "subsystem:0" or r["component_type"] == "HIERARCHY" for r in rows)):
        raise ToolSafetyError("Insertion requires flat ungrouped Draft; use reviewed clipboard reconstruction")
    archive = archive_snapshot(Path(source))
    with zipfile.ZipFile(source) as z:
        # Rebuilding only an empty Runtime is explicit. Opaque payloads are not discarded.
        rtx = [n for n in archive["members"] if n.lower().endswith(".rtx")]
        if len(rtx) != 1: raise ToolSafetyError("Reconstruction requires one saved empty Runtime layout")
        if z.getinfo(rtx[0]).file_size > 1024*1024: raise ToolSafetyError("Runtime layout exceeds reconstruction bounds")
        layout = parse_runtime_layout(z.read(rtx[0]).decode("utf-8-sig"))
        if layout["records"] or layout["warnings"]: raise ToolSafetyError("Reconstruction cannot discard a saved Runtime layout")
        for n in archive["members"]:
            if n not in {rtx[0], archive["dfx_member"]} and (not n.lower().endswith(".inf2") or z.getinfo(n).file_size):
                raise ToolSafetyError("Reconstruction cannot discard opaque archive payloads")
    top = [r for r in rows if r["context"] == "subsystem:0"]
    lo = [min(r["location"][i] for r in top)-512 for i in (0, 1)]
    hi = [max(r["location"][i] for r in top)+512 for i in (0, 1)]
    center = [((lo[i]+hi[i])//32)*16 for i in (0, 1)]
    wires = [{"source_id": r["uuid"], "phase": 3 if r["component_type"] == "BUS" else 1,
              "coordinates": wire_points(r)} for r in rows if r["component_type"] in {"BUS", "WIRE"}]
    plan = {"strategy": strategy, "component_count": len(rows), "group_count": len(document.get("groups", [])),
            "selection": [lo, hi], "paste_location": center, "wires": wires,
            "source_sha256": sha256_file(Path(source)), "runtime_records": 0,
            "qualification": "parsed Draft subset; exact saved verification required"}
    plan["plan_id"] = sha256_json(plan)
    return plan


def compare_reconstruction(before, after):
    """Match within each parent context, allowing one translation and new UUIDs.

    Ambiguous identical co-located records fail closed. Wires compare their world
    endpoints and style, allowing the SDK to choose midpoint/orientation storage.
    """
    a, b = defaultdict(list), defaultdict(list)
    for doc, target in ((before, a), (after, b)):
        seen = set()
        if not 1 <= len(doc["components"]) <= 500: raise ToolSafetyError("Reconstruction comparison bounds exceeded")
        for r in doc["components"]:
            key = (r["context"], r["uuid"])
            if key in seen: raise ToolSafetyError("Duplicate reconstruction identity")
            seen.add(key); target[r["context"]].append(r)
    mapping, contexts, shifts = {}, {}, {}
    pending = [("subsystem:0", "subsystem:0")]

    def origin(rows):
        points = [p for r in rows for p in (wire_points(r) if r["component_type"] in {"WIRE", "BUS"} else [r["location"]])]
        return [min(p[i] for p in points) for i in (0, 1)] if points else [0, 0]

    def signature(r, base):
        fields = {k:r[k] for k in ("component_type", "parameters", "orientation", "mirrored")}
        if r["component_type"] in {"WIRE", "BUS"}:
            fields = {"component_type":r["component_type"], "parameters":{k:v for k,v in r["parameters"].items() if k not in {"x1","y1","x2","y2"}},
                      "endpoints":sorted([[p[i]-base[i] for i in (0,1)] for p in wire_points(r)])}
        else: fields["location"] = [r["location"][i]-base[i] for i in (0, 1)]
        return sha256_json(fields)

    while pending:
        ca, cb = pending.pop()
        if ca in contexts or cb in contexts.values(): raise ToolSafetyError("Ambiguous hierarchy context mapping")
        ra, rb = a.get(ca, []), b.get(cb, [])
        oa, ob = origin(ra), origin(rb)
        ka, kb = {}, {}
        for rows, base, keyed in ((ra, oa, ka), (rb, ob, kb)):
            for r in rows:
                key = signature(r, base)
                if key in keyed: raise ToolSafetyError("Ambiguous co-located component mapping")
                keyed[key] = r
        if ka.keys() != kb.keys(): raise ToolSafetyError("Native reconstruction changed component content or relative geometry")
        contexts[ca] = cb; shifts[ca] = [ob[i]-oa[i] for i in (0,1)]
        for key in ka:
            x, y = ka[key], kb[key]
            mapping[(ca, x["uuid"])] = (cb, y["uuid"])
            if x["component_type"] == "HIERARCHY":
                def child(c, r): return c+"/"+(r["parameters"].get("Name", "box").rstrip("#") or "box")+":"+str(r["uuid"])
                pending.append((child(ca,x), child(cb,y)))
    if set(a)-contexts.keys() or set(b)-set(contexts.values()) or len(mapping) != len(after["components"]):
        raise ToolSafetyError("Unmapped native hierarchy/components")
    reverse = {v:k for k,v in mapping.items()}
    reverse_context = {v:k for k,v in contexts.items()}

    def group_signatures(doc, candidate):
        groups = {g["group_id"]:g for g in doc.get("groups", [])}
        if len(groups) != len(doc.get("groups", [])): raise ToolSafetyError("Duplicate GROUP identity")
        seen = set()
        def visit(gid, parent=None, depth=0):
            if depth > 32 or gid in seen or gid not in groups: raise ToolSafetyError("Invalid GROUP membership graph")
            seen.add(gid); g = groups[gid]
            if g["parent_group"] != parent: raise ToolSafetyError("Inconsistent GROUP parent")
            context = reverse_context[g["context"]] if candidate else g["context"]
            shift = shifts[context] if candidate else [0, 0]
            members = []
            for m in g["members"]:
                if m["kind"] == "group": members.append(["group", visit(m["group_id"],gid,depth+1)])
                else:
                    pair = (m["context"],m["uuid"])
                    pair = reverse[pair] if candidate else pair
                    if pair not in mapping or pair[0] != context: raise ToolSafetyError("Invalid GROUP member identity/context")
                    members.append(["component", *pair])
            bounds = g["bounds"]
            return sha256_json({"context":context,"location":[g["location"][i]-shift[i] for i in (0,1)],
                "bounds": [v-shift[i%2] for i,v in enumerate(bounds)] if bounds else None,
                "metadata":g["metadata"],"members":sorted(members,key=repr)})
        result = Counter(visit(gid) for gid,g in groups.items() if g["parent_group"] is None)
        if len(seen) != len(groups): raise ToolSafetyError("Unreachable GROUP")
        return result
    if group_signatures(before,False) != group_signatures(after,True): raise ToolSafetyError("Native reconstruction changed GROUP structure")
    normalized = copy.deepcopy(after)
    for net in normalized["nets"]:
        for m in net["members"]:
            context, uid = reverse[(m["context"],m["component_id"])]
            m["context"], m["component_id"] = context, uid
            for key in ("start", "end"):
                if key in m: m[key] = [v-shifts[context][i] for i,v in enumerate(m[key])]
    if topology_signature(before) != topology_signature(normalized): raise ToolSafetyError("Native reconstruction changed static topology")
    if before["source"]["settings"] != after["source"]["settings"]: raise ToolSafetyError("Native reconstruction changed stored case settings")
    return {"status":"verified_parsed_reconstruction", "component_count":len(mapping), "group_count":len(before.get("groups",[])),
            "uuid_mapping":[{"source_context":k[0],"source_id":k[1],"candidate_context":v[0],"candidate_id":v[1]} for k,v in sorted(mapping.items())],
            "context_translations":shifts, "same_static_topology":True, "integration_qualified":False}
