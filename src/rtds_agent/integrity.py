"""Portable release hash manifest, separate from local experiment evidence."""
from pathlib import Path
import json

from .core.state_machine import sha256_file, sha256_json


def verify_release() -> dict:
    root = Path(__file__).resolve().parent
    path = root / "release_manifest.json"
    if not path.is_file():
        raise PermissionError("Release integrity manifest is missing; live execution disabled")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    expected = manifest.get("files", {})
    actual_paths = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".json"} and p != path}
    if set(expected) != actual_paths:
        raise PermissionError("Release file inventory differs from manifest")
    for name, digest in expected.items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or sha256_file(target) != digest:
            raise PermissionError(f"Release code/schema hash mismatch: {name}")
    return {"status": "passed", "files": len(expected), "manifest_sha256": sha256_json(manifest),
            "scope": "local accidental-change detection; not a signature or protection against a malicious local administrator"}
