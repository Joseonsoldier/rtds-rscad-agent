"""Read-only operator suite validation and isolated native evaluation fixtures.

Strict suite schema (all SHA-256 values are lowercase hexadecimal)::

  {"schema_version":"1.0", "cohort_id":"operator-cohort",
   "coordination_config":{"path":"ABS_CONFIG", "sha256":"HASH"},
   "rscad_home":"ABS_VENDOR_HOME", "sdk_evidence_id":"HASH",
   "sdk_files":{"__init__.py":"HASH", "case.py":"HASH"},
   "executable_sha256":"HASH", "implementation_sha256":"HASH",
   "cases":{"EVAL-N03":{
     "source":"divider.rtfx",
     "files":{"divider.rtfx":{"path":"ABS_SOURCE", "sha256":"HASH"}},
     "definitions":{"definition_name":"HASH"}, "strategy":"insert",
     "required_component_types":["definition_name"]}}}

``sdk_files`` is the exact statically observed inventory relative to sdk_root /
``rtds``. Definitions are relative to MLIB/COMPONENTS. Companion names in files
are canonical paths relative to the future fixture sources directory. A source
must be top-level. The suite declares authority inputs; it cannot enable policy.

No vendor module is imported and no native operation is called. Static SDK
inspection reads/hash-checks Python declarations. create_fixture uses only the
bridge's allow_native=False inspector to derive scorer-side plan oracles.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import uuid

from eval_native_host import digest, durable_json, host_binding, read_json, safe_path
from rtds_agent.settings import Settings

TASKS = {"EVAL-N03": {"insert"}, "EVAL-N04": {"insert", "clipboard"}, "EVAL-N10": {"clipboard"}}
SUITE_FIELDS = {"schema_version", "cohort_id", "coordination_config", "rscad_home",
                "sdk_evidence_id", "sdk_files", "executable_sha256", "implementation_sha256", "cases"}
CASE_FIELDS = {"source", "files", "definitions", "strategy", "required_component_types"}
SETTINGS_FIELDS = {"schema_version", "data_dir", "rscad_home", "source_roots",
                   "document_roots", "vector_store_id", "expected_rscad_version"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _keys(value, expected):
    if type(value) is not dict or set(value) != set(expected):
        raise ValueError("Unexpected native suite fields")


def _sha(value):
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a lowercase SHA-256")
    return value


def _relative(value):
    if (type(value) is not str or not 1 <= len(value) <= 1024 or "\\" in value or ":" in value
            or PurePosixPath(value).is_absolute() or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise ValueError("Expected a canonical relative fixture name")
    # Windows normalizes trailing dots/spaces and reserves these names. Refuse
    # ambiguous destination names before any files are created.
    if any(part != part.rstrip(" .") or re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
           or any(c in '<>"|?*' or ord(c) < 32 for c in part) for part in value.split("/")):
        raise ValueError("Ambiguous Windows fixture name refused")
    return value


def _inventory(value):
    if type(value) is not dict or not 1 <= len(value) <= 1000:
        raise ValueError("Invalid bounded file inventory")
    names = [_relative(name) for name in value]
    if len({name.casefold() for name in names}) != len(names):
        raise ValueError("Case-insensitive file collision")
    for name in names:
        if any(other.casefold().startswith(name.casefold() + "/") for other in names):
            raise ValueError("File/directory fixture collision")


def _settings(value):
    _keys(value, SETTINGS_FIELDS)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["vector_store_id"] != "":
        raise ValueError("Native evaluation needs exact local settings without a remote store")
    if not isinstance(value["source_roots"], list) or not isinstance(value["document_roots"], list):
        raise ValueError("Settings roots must be explicit arrays")
    return Settings(safe_path(value["data_dir"]), safe_path(value["rscad_home"]),
                    tuple(safe_path(p) for p in value["source_roots"]),
                    tuple(safe_path(p) for p in value["document_roots"]), "",
                    value["expected_rscad_version"]).validated()


def _sdk_evidence(settings):
    from rtds_agent.core.native_edit import inspect_native_sdk
    return inspect_native_sdk(settings)


def _implementation_digest():
    from eval_native_cases import implementation_digest
    return implementation_digest()


def _bridge_factory(*args, **kwargs):
    from eval_native_cases import NativeCaseBridge
    return NativeCaseBridge(*args, **kwargs)


def _pin(pins, path, expected):
    path = safe_path(path)
    _sha(expected)
    if not path.is_file() or path.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Native suite file missing or exceeds bound")
    if digest(path) != expected:
        raise ValueError("Native suite file hash changed: " + str(path))
    key = str(path)
    if key in pins and pins[key] != expected:
        raise ValueError("Conflicting native suite file pins")
    pins[key] = expected


def load_suite(path, sha):
    """Validate explicit operator inputs without writes, SDK import or native calls."""
    path = safe_path(path)
    pins = {}
    _pin(pins, path, sha)
    doc = read_json(path)
    _keys(doc, SUITE_FIELDS)
    if doc["schema_version"] != "1.0" or type(doc["cohort_id"]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", doc["cohort_id"]):
        raise ValueError("Invalid suite version or cohort identity")
    _keys(doc["coordination_config"], {"path", "sha256"})
    ref = doc["coordination_config"]
    _pin(pins, ref["path"], ref["sha256"])
    coordination = _settings(read_json(ref["path"]))
    home = safe_path(doc["rscad_home"])
    if home != coordination.rscad_home:
        raise ValueError("Suite vendor home differs from operator settings")
    for field in ("sdk_evidence_id", "executable_sha256", "implementation_sha256"):
        _sha(doc[field])
    _inventory(doc["sdk_files"])
    for relative, expected in doc["sdk_files"].items():
        _pin(pins, coordination.sdk_root / "rtds" / relative, expected)
    _pin(pins, home / "BIN/RSCAD_FX.exe", doc["executable_sha256"])
    evidence = _sdk_evidence(coordination)
    if (evidence.get("available") is not True or evidence.get("evidence_id") != doc["sdk_evidence_id"]
            or evidence.get("sources") != doc["sdk_files"]
            or evidence.get("executable_sha256") != doc["executable_sha256"]):
        raise ValueError("Suite SDK evidence/inventory differs from current static observation")
    if _implementation_digest() != doc["implementation_sha256"]:
        raise ValueError("Suite implementation binding changed")
    cases = doc["cases"]
    if type(cases) is not dict or not 1 <= len(cases) <= 3 or set(cases) - set(TASKS):
        raise ValueError("Invalid native suite case selection")
    for task_id, case in cases.items():
        _keys(case, CASE_FIELDS)
        source = _relative(case["source"])
        if "/" in source or Path(source).suffix.lower() != ".rtfx" or case["strategy"] not in TASKS[task_id]:
            raise ValueError("Invalid top-level native source or task strategy")
        _inventory(case["files"])
        _inventory(case["definitions"])
        if source not in case["files"]:
            raise ValueError("Source is not in exact suite files")
        kinds = case["required_component_types"]
        if (type(kinds) is not list or not 1 <= len(kinds) <= 500
                or any(type(k) is not str or not 1 <= len(k) <= 256 for k in kinds)
                or len(set(kinds)) != len(kinds)):
            raise ValueError("Invalid required component kinds")
        for file_ref in case["files"].values():
            _keys(file_ref, {"path", "sha256"})
            _pin(pins, file_ref["path"], file_ref["sha256"])
        for relative, expected in case["definitions"].items():
            _pin(pins, coordination.definition_root / relative, expected)
    for file_path, expected in pins.items():
        _pin({}, file_path, expected)
    return {"path": str(path), "sha256": sha, "document": doc,
            "original_hashes": pins, "builder_sha256": digest(Path(__file__))}


def _verify_suite(suite):
    _keys(suite, {"path", "sha256", "document", "original_hashes", "builder_sha256"})
    current = load_suite(suite["path"], suite["sha256"])
    if current != suite:
        raise ValueError("Loaded native suite changed since caller validation")
    return current


def fixture_profile(task_id, suite):
    """Path/cohort-independent profile; unique manifest identities stay separate."""
    doc, case = suite["document"], suite["document"]["cases"][task_id]
    return {"schema_version": "1.0", "lane": "operator_native", "task_id": task_id,
            "source": case["source"], "files": {k: v["sha256"] for k, v in case["files"].items()},
            "definitions": case["definitions"], "strategy": case["strategy"],
            "required_component_types": case["required_component_types"],
            "sdk_evidence_id": doc["sdk_evidence_id"], "sdk_files": doc["sdk_files"],
            "executable_sha256": doc["executable_sha256"], "implementation_sha256": doc["implementation_sha256"],
            "fixture_builder_sha256": suite["builder_sha256"], "expected_rscad_version": "2.7.3"}


def _copy_exact(source, target, expected):
    source, target = safe_path(source), safe_path(target)
    if source.stat().st_size > 256 * 1024 * 1024:
        raise ValueError("Native source copy exceeds bound")
    target.parent.mkdir(parents=True, exist_ok=True)
    copied = hashlib.sha256()
    with source.open("rb") as src, target.open("xb") as dst:
        while block := src.read(1024 * 1024):
            copied.update(block)
            dst.write(block)
        dst.flush()
        os.fsync(dst.fileno())
    if copied.hexdigest() != expected or digest(source) != expected or digest(target) != expected:
        raise ValueError("Source changed during isolated copy")


def create_fixture(attempt, task_id, suite, *, bridge_factory=None):
    """Create a fresh fixture under an owned attempt; retain partial failures.

    The attempt may already contain runner files. Fixed fixture/native-data/
    native-config names must be unused. No operator config/policy is modified.
    ``bridge_factory`` is solely a trusted unit-test injection, never a CLI input.
    """
    _verify_suite(suite)
    if task_id not in suite["document"]["cases"]:
        raise ValueError("Task is not declared in the operator suite")
    attempt = safe_path(attempt)
    doc, case = suite["document"], suite["document"]["cases"][task_id]
    root, data, config = attempt / "fixture", attempt / "native-data", attempt / "native-config.json"
    for path in (root, data, config):
        if safe_path(path).exists():
            raise FileExistsError("Native fixture paths cannot be reused")
    if any(Path(path).is_relative_to(attempt) for path in suite["original_hashes"]):
        raise ValueError("Attempt overlaps a protected suite input")
    coordination_path = doc["coordination_config"]["path"]
    coordination = _settings(read_json(coordination_path))
    settings = Settings(data, coordination.rscad_home, (root / "sources",), (), "", "2.7.3").validated()
    if data.is_relative_to(coordination.data_dir) or coordination.data_dir.is_relative_to(attempt):
        raise ValueError("Attempt and operator data must remain separate")
    if any(safe_path(p).exists() for p in (coordination.data_dir / "native_recovery_required.json",
            coordination.data_dir / "eval-native/cohorts" / doc["cohort_id"] / "dispatch_stopped.json")):
        raise PermissionError("Operator recovery/cohort barrier blocks a new native fixture")
    attempt.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    (root / "sources").mkdir()
    data.mkdir()
    for relative, file_ref in case["files"].items():
        _copy_exact(file_ref["path"], root / "sources" / relative, file_ref["sha256"])
    fixture_id = task_id + "-" + uuid.uuid4().hex
    manifest = {"schema_version": "1.0", "task_id": task_id, "fixture_id": fixture_id,
                "cohort_id": doc["cohort_id"], "source": case["source"],
                "source_sha256": case["files"][case["source"]]["sha256"],
                "files": {k: v["sha256"] for k, v in case["files"].items()},
                "definitions": case["definitions"], "strategy": case["strategy"],
                "required_component_types": case["required_component_types"],
                "sdk_evidence_id": doc["sdk_evidence_id"], "implementation_sha256": doc["implementation_sha256"]}
    manifest_path = root / "manifest.json"
    durable_json(manifest_path, manifest, exclusive=True)
    durable_json(config, settings.as_dict(), exclusive=True)
    bridge = (bridge_factory or _bridge_factory)(manifest_path, settings, coordination, allow_native=False)
    inspection = bridge.inspect()  # Read-only AST/model parsing, no SDK import.
    bridge.verify()
    plan = inspection["plan"]
    if (inspection.get("live_calls_made") is not False
            or inspection.get("source_sha256") != manifest["source_sha256"]
            or inspection.get("fixture_sha256") != digest(manifest_path)):
        raise ValueError("Native fixture inspector returned inconsistent identity or live evidence")
    oracle = {"native_plan_sha256": _hash(plan), "native_component_count": len(plan["components"]),
              "native_group_count": len(plan["groups"]), "native_wire_count": len(plan["wires"])}
    durable_json(root / "oracle.json", oracle, exclusive=True)
    protected = dict(suite["original_hashes"])
    for path in [config, *sorted(root.rglob("*"))]:
        safe_path(path)
        if path.is_file():
            protected[str(path)] = digest(path)
    profile = fixture_profile(task_id, suite)
    meta = {"schema_version": "1.0", "lane": "operator_native", "evaluation_profile": "native_v1", "task_id": task_id,
            "root": str(root), "data_dir": str(data), "fixture_id": fixture_id,
            "cohort_id": doc["cohort_id"], "project_path": str(root / "sources" / case["source"]),
            "source_sha256": manifest["source_sha256"], "native_manifest": str(manifest_path),
            "native_manifest_sha256": digest(manifest_path), "native_config": str(config),
            "coordination_config": coordination_path, "native_host_binding": host_binding(manifest_path, config, coordination_path),
            "native_sdk_evidence_id": doc["sdk_evidence_id"], "native_implementation_sha256": doc["implementation_sha256"],
            "native_strategy": case["strategy"], "native_required_component_types": case["required_component_types"],
            **oracle,
            "fixture_sha256": _hash(profile), "fixture_profile": profile, "original_hashes": protected,
            "native_suite": suite}
    verify_fixture(meta)
    return meta


def verify_fixture(meta):
    """Check every original/copy/config/definition/SDK pin and exact manifest binding."""
    if meta.get("lane") != "operator_native" or meta.get("evaluation_profile") != "native_v1":
        raise ValueError("Native fixture lane binding changed")
    suite = _verify_suite(meta["native_suite"])
    task_id, root = meta["task_id"], safe_path(meta["root"])
    case, doc = suite["document"]["cases"][task_id], suite["document"]
    if (root.name != "fixture" or safe_path(meta["native_manifest"]) != root / "manifest.json"
            or safe_path(meta["native_config"]) != root.parent / "native-config.json"
            or safe_path(meta["data_dir"]) != root.parent / "native-data"
            or safe_path(meta["project_path"]) != root / "sources" / case["source"]
            or meta["cohort_id"] != doc["cohort_id"]):
        raise ValueError("Native fixture metadata layout changed")
    expected_files = {"manifest.json", "oracle.json", *("sources/" + name for name in case["files"])}
    actual = set()
    for path in root.rglob("*"):
        safe_path(path)
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected_files:
        raise ValueError("Native fixture protected file inventory changed")
    expected_pins = {**suite["original_hashes"], meta["native_config"]: meta["original_hashes"].get(meta["native_config"])}
    for name in expected_files:
        path = str(root / name)
        expected_pins[path] = meta["original_hashes"].get(path)
    if expected_pins != meta["original_hashes"]:
        raise ValueError("Native fixture original hash inventory changed")
    for path, sha in meta["original_hashes"].items():
        _pin({}, path, sha)
    manifest = read_json(meta["native_manifest"])
    expected = {"schema_version": "1.0", "task_id": task_id, "fixture_id": meta["fixture_id"],
                "cohort_id": doc["cohort_id"], "source": case["source"],
                "source_sha256": case["files"][case["source"]]["sha256"],
                "files": {k: v["sha256"] for k, v in case["files"].items()},
                "definitions": case["definitions"], "strategy": case["strategy"],
                "required_component_types": case["required_component_types"],
                "sdk_evidence_id": doc["sdk_evidence_id"], "implementation_sha256": doc["implementation_sha256"]}
    if manifest != expected or digest(meta["native_manifest"]) != meta["native_manifest_sha256"]:
        raise ValueError("Native manifest binding changed")
    oracle = read_json(root / "oracle.json")
    if oracle != {key: meta[key] for key in ("native_plan_sha256", "native_component_count", "native_group_count", "native_wire_count")}:
        raise ValueError("Native scorer plan oracle changed")
    coordination = _settings(read_json(meta["coordination_config"]))
    settings = _settings(read_json(meta["native_config"]))
    if safe_path(settings.data_dir / "execution_policy.json").exists():
        raise ValueError("Native evaluation isolated policy must remain absent")
    if (settings.source_roots != (root / "sources",) or settings.document_roots
            or settings.data_dir != safe_path(meta["data_dir"]) or settings.rscad_home != coordination.rscad_home
            or meta["coordination_config"] != doc["coordination_config"]["path"]):
        raise ValueError("Native isolated settings binding changed")
    if host_binding(meta["native_manifest"], meta["native_config"], meta["coordination_config"]) != meta["native_host_binding"]:
        raise ValueError("Native host binding changed")
    profile = fixture_profile(task_id, suite)
    if profile != meta["fixture_profile"] or _hash(profile) != meta["fixture_sha256"]:
        raise ValueError("Native stable fixture profile changed")
    if (meta["source_sha256"] != manifest["source_sha256"] or meta["native_sdk_evidence_id"] != doc["sdk_evidence_id"]
            or meta["native_implementation_sha256"] != doc["implementation_sha256"]
            or meta["native_strategy"] != case["strategy"]
            or meta["native_required_component_types"] != case["required_component_types"]):
        raise ValueError("Native scorer metadata differs from declared fixture")
    return True
