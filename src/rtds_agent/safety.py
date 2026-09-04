"""Shared path boundaries and credentials for portable local tools."""
from pathlib import Path
import json
import os

from .settings import get_settings, within
from .core.state_machine import sha256_file

_SETTINGS = get_settings()
AGENT_ROOT = _SETTINGS.data_dir
WORKING_PROJECT_ROOT = _SETTINGS.projects_root
DEFINITION_ROOT = _SETTINGS.definition_root


class ToolSafetyError(ValueError):
    pass


def is_within(path: str | Path, root: str | Path) -> bool:
    return within(Path(path), Path(root))


def checked_file(value: str, roots: tuple[Path, ...], suffix: str | None = None) -> Path:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ToolSafetyError("Expected an absolute file path")
    path = Path(value)
    if not path.is_absolute():
        raise ToolSafetyError("File path must be absolute")
    path = path.resolve()
    if not path.is_file() or not any(within(path, root) for root in roots):
        raise ToolSafetyError("File is missing or outside configured roots")
    if suffix and path.suffix.lower() != suffix:
        raise ToolSafetyError(f"Expected a {suffix} file")
    return path


def resolve_rtfx_path(project_path: str) -> tuple[Path, str]:
    settings = get_settings()
    path = checked_file(project_path, (*settings.source_roots, settings.projects_root), ".rtfx")
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ToolSafetyError("RTFX exceeds 128 MiB")
    import zipfile
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(entries) > 5000 or len(names) != len(set(names)) or sum(e.file_size for e in entries) > 256 * 1024 * 1024:
            raise ToolSafetyError("RTFX archive exceeds limits or contains duplicate entries")
        if any(e.flag_bits & 1 for e in entries):
            raise ToolSafetyError("Encrypted RTFX archives are unsupported")
    return path, "agent_working_copy" if within(path, settings.projects_root) else "source_read_only"


def read_json(path: Path) -> dict:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ToolSafetyError("JSON file exceeds 20 MiB")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ToolSafetyError("Expected a JSON object")
    return value


def read_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ToolSafetyError("Set OPENAI_API_KEY in the MCP host environment")
    return key
