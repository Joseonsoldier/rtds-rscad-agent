"""Read-only RTIFX companion-file discovery.

Component parameters are interpreted with the installed component definitions.
The module never writes an RTIFX file and never connects to RSCAD.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

AGENT_ROOT = Path(__file__).resolve().parent.parent

from rtds_agent.core.topology_parser import (
    DefinitionIndex,
    parse_dfx_components,
    parse_parameter_schema,
    read_rtfx_dfx,
    sha256_file,
)


KNOWN_COMPANION_EXTENSIONS = frozenset({
    ".tli", ".tlo", ".tlx", ".tlb",
    ".cli", ".clo", ".clx", ".clb",
    ".dat", ".dyr", ".raw", ".csv", ".txt",
    ".mat", ".xml", ".json", ".ind",
})
EXCLUDED_BASENAME_EXTENSIONS = frozenset({
    ".rtfx", ".dfx", ".backup", ".log", ".out",
    ".r1", ".r2", ".inf", ".sib", ".map", ".tmp",
})
PLACEHOLDER_VALUES = frozenset({
    "", "0", "none", "null", "n/a", "na", "unused",
})
FILE_TEXT_RE = re.compile(
    r"(?i)(\bfile\b|file\s*name|filename|data\s+name|"
    r"\.(?:tli|tlo|tlx|tlb|cli|clo|clx|clb)\b)"
)


class CompanionDiscoveryError(RuntimeError):
    """Raised when companion discovery cannot prove a complete safe bundle."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _clean_value(value: Any) -> str:
    cleaned = str(value).strip().strip('"').strip("'").strip()
    while cleaned.endswith("#"):
        cleaned = cleaned[:-1]
    return cleaned.strip()


def _safe_relative(value: str) -> Path | None:
    candidate = Path(value.replace("\\", "/"))
    if candidate.is_absolute() or ".." in candidate.parts:
        return None
    return candidate


def _file_index(search_root: Path, rtfx_path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in search_root.rglob("*"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if resolved == rtfx_path.resolve() or not _is_within(resolved, search_root):
            continue
        relative = resolved.relative_to(search_root.resolve())
        result.append({
            "path": resolved,
            "relative": relative,
            "relative_key": relative.as_posix().casefold(),
            "stem_key": relative.with_suffix("").as_posix().casefold(),
            "suffix": relative.suffix.casefold(),
        })
    return result


def _schema_is_file_semantic(
    parameter: str,
    schema_entry: Mapping[str, Any] | None,
    component_type: str,
) -> bool:
    if schema_entry is None:
        return False
    data_type = str(schema_entry.get("data_type", "")).upper()
    if data_type == "FILE":
        return True
    if data_type not in {"NAME", "CHAR", "TEXT", "CHARACTER"}:
        return False
    text = " ".join(
        str(schema_entry.get(key, ""))
        for key in ("description", "unit", "default", "raw")
    )
    if FILE_TEXT_RE.search(text):
        return True
    return (
        parameter.casefold() in {"dnm1", "tlb", "tline", "indfile"}
        and any(
            token in component_type.casefold()
            for token in ("tline", "cable", "line", "machine")
        )
    )


def _reference_key(reference: Mapping[str, Any]) -> str:
    return (
        f"{reference['component_uuid']}:"
        f"{reference['component_type']}:"
        f"{reference['parameter']}"
    )


def discover_companion_dependencies(
    rtfx_path: str | Path,
    definition_root: str | Path,
    *,
    search_root: str | Path | None = None,
) -> dict[str, Any]:
    """Discover component-parameter file dependencies below search_root."""

    rtfx = Path(rtfx_path).resolve()
    definitions_root = Path(definition_root).resolve()
    root = Path(search_root or rtfx.parent).resolve()
    if not rtfx.is_file():
        raise CompanionDiscoveryError(f"RTIFX does not exist: {rtfx}")
    if not definitions_root.is_dir():
        raise CompanionDiscoveryError(
            f"component definition root does not exist: {definitions_root}"
        )
    if not _is_within(rtfx, root):
        raise CompanionDiscoveryError("RTIFX is outside the discovery root")

    member, dfx_text, dfx_sha256 = read_rtfx_dfx(rtfx)
    components = parse_dfx_components(dfx_text)
    definition_index = DefinitionIndex(definitions_root)
    files = _file_index(root, rtfx)
    by_relative = {
        item["relative_key"]: item for item in files
    }
    by_stem: dict[str, list[dict[str, Any]]] = {}
    for item in files:
        by_stem.setdefault(item["stem_key"], []).append(item)

    references: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    definition_errors: list[dict[str, Any]] = []
    discovered_paths: dict[str, dict[str, Any]] = {}

    for component in components:
        component_type = str(component["component_type"])
        definition_path, resolution_error = definition_index.resolve(
            component_type
        )
        schema: dict[str, dict[str, Any]] = {}
        if resolution_error:
            definition_errors.append({
                "component_uuid": component["uuid"],
                "component_type": component_type,
                "error": resolution_error,
            })
        else:
            assert definition_path is not None
            schema = parse_parameter_schema(
                definition_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            )

        for parameter, raw_value in component["parameters"].items():
            value = _clean_value(raw_value)
            if value.casefold() in PLACEHOLDER_VALUES:
                continue
            entry = schema.get(parameter)
            suffix = Path(value.replace("\\", "/")).suffix.casefold()
            explicit_known = suffix in KNOWN_COMPANION_EXTENSIONS
            file_semantic = _schema_is_file_semantic(
                parameter,
                entry,
                component_type,
            )
            if not explicit_known and not file_semantic:
                continue

            safe = _safe_relative(value)
            base_record = {
                "component_uuid": component["uuid"],
                "component_type": component_type,
                "parameter": parameter,
                "raw_value": str(raw_value),
                "normalized_value": value,
                "definition": str(definition_path) if definition_path else None,
                "schema_data_type": (
                    entry.get("data_type") if entry else None
                ),
            }
            dynamic_tokens = ("*", "?", "$" + "{", "%{")
            if safe is None or any(token in value for token in dynamic_tokens):
                blocked.append({
                    **base_record,
                    "reason": "unsafe_or_dynamic_path",
                })
                continue

            matches: list[dict[str, Any]]
            strategy: str
            if suffix:
                match = by_relative.get(safe.as_posix().casefold())
                matches = [match] if match is not None else []
                strategy = "explicit_filename"
            else:
                stem_key = safe.as_posix().casefold()
                matches = [
                    item for item in by_stem.get(stem_key, [])
                    if (
                        item["suffix"] in KNOWN_COMPANION_EXTENSIONS
                        or (
                            entry is not None
                            and str(entry.get("data_type", "")).upper()
                            == "FILE"
                            and item["suffix"]
                            not in EXCLUDED_BASENAME_EXTENSIONS
                        )
                    )
                ]
                strategy = "definition_semantic_stem_family"

            if not matches:
                missing.append({
                    **base_record,
                    "strategy": strategy,
                    "reason": "referenced_companion_not_found",
                })
                continue

            matched_relative_paths = sorted(
                item["relative"].as_posix() for item in matches
            )
            reference = {
                **base_record,
                "strategy": strategy,
                "matched_relative_paths": matched_relative_paths,
            }
            references.append(reference)
            reference_id = _reference_key(reference)
            for item in matches:
                key = item["relative_key"]
                record = discovered_paths.setdefault(key, {
                    "path": str(item["path"]),
                    "relative_path": item["relative"].as_posix(),
                    "sha256": sha256_file(item["path"]),
                    "bytes": item["path"].stat().st_size,
                    "referenced_by": [],
                })
                if reference_id not in record["referenced_by"]:
                    record["referenced_by"].append(reference_id)

    for record in discovered_paths.values():
        record["referenced_by"].sort()
    discovered_files = sorted(
        discovered_paths.values(),
        key=lambda item: item["relative_path"].casefold(),
    )
    references.sort(
        key=lambda item: (
            int(item["component_uuid"]),
            item["component_type"],
            item["parameter"],
        )
    )
    missing.sort(
        key=lambda item: (
            int(item["component_uuid"]),
            item["component_type"],
            item["parameter"],
        )
    )
    blocked.sort(
        key=lambda item: (
            int(item["component_uuid"]),
            item["component_type"],
            item["parameter"],
        )
    )
    definition_errors.sort(
        key=lambda item: (
            int(item["component_uuid"]),
            item["component_type"],
        )
    )
    fingerprint_payload = {
        "contract_version": "1.0",
        "dfx_sha256": dfx_sha256,
        "references": [
            {
                key: item[key]
                for key in (
                    "component_uuid",
                    "component_type",
                    "parameter",
                    "normalized_value",
                    "strategy",
                    "matched_relative_paths",
                )
            }
            for item in references
        ],
        "files": [
            {
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
            }
            for item in discovered_files
        ],
    }
    passed = not missing and not blocked and not definition_errors
    return {
        "schema_version": "1.0",
        "contract_version": "1.0",
        "status": "passed" if passed else "incomplete",
        "passed": passed,
        "mode": "read_only_rtfx_component_parameter_discovery",
        "source": {
            "rtfx_path": str(rtfx),
            "rtfx_sha256": sha256_file(rtfx),
            "dfx_member": member,
            "dfx_sha256": dfx_sha256,
            "search_root": str(root),
            "definition_root": str(definitions_root),
        },
        "summary": {
            "component_count": len(components),
            "reference_count": len(references),
            "file_count": len(discovered_files),
            "missing_count": len(missing),
            "blocked_count": len(blocked),
            "definition_error_count": len(definition_errors),
        },
        "references": references,
        "files": discovered_files,
        "missing": missing,
        "blocked": blocked,
        "definition_errors": definition_errors,
        "fingerprint_payload": fingerprint_payload,
        "discovery_sha256": canonical_sha256(fingerprint_payload),
        "safety": {
            "rtfx_written": False,
            "rscad_connection_opened": False,
            "compile_called": False,
            "runtime_called": False,
            "hardware_io_called": False,
        },
    }


def require_complete(discovery: Mapping[str, Any]) -> None:
    if discovery.get("passed") is not True:
        summary = discovery.get("summary", {})
        raise CompanionDiscoveryError(
            "companion discovery is incomplete: "
            f"missing={summary.get('missing_count')}, "
            f"blocked={summary.get('blocked_count')}, "
            f"definition_errors={summary.get('definition_error_count')}"
        )


def input_files_from_discovery(
    discovery: Mapping[str, Any],
) -> list[dict[str, str]]:
    require_complete(discovery)
    return [
        {
            "path": str(Path(str(item["path"])).resolve()),
            "sha256": str(item["sha256"]).lower(),
        }
        for item in discovery.get("files", [])
    ]


def verify_declared_inputs(
    discovery: Mapping[str, Any],
    declared_inputs: Sequence[Mapping[str, Any]] | None,
) -> None:
    expected = input_files_from_discovery(discovery)
    actual = sorted(
        (
            {
                "path": str(Path(str(item["path"])).resolve()),
                "sha256": str(item["sha256"]).lower(),
            }
            for item in (declared_inputs or [])
        ),
        key=lambda item: item["path"].casefold(),
    )
    expected.sort(key=lambda item: item["path"].casefold())
    if actual != expected:
        raise CompanionDiscoveryError(
            "declared input_files do not exactly match auto-discovered "
            "RTIFX dependencies"
        )


__all__ = [
    "CompanionDiscoveryError",
    "KNOWN_COMPANION_EXTENSIONS",
    "canonical_sha256",
    "discover_companion_dependencies",
    "input_files_from_discovery",
    "require_complete",
    "verify_declared_inputs",
]
