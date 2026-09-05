"""Versioned static model IR and deterministic diagram; not a vendor serializer."""
from .state_machine import sha256_json


def model_ir(document):
    if len(document["components"]) > 5000 or len(document["nets"]) > 10000:
        raise ValueError("IR exceeds 5000 components/10000 nets")
    components = [{k: row[k] for k in ("context", "uuid", "component_type", "parameters", "location", "orientation", "mirrored")}
                  for row in document["components"]]
    result = {"schema_version": "1.0", "representation": "parsed_rscad_subset", "components": components,
              "hierarchy": sorted({r["context"] for r in components}), "ports": document["ports"],
              "connections": document["nets"], "metadata": {"source": document["source"],
              "coverage": document["coverage"], "warnings": document["warnings"], "limitations": document["limitations"]}}
    result["ir_sha256"] = sha256_json(result)
    import json
    if len(json.dumps(result,allow_nan=False)) > 10*1024*1024:
        raise ValueError("IR exceeds 10 MiB JSON output")
    return result


def semantic_diff(before, after):
    def keyed(doc):
        rows = {(r["context"], r["uuid"]): r for r in model_ir(doc)["components"]}
        if len(rows) != len(doc["components"]):
            raise ValueError("Duplicate component identity prevents semantic comparison")
        return rows
    a, b = keyed(before), keyed(after)
    from .static_comparison import topology_signature
    return {"added": [b[k] for k in sorted(b.keys()-a.keys())],
            "removed": [a[k] for k in sorted(a.keys()-b.keys())],
            "changed": [{"identity": list(k), "before": a[k], "after": b[k]} for k in sorted(a.keys() & b.keys()) if a[k] != b[k]],
            "same_static_topology": topology_signature(before) == topology_signature(after)}


def mermaid_overview(document):
    # Labels are entity-encoded, never executable Mermaid supplied by the project.
    def label(value):
        return "".join(c if c.isalnum() or c in " _.-:/" else f"#{ord(c)};" for c in str(value))[:240]
    if len(document["components"]) > 500 or len(document["nets"]) > 1000:
        raise ValueError("Diagram exceeds 500 components/1000 nets; narrow the model first")
    lines, ids = ["flowchart LR"], {}
    for i, row in enumerate(document["components"]):
        key = (row["context"], row["uuid"])
        if key in ids:
            raise ValueError("Ambiguous identities cannot be drawn as exact components")
        ids[key] = f"c{i}"
        lines.append(f'  c{i}["{label(row["context"])} / {row["uuid"]}: {label(row["component_type"])}"]')
    for i, net in enumerate(document["nets"]):
        members = sorted({ids[(m["context"], m["component_id"])] for m in net["members"]})
        if len(members) > 1:
            lines.append(f'  n{i}(("{label(net["domain"])}"))')
            lines.extend(f"  {c} --- n{i}" for c in members)
    return "\n".join(lines) + "\n"
