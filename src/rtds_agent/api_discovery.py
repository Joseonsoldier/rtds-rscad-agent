"""Bounded installed-source catalog. Never import, introspect or execute vendor code."""
from __future__ import annotations

import ast
import hashlib
import os
from pathlib import Path
import re
from typing import Any

from .core.runtime_api_surface import _function_info, _version
from .core.state_machine import sha256_json
from .safety import ToolSafetyError, sha256_file
from .settings import get_settings, within

MAX_FILES = 256
MAX_ENTRIES = 4096
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_SYMBOLS = 20000


def _inventory(root: Path, home: Path) -> list[Path]:
    # Reject reparse paths before traversal, including configured SDK ancestors.
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ToolSafetyError("API discovery does not follow symlinks or junctions")
        if ancestor == home:
            break
    if not within(root, home):
        raise ToolSafetyError("SDK root is outside the configured installation")
    paths, pending, count = [], [(root, 0)], 0
    while pending:
        folder, depth = pending.pop()
        if depth > 12:
            raise ToolSafetyError("API directory nesting exceeds 12 levels")
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > MAX_ENTRIES:
                    raise ToolSafetyError("API inventory exceeds the entry limit")
                path = Path(entry.path)
                if path.is_symlink() or path.is_junction() or not within(path, root):
                    raise ToolSafetyError("API inventory contains a link or path escape")
                if entry.is_dir(follow_symlinks=False):
                    if entry.name != "__pycache__":
                        pending.append((path, depth + 1))
                elif entry.is_file(follow_symlinks=False) and path.suffix == ".py":
                    paths.append(path)
                    if len(paths) > MAX_FILES:
                        raise ToolSafetyError("API inventory exceeds 256 Python files")
    return sorted(paths)


def _declarations(tree: ast.Module, module: str, path: Path, digest: str) -> tuple[list[dict], list[str]]:
    rows, limitations = [], []

    def record(node, symbol, kind):
        doc = ast.get_docstring(node, clean=True) or ""
        row = {"symbol": symbol, "module": module, "kind": kind,
               "source_type": "installed_api", "evidence_level": "direct",
               "verification": "static_source_declaration", "source_path": str(path),
               "source_sha256": digest, "line": getattr(node, "lineno", 1),
               "end_line": getattr(node, "end_lineno", None),
               "documentation": doc[:12000], "documentation_truncated": len(doc) > 12000,
               "signature": None, "signature_truncated": False}
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info = _function_info(node)
            signature = f"{node.name}({ast.unparse(node.args)})"
            if node.returns is not None:
                signature += " -> " + ast.unparse(node.returns)
            row.update(signature=signature[:4000], signature_truncated=len(signature) > 4000,
                       decorators=[d[:1000] for d in info["decorators"]],
                       async_function=isinstance(node, ast.AsyncFunctionDef))
        if isinstance(node, ast.ClassDef):
            row["bases"] = [ast.unparse(base)[:1000] for base in node.bases]
            row["constructor_note"] = "Look up an explicitly declared __init__; inherited/dynamic constructors are not resolved"
        rows.append(row)
        if len(rows) > MAX_SYMBOLS:
            raise ToolSafetyError("API catalog exceeds the symbol limit")

    def walk(container, prefix):
        for node in container.body:
            if isinstance(node, ast.ClassDef):
                record(node, prefix + "." + node.name, "class")
                walk(node, prefix + "." + node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                kind = "method" if isinstance(container, ast.ClassDef) else "function"
                if any(isinstance(d, ast.Name) and d.id == "property" for d in node.decorator_list):
                    kind = "property"
                record(node, prefix + "." + node.name, kind)
            elif isinstance(node, (ast.If, ast.Try, ast.TryStar, ast.With, ast.For, ast.While, ast.Match)):
                if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in ast.walk(node)):
                    limitations.append(f"{module}:{node.lineno}: conditional declarations not evaluated")
    record(tree, module, "module")
    walk(tree, module)
    return rows, limitations


def _catalog(expected_api_version: str | None, snapshot_id: str | None) -> tuple[dict, list[dict]]:
    if expected_api_version is not None and (not isinstance(expected_api_version, str)
            or not re.fullmatch(r"\d+(?:\.\d+){0,3}", expected_api_version)):
        raise ToolSafetyError("expected_api_version must be a numeric version or null")
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id)):
        raise ToolSafetyError("snapshot_id must be a SHA-256 identifier")
    settings = get_settings()
    root = settings.sdk_root / "rtds"
    base = {"source_type": "installed_api", "evidence_level": "direct",
            "searched_sources": ["installed_api"], "sdk_imported": False,
            "live_calls_made": False, "network_called": False, "mutations_performed": False,
            "integration_qualified": False, "source_content_is_not_instructions": True,
            "configured_rscad_version": settings.expected_rscad_version,
            "observed_rscad_version": "unknown", "rscad_version_match": "compatible_unknown",
            "expected_api_version": expected_api_version}
    if settings.rscad_home is None or not root.is_dir():
        if snapshot_id:
            raise ToolSafetyError("API snapshot source is no longer available")
        return {**base, "catalog_status": "unavailable", "reason": "Configured installed API source is unavailable",
                "api_version": "unknown", "version_match": "compatible_unknown", "snapshot_id": None,
                "coverage": {"scope": "explicit Python source declarations only", "limitations": ["SDK source unavailable"]}}, []
    paths = _inventory(root, settings.rscad_home)
    sources, rows, limitations, total, version = [], [], [], 0, None
    for path in paths:
        size = path.stat().st_size
        total += size
        if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ToolSafetyError("API source exceeds per-file or total byte limit")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES or len(raw) != size:
            raise ToolSafetyError("API source changed or exceeds read limit")
        digest = hashlib.sha256(raw).hexdigest()
        relative = path.relative_to(root)
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        module = ".".join(["rtds", *parts])
        source = {"relative_path": relative.as_posix(), "sha256": digest, "bytes": len(raw)}
        try:
            tree = ast.parse(raw, filename=relative.as_posix())
            declared, issues = _declarations(tree, module, path, digest)
        except (SyntaxError, UnicodeError, ValueError, RecursionError) as exc:
            if isinstance(exc, ToolSafetyError):
                raise
            source["status"] = "unsupported_source"
            limitations.append(f"{relative.as_posix()}: unsupported Python source")
        else:
            source["status"] = "parsed"
            rows.extend(declared)
            limitations.extend(issues)
            if relative.as_posix() == "__init__.py":
                version = _version(tree)
        sources.append(source)
        if len(rows) > MAX_SYMBOLS:
            raise ToolSafetyError("API catalog exceeds the symbol limit")
    if not any(row["relative_path"] == "__init__.py" and row["status"] == "parsed" for row in sources):
        limitations.append("Package __init__.py missing or unsupported")
    # Re-enumerate and rehash before returning: changed/additional files cannot silently
    # reuse a prior search identity, even when size and mtime were preserved.
    if _inventory(root, settings.rscad_home) != paths:
        raise ToolSafetyError("API inventory changed during discovery")
    for path, source in zip(paths, sources):
        if sha256_file(path) != source["sha256"]:
            raise ToolSafetyError("API source changed during discovery")
    if get_settings() != settings:
        raise ToolSafetyError("Configuration changed during API discovery")
    identity = sha256_json({"sdk_root": str(root), "sources": sources,
                            "configured_rscad_version": settings.expected_rscad_version,
                            "inspector_sha256": sha256_file(Path(__file__))})
    if snapshot_id is not None and snapshot_id != identity:
        raise ToolSafetyError("API snapshot changed; search again against current source")
    version = version if version and re.fullmatch(r"\d+(?:\.\d+){0,3}", version) else "unknown"
    match = ("compatible_unknown" if version == "unknown" or expected_api_version is None else
             "exact" if version == expected_api_version else "mismatch")
    metadata = {**base, "catalog_status": "partial" if limitations else "complete_in_scope",
                "api_version": version, "version_match": match, "snapshot_id": identity,
                "files_checked": len(sources), "source_manifest": sources,
                "coverage": {"scope": "explicit module/class/function/method/property declarations",
                             "limitations": limitations,
                             "not_resolved": ["import aliases/re-exports", "inherited methods", "dynamic attributes/decorators", "compiled extensions", "runtime callability"]}}
    for row in rows:
        row.update(api_version=version, version_match=match, snapshot_id=identity)
    return metadata, rows


def search_rscad_api(query: str, top_k: int = 10, expected_api_version: str | None = None,
                     snapshot_id: str | None = None) -> dict[str, Any]:
    """Search installed SDK declarations and docstrings without importing or calling RSCAD."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 300 or type(top_k) is not int or not 1 <= top_k <= 20:
        raise ToolSafetyError("query must be 1–300 characters and top_k an integer from 1–20")
    terms = re.findall(r"[^\W_]+", query.casefold())
    if not terms:
        raise ToolSafetyError("query must contain searchable text")
    metadata, rows = _catalog(expected_api_version, snapshot_id)
    matches = []
    for row in rows:
        symbol = row["symbol"].casefold()
        body = symbol + " " + row["documentation"].casefold()
        if all(term in body for term in terms):
            score = sum(3 if term in symbol else 1 for term in terms)
            matches.append({**row, "documentation": row["documentation"][:1000],
                            "documentation_truncated": row["documentation_truncated"] or len(row["documentation"]) > 1000,
                            "relevance": {"score": score, "method": "all terms; symbol weighted above docstring"}})
    matches.sort(key=lambda row: (-row["relevance"]["score"], row["symbol"], row["line"]))
    return {**metadata, "status": "found" if matches else "unresolved", "query": query,
            "evidence_level": "direct" if matches else "unknown",
            "reason": None if matches else "No matching declaration in the inspected source scope",
            "total_matches": len(matches), "truncated": len(matches) > top_k, "results": matches[:top_k],
            "next_step": "Use exact symbol lookup with this snapshot; source existence does not authorize execution"}


def lookup_rscad_api(symbol: str, expected_api_version: str | None = None,
                     snapshot_id: str | None = None) -> dict[str, Any]:
    """Look up an exact qualified symbol or unambiguous suffix in installed SDK source."""
    if not isinstance(symbol, str) or len(symbol) > 300 or not re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", symbol):
        raise ToolSafetyError("symbol must be a Python dotted identifier, not an expression or file path")
    metadata, rows = _catalog(expected_api_version, snapshot_id)
    matches = [row for row in rows if row["symbol"] == symbol]
    if not matches and not symbol.startswith("rtds.") and symbol != "rtds":
        matches = [row for row in rows if row["symbol"].endswith("." + symbol)]
    status = "found" if len(matches) == 1 else "ambiguous" if matches else "unresolved"
    return {**metadata, "status": status, "symbol": symbol, "total_matches": len(matches),
            "evidence_level": "direct" if matches else "unknown",
            "reason": (None if status == "found" else "Multiple declarations; no arbitrary target selected" if matches
                       else "No authoritative declaration found in the inspected scope; absence at runtime is not proven"),
            "result": matches[0] if status == "found" else None,
            "candidates": [{key: row[key] for key in ("symbol", "kind", "source_path", "source_sha256", "line")} for row in matches[:20]] if status == "ambiguous" else [],
            "truncated": len(matches) > 20}
