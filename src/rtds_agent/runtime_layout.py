"""Bounded disk-only Runtime layout inventory; no live signal/control discovery."""
from __future__ import annotations
from typing import Any, Literal
import hashlib
from io import BytesIO
from pathlib import Path
import zipfile
from .project_tools import _document, _pagination
from .safety import ToolSafetyError, sha256_file
from .core.state_machine import sha256_json
from .core.runtime_parser import parse_runtime_layout, SUPPORTED, CONTROLS
from .core.runtime_ir import runtime_ir

def inspect_runtime_layout(project_path: str, snapshot_id: str | None = None,
                           offset: int = 0, limit: int = 100,
                           representation: Literal["inventory", "ir"] = "inventory") -> dict[str, Any]:
    """Read saved Runtime inventory or bounded semantic IR; never confirm a live target or author an overlay."""
    if representation not in {"inventory","ir"}:raise ToolSafetyError("Unsupported Runtime representation")
    if representation=="ir" and (offset!=0 or limit!=100):raise ToolSafetyError("Runtime IR is whole-document; inventory supports pagination")
    target, _, document = _document(project_path)
    parser_sources = {p.name:sha256_file(p) for p in (Path(__file__),Path(__file__).parent/'core/runtime_parser.py',Path(__file__).parent/'core/runtime_ir.py')}
    layout_snapshot = sha256_json({"project_snapshot_id": document["snapshot_id"], "parser_sources":parser_sources})
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
    if representation=="ir":
        ir=runtime_ir(parsed,document,snapshot_id=layout_snapshot,member=names[0],member_sha256=hashlib.sha256(raw).hexdigest())
        return {"status":ir["status"],"snapshot_id":layout_snapshot,"project_snapshot_id":document["snapshot_id"],
                "source_sha256":document["source"]["rtfx_sha256"],"runtime_ir":ir,"live_calls_made":False,"gui_observed":False,"saved_state_only":True}
    page = _pagination(len(parsed["records"]), limit, offset, snapshot_id)
    records = parsed.pop("records")
    for record in records:
        record["record_key"] = sha256_json({"snapshot_id": layout_snapshot, "member": names[0], "index": record["record_index"]})
    return {**parsed, "snapshot_id": layout_snapshot, "project_snapshot_id": document["snapshot_id"], "source_sha256": document["source"]["rtfx_sha256"],
            "member": names[0], "total_count": len(records), **page, "records": records[offset:offset + limit],
            "live_calls_made": False, "gui_observed": False, "saved_state_only": True,
            "limitations": ["This is a disk layout, not live signal/control enumeration", "No units, current values or active GUI session are inferred",
                            "Plot graph/curve parsing covers a stored subset; numeric samples are not parsed and duplicate IDs are not silently resolved"]}
