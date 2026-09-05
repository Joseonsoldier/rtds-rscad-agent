"""Verify exact document/hash/page and declared requirement-to-test mappings."""
from .settings import get_settings
from .safety import checked_file, sha256_file, ToolSafetyError


def verify_traceability(spec):
    from .knowledge import get_manual_page
    requirements = {r["requirement_id"]:r for r in spec["criteria"]["requirements"]}
    if len(requirements) != len(spec["criteria"]["requirements"]): raise ToolSafetyError("Duplicate requirement ID")
    channels, events = {c["channel_id"] for c in spec["channels"]}, {e["event_id"] for e in spec["events"]}
    traced, result = set(), []
    for row in spec["traceability"]:
        key = row["requirement_id"]
        if key not in requirements or key in traced: raise ToolSafetyError("Trace requirement is absent or duplicated")
        if not set(row["channel_ids"]) <= channels or not set(row["event_ids"]) <= events:
            raise ToolSafetyError("Trace maps missing event/channel identities")
        if requirements[key]["channel_id"] not in row["channel_ids"]:
            raise ToolSafetyError("Trace does not include the criterion's channel")
        path = checked_file(row["source_path"],get_settings().document_roots)
        if sha256_file(path) != row["source_sha256"]: raise ToolSafetyError("Requirement document hash mismatch")
        page = get_manual_page(str(path),row["page"])
        if page.get("source_sha256") != row["source_sha256"]: raise ToolSafetyError("Requirement page source changed")
        traced.add(key)
        result.append({**row,"document_hash_and_page_verified":True,"statement_interpretation_verified":False,
                       "criterion":requirements[key],"engineering_verdict":"not_evaluated"})
    if any(r["provenance"]["kind"] == "cited_document" and key not in traced for key,r in requirements.items()):
        raise ToolSafetyError("Cited-document criteria require document/hash/page traceability")
    return result
