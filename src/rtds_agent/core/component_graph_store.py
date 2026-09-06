"""Immutable local graph publication; no source, SDK or policy mutations."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from ..safety import ToolSafetyError
from ..settings import get_settings, within

MAX_BYTES = 128 * 1024 * 1024
MAX_GENERATIONS = 128
IDENTITY = re.compile(r"[0-9a-f]{64}")


def safe_path(path: Path, root: Path) -> Path:
    if not path.is_absolute() or not within(path, root):
        raise ToolSafetyError("Component graph path escapes its configured root")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ToolSafetyError("Component graph refuses linked paths or ancestors")
    return path


def cache_root(settings=None):
    settings = settings or get_settings()
    return safe_path(settings.data_dir / "knowledge" / "component_graphs", settings.data_dir)


def graph_path(graph_id, settings=None):
    if not isinstance(graph_id, str) or IDENTITY.fullmatch(graph_id) is None:
        raise ToolSafetyError("graph_id must be a lowercase SHA-256 identifier")
    root = cache_root(settings)
    return safe_path(root / graph_id / "graph.json", root)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ToolSafetyError("Duplicate component graph JSON key")
        result[key] = value
    return result


def read_object(path, maximum=MAX_BYTES):
    if not path.is_file() or path.stat().st_size > maximum:
        raise ToolSafetyError("Component graph JSON is missing or exceeds its size limit")
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ToolSafetyError("Component graph JSON exceeds its size limit")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ToolSafetyError("Invalid component graph JSON") from exc
    if not isinstance(value, dict):
        raise ToolSafetyError("Component graph JSON must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def status():
    root = cache_root()
    if not root.exists():
        return {"status": "absent", "graph_ids": [], "writes_performed": False}
    ids = []
    for index, entry in enumerate(root.iterdir()):
        if index >= MAX_GENERATIONS * 3:
            raise ToolSafetyError("Component graph cache exceeds traversal bounds")
        if IDENTITY.fullmatch(entry.name):
            path = graph_path(entry.name)
            if not entry.is_dir() or not path.is_file():
                raise ToolSafetyError("Incomplete published component graph")
            ids.append(entry.name)
    if len(ids) > MAX_GENERATIONS:
        raise ToolSafetyError("Component graph cache exceeds generation limit")
    return {"status": "available_unverified" if ids else "absent", "graph_ids": sorted(ids),
            "verification": "Each query verifies graph and current source hashes", "writes_performed": False}


@contextmanager
def _writer(root):
    root.mkdir(parents=True, exist_ok=True)
    safe_path(root, get_settings().data_dir)
    lock = safe_path(root / ".writer-lock", root)
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ToolSafetyError("Component graph writer conflict; inspect a stale writer lock before manual cleanup") from exc
    try:
        yield
    finally:
        lock.rmdir()


def publish(graph, revalidate):
    """Publish one complete generation by atomic directory rename, without overwrite."""
    graph_id = graph["graph_sha256"]
    target = graph_path(graph_id)
    root = cache_root()
    raw = (json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()
    if len(raw) > MAX_BYTES:
        raise ToolSafetyError("Component graph exceeds 128 MiB")
    with _writer(root):
        revalidate()
        if target.exists():
            existing, _ = read_object(target)
            if existing != graph:
                raise ToolSafetyError("Existing component graph differs; immutable generations are never overwritten")
            safe_path(target, root)
            revalidate()
            return {"status": "already_present", "graph_id": graph_id, "graph_path": str(target)}
        if len(status()["graph_ids"]) >= MAX_GENERATIONS:
            raise ToolSafetyError("Component graph generation limit reached; preserve or archive existing data explicitly")
        staging = safe_path(root / (".staging-" + uuid.uuid4().hex), root)
        staging.mkdir()
        with (staging / "graph.json").open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        revalidate()
        safe_path(staging, root)
        safe_path(target.parent, root)
        os.rename(staging, target.parent)
    return {"status": "published", "graph_id": graph_id, "graph_path": str(target)}
