"""Immutable, hash-verified local parameter catalog generations.

Only entries referenced by the atomic pointer are published. A crashed writer's
staging directory or orphan generation cannot become lookup evidence.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Iterator
import uuid

from rtds_agent.settings import get_settings, within
from rtds_agent.safety import ToolSafetyError, resolve_rtfx_path
from .state_machine import sha256_file, now_iso
from .topology_parser import DefinitionIndex, parse_parameter_schema, parse_dfx_components, read_rtfx_dfx


COLUMNS = ("component", "parameter", "rscad_version", "data_type", "unit", "default_value",
           "minimum", "maximum", "enum_values_json", "description", "definition_path",
           "definition_sha256", "verification_status", "raw_definition")
TABLE_SQL = """CREATE TABLE parameters(component TEXT, parameter TEXT, rscad_version TEXT,
data_type TEXT, unit TEXT, default_value TEXT, minimum REAL, maximum REAL,
enum_values_json TEXT, description TEXT, definition_path TEXT, definition_sha256 TEXT,
verification_status TEXT, raw_definition TEXT, PRIMARY KEY(component,parameter,rscad_version))"""
SCOPE = "definition parsing and provenance only; no simulation/engineering verdict"
_ID = re.compile(r"[0-9a-f]{32}")
_HASH = re.compile(r"[0-9a-f]{64}")


def _inside(path: Path, root: Path) -> Path:
    if not within(path, root):
        raise ToolSafetyError("Parameter catalog path escapes its configured root")
    return path


def _root() -> Path:
    settings = get_settings()
    return _inside(settings.data_dir / "knowledge" / "parameter_catalog", settings.data_dir)


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > 20 * 1024 * 1024:
        raise ToolSafetyError("Parameter catalog JSON is missing or exceeds its size limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ToolSafetyError("Invalid parameter catalog JSON") from exc
    if not isinstance(value, dict):
        raise ToolSafetyError("Parameter catalog JSON must be an object")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _pointer(root: Path) -> dict[str, Any]:
    path = _inside(root / "current.json", root)
    if not path.exists():
        return {"schema_version": 1, "snapshots": [], "current_snapshot_id": None}
    value = _json(path)
    entries = value.get("snapshots")
    if value.get("schema_version") != 1 or not isinstance(entries, list):
        raise ToolSafetyError("Unsupported parameter catalog pointer schema")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ToolSafetyError("Invalid parameter catalog pointer entry")
        identity, digest = entry.get("snapshot_id"), entry.get("audit_sha256")
        if not isinstance(identity, str) or not _ID.fullmatch(identity) or identity in seen:
            raise ToolSafetyError("Invalid or duplicate parameter catalog snapshot ID")
        if not isinstance(digest, str) or not _HASH.fullmatch(digest):
            raise ToolSafetyError("Invalid parameter catalog audit hash")
        seen.add(identity)
    if not entries or value.get("current_snapshot_id") != entries[-1]["snapshot_id"]:
        raise ToolSafetyError("Parameter catalog current pointer is inconsistent")
    return value


@contextmanager
def _writer(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock = _inside(root / ".writer-lock", root)
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ToolSafetyError("Parameter catalog writer conflict; retry after the current writer completes. A stale lock requires deliberate operator cleanup.") from exc
    try:
        yield
    finally:
        lock.rmdir()


def _definition(row: dict[str, Any]) -> None:
    settings = get_settings()
    value, digest = row.get("definition_path"), row.get("definition_sha256")
    if not isinstance(value, str) or not isinstance(digest, str) or not _HASH.fullmatch(digest):
        raise ToolSafetyError("Invalid parameter definition provenance")
    path = Path(value)
    if (not path.is_absolute() or not within(path, settings.definition_root)
            or not path.is_file() or sha256_file(path) != digest):
        raise ToolSafetyError("Installed parameter definition provenance failed: stale or outside configured root")


def _rows(database: Path) -> list[dict[str, Any]]:
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ToolSafetyError("Parameter catalog database integrity check failed")
            if tuple(row[1] for row in connection.execute("PRAGMA table_info(parameters)")) != COLUMNS:
                raise ToolSafetyError("Unsupported parameter database schema")
            rows = [dict(row) for row in connection.execute("SELECT * FROM parameters")]
    except sqlite3.Error as exc:
        raise ToolSafetyError("Invalid parameter catalog database") from exc
    keys = set()
    for row in rows:
        if any(not isinstance(row.get(key), str) or not row[key]
               for key in ("component", "parameter", "rscad_version", "data_type", "verification_status")):
            raise ToolSafetyError("Incomplete parameter database row")
        key = (row["component"].casefold(), row["parameter"].casefold(), row["rscad_version"])
        if key in keys:
            raise ToolSafetyError("Ambiguous case-insensitive parameter database key")
        keys.add(key)
    return rows


def _verify_audit(database: Path, audit_path: Path, *, expected_hash: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not database.is_file() or not audit_path.is_file():
        raise ToolSafetyError("Parameter catalog database or audit is missing")
    observed_audit_hash = sha256_file(audit_path)
    if expected_hash is not None and observed_audit_hash != expected_hash:
        raise ToolSafetyError("Parameter catalog audit hash differs from published evidence")
    audit = _json(audit_path)
    checks = audit.get("checks")
    if audit.get("status") != "passed" or not isinstance(checks, dict) or not checks or not all(v is True for v in checks.values()):
        raise ToolSafetyError("Parameter DB audit is not passed")
    recorded = audit.get("database", {})
    if not isinstance(recorded, dict) or recorded.get("path") != str(database):
        raise ToolSafetyError("Parameter DB audit path differs from its generation")
    digest = sha256_file(database)
    if recorded.get("sha256") != digest:
        raise ToolSafetyError("Parameter DB hash differs from its passed audit")
    rows = _rows(database)
    if audit.get("parameters") != len(rows):
        raise ToolSafetyError("Parameter audit count differs from its database")
    if sha256_file(database) != digest or sha256_file(audit_path) != observed_audit_hash:
        raise ToolSafetyError("Parameter catalog changed while reading")
    return audit, rows


def _generation(root: Path, entry: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    folder = _inside(root / "snapshots" / entry["snapshot_id"], root)
    database = _inside(folder / "parameters.sqlite", root)
    audit_path = _inside(folder / "audit.json", root)
    audit, rows = _verify_audit(database, audit_path, expected_hash=entry["audit_sha256"])
    if audit.get("schema_version") != 1 or audit.get("parameter_catalog_snapshot_id") != entry["snapshot_id"]:
        raise ToolSafetyError("Parameter catalog snapshot identity differs from its audit")
    return audit, rows, audit_path


def _legacy() -> tuple[dict[str, Any], list[dict[str, Any]], Path]:
    settings = get_settings()
    folder = _inside(settings.data_dir / "knowledge", settings.data_dir)
    database = _inside(folder / "parameters.sqlite", folder)
    audit_path = _inside(folder / "parameter_audit.json", folder)
    if not database.is_file() or not audit_path.is_file():
        raise ToolSafetyError("Audited parameter DB evidence is missing")
    audit, rows = _verify_audit(database, audit_path)
    return audit, rows, audit_path


def read_audit(snapshot_id: str | None = None) -> tuple[dict[str, Any], str]:
    root = _root()
    pointer = _pointer(root)
    if not pointer["snapshots"] and snapshot_id is None:
        audit, _, _ = _legacy()
    else:
        selected = snapshot_id if snapshot_id is not None else pointer["current_snapshot_id"]
        matches = [row for row in pointer["snapshots"] if row["snapshot_id"] == selected]
        if len(matches) != 1:
            raise ToolSafetyError("Unknown or unpublished parameter catalog snapshot ID")
        audit, _, _ = _generation(root, matches[0])
    return audit, audit["database"]["sha256"]


def lookup(component_type: str, parameter: str, rscad_version: str, snapshot_id: str | None = None) -> dict[str, Any]:
    if any(not isinstance(value, str) or not value.strip() for value in (component_type, parameter, rscad_version)):
        raise ToolSafetyError("Component, parameter and RSCAD version must be non-empty strings")
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or not _ID.fullmatch(snapshot_id)):
        raise ToolSafetyError("Invalid parameter catalog snapshot ID")
    root = _root()
    pointer = _pointer(root)
    entries = pointer["snapshots"]
    if snapshot_id is not None:
        entries = [entry for entry in entries if entry["snapshot_id"] == snapshot_id]
        if not entries:
            raise ToolSafetyError("Unknown or unpublished parameter catalog snapshot ID")
    evidence = [_generation(root, entry) for entry in entries]
    if not pointer["snapshots"] and snapshot_id is None:
        evidence = [_legacy()]
    matches = []
    for audit, rows, audit_path in evidence:
        for row in rows:
            if (row["component"].casefold() == component_type.casefold()
                    and row["parameter"].casefold() == parameter.casefold()
                    and row["rscad_version"] == rscad_version):
                matches.append((row, audit, audit_path))
    if not matches:
        raise ToolSafetyError("Parameter is outside the audited component/parameter/version subset")
    identities = {(row["definition_sha256"], str(Path(row["definition_path"]).resolve())) for row, _, _ in matches}
    if len(identities) != 1:
        raise ToolSafetyError("Ambiguous parameter definition evidence; supply parameter_catalog_snapshot_id")
    row, audit, audit_path = matches[-1]
    _definition(row)
    return {**row, "source_type": "installed_definition", "evidence_level": "direct",
            "version_match": "compatible_unknown",
            "parameter_catalog_snapshot_id": audit.get("parameter_catalog_snapshot_id"),
            "parameter_database_sha256": audit["database"]["sha256"],
            "parameter_audit_path": str(audit_path), "parameter_audit_sha256": sha256_file(audit_path),
            "library_identity": audit.get("library_identity"),
            "rscad_version_evidence": audit.get("rscad_version_evidence", "legacy_configured_not_installation_verified"),
            "api_version_evidence": audit.get("api_version_evidence", "not_observed"),
            "catalog_format": "immutable_snapshot" if audit.get("parameter_catalog_snapshot_id") else "legacy_read_only"}


def _publish(root: Path, rows: list[dict[str, Any]], *, project: dict[str, Any] | None = None,
             migration: dict[str, Any] | None = None, definitions: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """Caller owns the writer lock. Readers use only the final pointer."""
    pointer = _pointer(root)
    if definitions is None:
        definitions = [{"definition_path": path, "definition_sha256": digest} for path, digest in sorted(
            {(row["definition_path"], row["definition_sha256"]) for row in rows})]
    # Existing committed evidence must remain consistent before extending it.
    for entry in pointer["snapshots"]:
        _generation(root, entry)
    identity = uuid.uuid4().hex
    staging = _inside(root / (".staging-" + identity), root)
    final = _inside(root / "snapshots" / identity, root)
    staging.mkdir()
    pointer_temp = root / (".pointer-" + identity + ".tmp")
    try:
        database = staging / "parameters.sqlite"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(TABLE_SQL)
            for row in rows:
                connection.execute("INSERT INTO parameters VALUES(" + ",".join("?" for _ in COLUMNS) + ")",
                                   tuple(row[name] for name in COLUMNS))
        _rows(database)
        for definition in definitions:
            _definition(definition)
        settings = get_settings()
        library_root = str(settings.definition_root.resolve())
        audit = {"schema_version": 1, "parameter_catalog_snapshot_id": identity,
                 "status": "passed", "checks": {"definitions_resolved": True, "source_hashes_unchanged": True},
                 "database": {"path": str(final / "parameters.sqlite"), "sha256": sha256_file(database)},
                 "parameters": len(rows), "scope": SCOPE, "created_at": now_iso(),
                 "library_identity": {"id": hashlib.sha256(library_root.encode("utf-8")).hexdigest(), "definition_root": library_root},
                 "rscad_version_evidence": "configured_version_not_installation_verified",
                 "rscad_versions": sorted({row["rscad_version"] for row in rows}),
                 "api_version_evidence": "not_observed", "source_project": project,
                 "definitions": definitions,
                 "migration": migration}
        audit_path = staging / "audit.json"
        _write_json(audit_path, audit)
        entry = {"snapshot_id": identity, "audit_sha256": sha256_file(audit_path)}
        final.parent.mkdir(parents=True, exist_ok=True)
        # Recheck live source evidence immediately before publication.
        for definition in definitions:
            _definition(definition)
        if project and sha256_file(Path(project["path"])) != project["sha256"]:
            raise ToolSafetyError("Project changed during parameter indexing")
        staging.rename(final)
        _generation(root, entry)
        next_pointer = {"schema_version": 1, "snapshots": [*pointer["snapshots"], entry], "current_snapshot_id": identity}
        _write_json(pointer_temp, next_pointer)
        pointer_temp.replace(_inside(root / "current.json", root))
        return audit
    finally:
        if staging.exists():
            shutil.rmtree(_inside(staging, root))
        pointer_temp.unlink(missing_ok=True)


def index_project(project_path: str) -> dict[str, Any]:
    settings = get_settings()
    project, _ = resolve_rtfx_path(project_path)
    root = _root()
    with _writer(root):
        legacy_dir = settings.data_dir / "knowledge"
        if not _pointer(root)["snapshots"] and any((legacy_dir / name).exists() for name in ("parameters.sqlite", "parameter_audit.json")):
            raise ToolSafetyError("Legacy parameter evidence exists; run knowledge migrate-parameters explicitly before indexing")
        digest = sha256_file(project)
        _, dfx, _ = read_rtfx_dfx(project)
        definitions = DefinitionIndex(settings.definition_root)
        rows = []
        definition_evidence = []
        for kind in sorted({c["component_type"] for c in parse_dfx_components(dfx)}):
            definition, error = definitions.resolve(kind)
            if error or definition is None or not within(definition, settings.definition_root):
                raise ToolSafetyError(f"Cannot resolve installed definition for {kind}")
            definition = definition.resolve()
            definition_hash = sha256_file(definition)
            definition_evidence.append({"definition_path": str(definition), "definition_sha256": definition_hash})
            schema = parse_parameter_schema(definition.read_text(encoding="utf-8", errors="replace"))
            for name, entry in schema.items():
                values = (kind, name, settings.expected_rscad_version, entry["data_type"], entry["unit"], entry["default"],
                          entry["minimum"], entry["maximum"], json.dumps(entry["enum_values"]), entry["description"],
                          str(definition), definition_hash, "parsed_from_local_definition_not_simulation_verified", entry["raw"])
                rows.append(dict(zip(COLUMNS, values)))
            if sha256_file(definition) != definition_hash:
                raise ToolSafetyError("Definition changed during indexing")
        return _publish(root, rows, project={"path": str(project), "sha256": digest}, definitions=definition_evidence)


def migrate_legacy() -> dict[str, Any]:
    """Explicitly copy validated legacy evidence; never rewrite old files or approvals."""
    root = _root()
    with _writer(root):
        audit, rows, audit_path = _legacy()
        database = Path(audit["database"]["path"])
        migration = {"source_database_sha256": audit["database"]["sha256"], "source_audit_sha256": sha256_file(audit_path),
                     "source_schema": "legacy", "past_workflow_hashes_modified": False}
        for row in rows:
            _definition(row)
        # Repeated migration is idempotent for exactly the same legacy bytes.
        for entry in _pointer(root)["snapshots"]:
            published, _, _ = _generation(root, entry)
            if published.get("migration") == migration:
                return published
        if sha256_file(database) != migration["source_database_sha256"] or sha256_file(audit_path) != migration["source_audit_sha256"]:
            raise ToolSafetyError("Legacy evidence changed during migration")
        return _publish(root, rows, migration=migration)


def catalog_status() -> dict[str, Any]:
    """Read local catalog publication state without creating a directory or connecting."""
    try:
        root = _root()
        pointer = _pointer(root)
        if pointer["snapshots"]:
            for entry in pointer["snapshots"]:
                _generation(root, entry)
            return {"status": "ready", "format": "immutable_snapshots", "snapshot_count": len(pointer["snapshots"]),
                    "current_snapshot_id": pointer["current_snapshot_id"], "selection": "unique_definition_or_explicit_snapshot", "scope": SCOPE}
        legacy_dir = get_settings().data_dir / "knowledge"
        if any((legacy_dir / name).exists() for name in ("parameters.sqlite", "parameter_audit.json")):
            _legacy()
            return {"status": "ready", "format": "legacy_read_only", "snapshot_count": 0,
                    "migration_required_before_indexing": True, "scope": SCOPE}
        return {"status": "missing", "snapshot_count": 0, "scope": SCOPE}
    except (ToolSafetyError, OSError) as exc:
        return {"status": "invalid", "reason": str(exc), "scope": SCOPE}
