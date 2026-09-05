"""Bounded disk-only Runtime layout inventory; no live signal/control discovery."""
from __future__ import annotations
from typing import Any
from collections import Counter
import re
import hashlib
from io import BytesIO
from pathlib import Path
import zipfile
from .project_tools import _document, _pagination
from .safety import ToolSafetyError, sha256_file
from .core.state_machine import sha256_json

SUPPORTED = {"METER", "SLIDER", "SWITCH", "DIAL", "PUSHBUTTON", "BINARY_SWITCH", "DRAFT_VARIABLE", "PLOT", "FRAME"}
CONTROLS = {"SLIDER", "SWITCH", "DIAL", "PUSHBUTTON", "BINARY_SWITCH", "DRAFT_VARIABLE"}


def parse_runtime_layout(text: str) -> dict[str, Any]:
    """Parse supported component headers, retaining duplicates and unknown records."""
    if len(text.encode("utf-8")) > 16 * 1024 * 1024:
        raise ToolSafetyError("Runtime layout exceeds 16 MiB")
    records, stack, warnings = [], [], []
    view = None
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if line.startswith("VIEW-START:"):
            if stack:
                raise ToolSafetyError("Runtime view starts inside an unclosed component")
            match = re.search(r'VIEW-ID:\s*"([^"\r\n]+)"', line)
            view = match.group(1) if match else None
            if view is None:
                warnings.append(f"line {line_no}: unsupported view identity")
        elif line.startswith("VIEW-END:"):
            if stack:
                raise ToolSafetyError("Runtime view ends inside an unclosed component")
            view = None
        elif line.startswith("COMPONENT:"):
            if len(records) >= 10000 or len(stack) >= 32:
                raise ToolSafetyError("Runtime layout component/depth limit exceeded")
            stored_type = line.split(":", 1)[1].strip()
            kind = stored_type.removeprefix("TAGGED_V2.2_")
            record = {"index": len(records), "parent_index": stack[-1] if stack else None,
                      "view_id": view, "stored_type": stored_type, "kind": kind,
                      "source_line": line_no, "fields": {}, "references": [], "header_closed": False,
                      "pending_group": None, "field_ambiguities": []}
            if stack:
                records[stack[-1]]["header_closed"] = True
            records.append(record)
            stack.append(record["index"])
        elif line == "COMPONENT-END:":
            if not stack:
                raise ToolSafetyError("Orphan Runtime component end")
            records[stack.pop()]["end_line"] = line_no
        elif stack:
            record = records[stack[-1]]
            if re.search(r"(?:^|-)DATA-START$", line) or line.endswith("-DATA-START:"):
                record["header_closed"] = True
            if record["header_closed"] or ":" not in line:
                continue
            key, value = (part.strip() for part in line.split(":", 1))
            if len(value) > 4096:
                raise ToolSafetyError("Runtime header value exceeds limit")
            if key == "GROUP":
                record["pending_group"] = value
            elif key == "DESC":
                group = record["pending_group"]
                record["references"].append({"group": group, "description": value,
                    "stored_signal_path": group + "|" + value if group and group != "(NONE)" and value else None})
            elif key in {"UUID", "NAME", "UNITS", "MIN", "MAX", "comp_locX", "comp_locY", "comp_width", "comp_height"}:
                if key in record["fields"]:
                    record["field_ambiguities"].append(key)
                record["fields"][key] = value
    if stack:
        raise ToolSafetyError("Unclosed Runtime component; inventory is incomplete")
    uuids = Counter(r["fields"].get("UUID") for r in records if r["fields"].get("UUID"))
    result = []
    for record in records:
        fields = record["fields"]
        value = fields.get("UUID", "")
        uuid = int(value) if re.fullmatch(r"[0-9]{1,16}", value) else None
        ambiguous = bool(record["field_ambiguities"]) or uuid is None or uuids[value] > 1
        kind = record["kind"]
        result.append({"record_index": record["index"], "parent_index": record["parent_index"],
                       "view_id": record["view_id"], "component_id": uuid, "stored_type": record["stored_type"],
                       "kind": kind, "role": "control" if kind in CONTROLS else "display" if kind in SUPPORTED else "unknown",
                       "parse_status": "supported_header" if kind in SUPPORTED else "unsupported_type",
                       "identity_status": "ambiguous" if ambiguous else "stored_unique",
                       "field_ambiguities": record["field_ambiguities"], "name": fields.get("NAME"),
                       "stored_units": fields.get("UNITS"), "observed_units": None, "observed_value": None,
                       "stored_configuration": {k: v for k, v in fields.items() if k not in {"UUID", "NAME", "UNITS"}},
                       "signal_references": record["references"], "source_line": record["source_line"], "end_line": record["end_line"],
                       "evidence_level": "saved_runtime_layout", "live_target_verified": False})
    unsupported = sum(r["parse_status"] != "supported_header" for r in result)
    return {"records": result, "warnings": warnings, "unsupported_count": unsupported,
            "status": "partial" if unsupported or warnings or any(r["identity_status"] == "ambiguous" for r in result) else "available"}


def inspect_runtime_layout(project_path: str, snapshot_id: str | None = None,
                           offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Read saved Runtime headers with source snapshots; never confirm a live target or GUI."""
    target, _, document = _document(project_path)
    layout_snapshot = sha256_json({"project_snapshot_id": document["snapshot_id"], "layout_parser_sha256": sha256_file(Path(__file__))})
    if snapshot_id is not None and snapshot_id != layout_snapshot:
        raise ToolSafetyError("Runtime layout snapshot changed; restart pagination")
    with target.open("rb") as stream:
        project_bytes = stream.read(128 * 1024 * 1024 + 1)
    if len(project_bytes) > 128 * 1024 * 1024 or hashlib.sha256(project_bytes).hexdigest() != document["source"]["rtfx_sha256"]:
        raise ToolSafetyError("Runtime project bytes differ from the observed snapshot")
    with zipfile.ZipFile(BytesIO(project_bytes)) as archive:
        names = [n for n in archive.namelist() if n.lower().endswith(".rtx")]
        if len(names) != 1:
            return {"status": "unsupported", "reason": "Exactly one saved RTX layout is required", "snapshot_id": layout_snapshot, "live_calls_made": False}
        if archive.getinfo(names[0]).file_size > 16 * 1024 * 1024:
            raise ToolSafetyError("Runtime layout exceeds 16 MiB")
        raw = archive.read(names[0])
        try:
            parsed = parse_runtime_layout(raw.decode("utf-8-sig"))
        except UnicodeError as exc:
            raise ToolSafetyError("Runtime layout encoding is unsupported") from exc
    _document(project_path, document["snapshot_id"])
    page = _pagination(len(parsed["records"]), limit, offset, snapshot_id)
    records = parsed.pop("records")
    for record in records:
        record["record_key"] = sha256_json({"snapshot_id": layout_snapshot, "member": names[0], "index": record["record_index"]})
    return {**parsed, "snapshot_id": layout_snapshot, "project_snapshot_id": document["snapshot_id"], "source_sha256": document["source"]["rtfx_sha256"],
            "member": names[0], "total_count": len(records), **page, "records": records[offset:offset + limit],
            "live_calls_made": False, "gui_observed": False, "saved_state_only": True,
            "limitations": ["This is a disk layout, not live signal/control enumeration", "No units, current values or active GUI session are inferred",
                            "Plot graph internals are outside header parsing; duplicate IDs are not silently resolved"]}
