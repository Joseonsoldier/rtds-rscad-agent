"""Read and explicitly export the bundled, versioned instruction-only skills.

This module neither selects a host discovery path nor changes host configuration.
"""
from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
import re

from . import __version__

SKILL_NAMES = (
    "rscad-understand-model",
    "rscad-edit-model",
    "rscad-diagnose-compile",
    "rtds-run-experiment",
    "rtds-validate-results",
    "rtds-ground-with-manuals",
    "rtds-read-documentation",
    "rtds-derive-test-requirements",
    "rtds-verify-grid-code",
)
_SAFE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")


def _select(names: list[str] | tuple[str, ...] | None) -> tuple[str, ...]:
    selected = SKILL_NAMES if names is None else tuple(names)
    if not selected or len(set(selected)) != len(selected):
        raise ValueError("Select one or more unique skill names")
    if any(name not in SKILL_NAMES for name in selected):
        raise ValueError("Unknown skill name; use the bundled skill catalog")
    return selected


def _bundled_files(name: str) -> dict[str, bytes]:
    root = resources.files("rtds_agent").joinpath("skills", name)
    if isinstance(root, Path) and (root.is_symlink() or root.is_junction()):
        raise ValueError("Bundled skill directory cannot be a link")
    result: dict[str, bytes] = {}

    def visit(node, prefix: str = ""):
        for child in sorted(node.iterdir(), key=lambda item: item.name):
            if not _SAFE_PART.fullmatch(child.name) or child.name in {".", ".."}:
                raise ValueError("Unsafe bundled skill resource path")
            if isinstance(child, Path) and (child.is_symlink() or child.is_junction()):
                raise ValueError("Bundled skill resources cannot be links")
            relative = prefix + child.name
            if child.is_dir():
                visit(child, relative + "/")
            elif child.is_file() and (child.name.endswith(".md") or child.name == "manifest.json"):
                result[relative] = child.read_bytes()
            else:
                raise ValueError("Unsupported bundled skill resource")

    visit(root)
    if "SKILL.md" not in result:
        raise ValueError("Bundled skill is missing SKILL.md")
    return result


def _metadata(body: bytes) -> dict[str, str]:
    lines = body.decode("utf-8").splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("Skill must have frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("Skill frontmatter is incomplete") from exc
    values = {}
    for line in lines[1:end]:
        key, separator, value = line.partition(":")
        if not separator or key not in {"name", "description"} or key in values:
            raise ValueError("Unsupported or duplicate skill metadata")
        value = value.strip()
        values[key] = json.loads(value) if value.startswith('"') else value
    if set(values) != {"name", "description"} or any(not isinstance(v, str) or not v.strip() for v in values.values()):
        raise ValueError("Skill name and description are required")
    return values


def list_skills() -> dict:
    """List packaged resources without consulting the operator's configuration."""
    skills = []
    for name in SKILL_NAMES:
        files = _bundled_files(name)
        metadata = _metadata(files["SKILL.md"])
        if metadata["name"] != name:
            raise ValueError("Skill directory and frontmatter name differ")
        manifest = json.loads(files["manifest.json"])
        if manifest.get("name") != name or set(manifest) != {"name","version","required_tools","optional_tools","required_capabilities","minimum_api","safety_class","tags","examples"}:
            raise ValueError("Invalid skill capability manifest")
        skills.append({**metadata, "manifest":manifest, "files": [
            {"path": relative, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
            for relative, body in files.items()
        ]})
    return {"package_version": __version__, "skills": skills, "host_configuration_changed": False}


def _reject_links(path: Path) -> None:
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or part.is_junction():
            raise ValueError("Skill export does not follow symlinks or junctions")
        if part.exists() and not part.is_dir():
            raise ValueError("Skill export destination parent is not a directory")


def _destination(destination: str | Path) -> Path:
    if not isinstance(destination, (str, Path)) or not str(destination).strip():
        raise ValueError("An explicit export destination is required")
    requested = Path(destination).expanduser()
    if ".." in requested.parts:
        raise ValueError("Skill export destination cannot contain parent traversal")
    absolute = requested.absolute()
    _reject_links(absolute)
    target = absolute.resolve()
    if target == Path(target.anchor):
        raise ValueError("A filesystem root is not a skill export destination")
    package_root = resources.files("rtds_agent")
    if isinstance(package_root, Path) and target.is_relative_to(package_root.resolve()):
        raise ValueError("Cannot export over installed package resources")
    return target


def export_skills(destination: str | Path, *, dry_run: bool = False,
                  names: list[str] | tuple[str, ...] | None = None) -> dict:
    """Export selected skill directories with exclusive writes and no overwrite.

    Preflight all collisions, reject path traversal and filesystem links, and
    clean up only files/directories created by this call if publication fails.
    Export is an explicit file operation, not proof of host skill discovery.
    """
    if not isinstance(dry_run, bool):
        raise ValueError("dry_run must be a boolean")
    selected = _select(names)
    target = _destination(destination)
    bundled = {name: _bundled_files(name) for name in selected}
    for name in selected:
        output = target / name
        if output.exists() or output.is_symlink() or output.is_junction():
            raise FileExistsError(f"Skill export conflict: {name}; existing contents are preserved")
    files = [f"{name}/{relative}" for name in selected for relative in bundled[name]]
    result = {"package_version": __version__, "destination": str(target),
              "skills": list(selected), "files": files, "dry_run": dry_run,
              "host_configuration_changed": False, "host_discovery_verified": False}
    if dry_run:
        return {**result, "status": "dry_run", "files_written": 0}
    created_files: list[Path] = []
    created_dirs: list[Path] = []

    def mkdir(path: Path):
        _reject_links(path)
        if path.exists():
            return
        if not path.parent.exists():
            mkdir(path.parent)
        path.mkdir()
        created_dirs.append(path)

    try:
        mkdir(target)
        # Claim every skill directory before exposing any SKILL.md entrypoint.
        for name in selected:
            _reject_links(target)
            output = target / name
            output.mkdir()
            created_dirs.append(output)
        for name in selected:
            for relative, body in bundled[name].items():
                output = target / name / relative
                mkdir(output.parent)
                _reject_links(output.parent)
                if not output.resolve().is_relative_to(target):
                    raise ValueError("Skill export path escaped destination")
                with output.open("xb") as stream:
                    created_files.append(output)
                    stream.write(body)
    except Exception:
        for path in reversed(created_files):
            if path.parent.resolve().is_relative_to(target) and not path.is_symlink():
                path.unlink(missing_ok=True)
        for path in reversed(created_dirs):
            if not path.is_symlink() and not path.is_junction():
                try:
                    path.rmdir()
                except OSError:
                    pass
        raise
    return {**result, "status": "exported", "files_written": len(created_files)}
