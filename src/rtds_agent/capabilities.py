"""Read-only capability evidence. No vendor package import or live discovery."""
from __future__ import annotations

import ast
import importlib.metadata
import json
from pathlib import Path
import re
import shutil
import sys
from typing import Any

from . import __version__
from .settings import ConfigurationError, config_path, get_settings, within
from .policy import read_policy
from .integrity import verify_release
from .core.parameter_catalog import catalog_status
from .core.runtime_api_surface import inspect_runtime_api_surface, RuntimeApiSurfaceError
from .core.state_machine import sha256_file, sha256_json


_API_FILES = ("__init__.py", "rscadfx.py", "case.py", "case_settings.py", "component.py", "rtx.py", "comms/connection_setup.py")


def _file(path: Path, root: Path, *, maximum: int = 5 * 1024 * 1024) -> dict[str, Any]:
    if not within(path, root):
        return {"status": "outside_configured_root"}
    if not path.is_file():
        return {"status": "missing"}
    if path.stat().st_size > maximum:
        return {"status": "exceeds_inspection_limit"}
    return {"status": "present", "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _api_version(path: Path, evidence: dict[str, Any]) -> str:
    if evidence.get("status") != "present":
        return "unknown"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, ValueError, UnicodeError, OSError):
        return "unknown"
    if sha256_file(path) != evidence["sha256"]:
        return "unknown"
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == "__version__" for target in targets):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    value = node.value.value
                    return value if re.fullmatch(r"\d+(?:\.\d+){1,3}", value) else "unknown"
    return "unknown"


def _feature(*, implemented: bool, available: bool | None, inspected: bool = False,
             reasons: list[str] | None = None, action: str | None = None) -> dict[str, Any]:
    return {"implemented": implemented, "dependency_available": available,
            "statically_inspected": inspected, "integration_qualified": False,
            "qualification_state": "not_evaluated", "policy_action": action,
            "reasons": reasons or [], "live_execution_eligibility": "requires_workflow_validation" if action else "not_applicable"}


def _invalid_configuration() -> dict[str, Any]:
    """Expose only a validated numeric version, never arbitrary invalid config fields."""
    configured = "unknown"
    try:
        path = config_path()
        if path.is_file() and path.stat().st_size <= 1024 * 1024:
            value = json.loads(path.read_text(encoding="utf-8"))
            version = value.get("expected_rscad_version") if isinstance(value, dict) else None
            if isinstance(version, str) and re.fullmatch(r"\d+(?:\.\d+){1,3}", version):
                configured = version
    except (ValueError, OSError):
        pass
    return {"status": "invalid", "reason": "Configuration is invalid or outside the supported FX 2.7.3 scope",
            "configured_rscad_version": configured}


def get_capabilities() -> dict[str, Any]:
    """Report software, dependency, policy and qualification states using local reads only.

    A passed Runtime API source inspection is not an observed RSCAD version or
    authorization to use a rack. Every actual workflow retains its live gates.
    """
    packages = {}
    for name in ("mcp", "pypdf", "jsonschema", "rtds-rscad-agent"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "unknown"
    host_supported = sys.platform == "win32" and sys.version_info[:2] == (3, 12)
    renderer = shutil.which("pdftoppm")
    try:
        release = verify_release()
    except (ValueError, OSError, PermissionError) as exc:
        release = {"status": "failed", "reason": str(exc)}
    try:
        settings = get_settings()
        configuration = {"status": "valid", "configured_rscad_version": settings.expected_rscad_version,
                         "rscad_home_configured": settings.rscad_home is not None}
    except (ConfigurationError, ValueError, OSError):
        settings = None
        configuration = _invalid_configuration()
    policy = {"status": "unavailable", "actions": [], "configured_allowed_racks": [], "live_racks_observed": False}
    catalog = {"status": "unavailable"}
    definitions_available = False
    files: dict[str, Any] = {}
    api_files: dict[str, Any] = {}
    inspection: dict[str, Any] = {"status": "not_inspected", "reason": "RSCAD_HOME is not configured"}
    observed_api = "unknown"
    if settings is not None:
        catalog = catalog_status()
        definitions_available = settings.definition_root.is_dir()
        try:
            configured_policy = read_policy(settings)
            policy = {"status": configured_policy["status"], "actions": list(configured_policy["actions"]),
                      "configured_allowed_racks": list(configured_policy["allowed_racks"]), "live_racks_observed": False,
                      "authorization_scope": "configuration only; fresh per-workflow checks and single-use grants remain required"}
        except (KeyError, TypeError, ValueError, OSError, PermissionError):
            policy["status"] = "invalid"
            policy["reason"] = "Policy cannot be validated against the current settings"
        if settings.rscad_home is not None:
            files = {"rscad_executable": _file(settings.rscad_home / "BIN/RSCAD_FX.exe", settings.rscad_home, maximum=256 * 1024 * 1024),
                     "fsat_executable": _file(settings.rscad_home / "BIN/fs.exe", settings.rscad_home, maximum=256 * 1024 * 1024)}
            api_root = settings.sdk_root / "rtds"
            api_files = {name: _file(api_root / name, settings.sdk_root) for name in _API_FILES}
            observed_api = _api_version(api_root / "__init__.py", api_files["__init__.py"])
            missing = [name for name, evidence in api_files.items() if evidence["status"] != "present"]
            if missing:
                inspection = {"status": "unavailable", "reason": "API source files are missing or outside inspection bounds", "unavailable_files": missing}
            else:
                try:
                    audit = inspect_runtime_api_surface(site_packages=settings.sdk_root)
                    after = {name: _file(api_root / name, settings.sdk_root) for name in _API_FILES}
                    if after != api_files:
                        inspection = {"status": "failed", "reason": "API files changed during static inspection"}
                        observed_api = "unknown"
                    else:
                        inspection = {"status": audit["status"], "checks": audit["checks"],
                                      "api_fingerprint_sha256": sha256_json(api_files),
                                      "inspection_evidence_sha256": audit["integrity"]["payload_sha256"],
                                      "adapter_sha256": audit["adapter"]["sha256"],
                                      "scope": "Runtime API source signatures and adapter text; no vendor code executed"}
                except (RuntimeApiSurfaceError, ValueError, OSError) as exc:
                    inspection = {"status": "failed", "reason": str(exc)}
    api_available = bool(api_files) and all(row["status"] == "present" for row in api_files.values())
    executable = files.get("rscad_executable", {}).get("status") == "present"
    fsat = files.get("fsat_executable", {}).get("status") == "present"
    runtime_inspected = inspection["status"] == "passed"
    definition_profile = {"status":"unavailable","sha256":None,"file_count":0}
    if settings is not None and definitions_available:
        try:
            from .core.component_catalog import inventory
            _,definition_rows,definition_digest = inventory()
            definition_profile = {"status":"statically_hashed","sha256":definition_digest,"file_count":len(definition_rows)}
        except (ValueError,OSError) as exc:
            definition_profile = {"status":"unresolved","sha256":None,"reason":str(exc)}
    common_reasons = []
    if not host_supported:
        common_reasons.append("Live adapters support Windows with Python 3.12 only")
    if not executable:
        common_reasons.append("RSCAD_FX.exe is unavailable within the configured installation")
    if not api_available:
        common_reasons.append("Required installed Python API source files are unavailable")
    if not runtime_inspected:
        common_reasons.append("Runtime API static inspection has not passed")
    if release["status"] != "passed":
        common_reasons.append("Release integrity must pass before live execution")
    common_reasons.append("RSCAD executable version and target-specific integration qualification are not observed")
    live_dependencies = host_supported and executable and api_available
    features = {
        "native_draft_editing": _feature(implemented=True, available=live_dependencies,
            reasons=["Explicit native backend supports existing flat Draft parameter/location edits with a reviewed project policy preview",
                     "Uses isolated input, a fixed SDK worker, readback, exact save/close/reopen comparison and a durable recovery journal",
                     "Auto remains static preview only; native new-case construction, insert/clone/wire operations and Compile integration are not qualified"]),
        "group_inspection": _feature(implemented=True, available=settings is not None,
            reasons=["GROUP containers, nested membership and anchor bounds are separate from UUID-bearing components",
                     "Context/ordinal group IDs are snapshot identities, not SDK IDs; grouped mutation remains unsupported"]),
        "static_structural_editing": _feature(implemented=True, available=settings is not None and definitions_available,
            reasons=["Bounded offline record/template adapter only; project policy, source/snapshot/preview hashes and model checks required", "Native structural editing, opaque-reference removal, and general DFX generation remain unqualified"]),
        "component_definition_catalog": _feature(implemented=True, available=definitions_available,
            reasons=["Installed definition identity/hash and parsed ports/parameters; unsupported grammar remains explicit"]),
        "model_check": _feature(implemented=True, available=settings is not None,
            reasons=["Static and explicitly mapped unit-bound rules only; hardware allocation and engineering acceptance not evaluated"]),
        "saved_native_result_acquisition": _feature(implemented=True, available=settings is not None,
            reasons=["Existing backend long-form CSV to canonical JSON; does not initiate native capture"]),
        "experiment_suites": _feature(implemented=True, available=settings is not None,
            reasons=["Canonical JSON DSL, <=64 sequential runs, cartesian/paired sweep and supplied-sample assessment", "Execution uses existing policy/Compile/Runtime gates and exact grants; no automatic repair or retry"]),
        "project_parsing": _feature(implemented=True, available=settings is not None,
                                    reasons=[] if definitions_available else ["Unresolved installed definitions will be reported as partial parser coverage"]),
        "numeric_parameter_editing": _feature(implemented=True, available=settings is not None and definitions_available and catalog["status"] == "ready",
                                              reasons=["Requires source hash, exact component/context, audited finite REAL/INTEGER parameters and fresh definition hashes"]),
        "manual_figure_rendering": _feature(implemented=True, available=renderer is not None and packages["pypdf"] != "unknown",
                                            reasons=[] if renderer else ["pdftoppm (Poppler) is unavailable on PATH"]),
        "compile": _feature(implemented=True, available=live_dependencies, reasons=[*common_reasons, "Runtime source inspection does not qualify the Compile API"], action="compile"),
        "runtime_capture": _feature(implemented=True, available=live_dependencies, inspected=runtime_inspected, reasons=common_reasons, action="runtime_start_stop"),
        "runtime_controls": _feature(implemented=True, available=live_dependencies, inspected=runtime_inspected,
                                     reasons=[*common_reasons, "Exact target, expected initial value, readback, restoration and cleanup remain mandatory"], action="runtime_controls"),
        "offline_fsat": _feature(implemented=True, available=host_supported and fsat,
                                 reasons=["Requires validated DQ0 plan, compile artifacts, source hashes and fs.exe; executable presence does not qualify FSAT behavior"], action="offline_test"),
        "structural_editing": _feature(implemented=False, available=None,
                                      reasons=["unsupported live application: no qualified structural editing adapter", "Offline TOGGLE node-impact preview and unchanged isolated trial preparation are implemented", "inspect_extension_support reads exact installed declarations; save/reopen and isolated connection tests remain required"]),
        "gui_runtime_target_discovery": _feature(implemented=False, available=None,
                                                reasons=["unsupported live discovery: exact GUI session/model and Runtime APIs are not qualified", "inspect_runtime_layout inventories saved headers only, without current values or inferred units", "Requires verified window/project identity, saved-state handling, timestamps, identifiers/units and policy-bound connection tests"]),
    }
    evidence_id = sha256_json({"packages": packages, "source_version": __version__, "release": release,
                              "api_files": api_files, "files": files, "configuration": configuration,
                              "policy": policy, "catalog": catalog, "host": sys.platform})
    return {"schema_version": "1.0", "status": "completed", "capability_evidence_id": evidence_id,
            "host": {"platform": sys.platform, "python_observed": sys.version.split()[0], "live_adapter_host_supported": host_supported},
            "versions": {"agent_observed": __version__, "rscad_configured": configuration["configured_rscad_version"],
                         "rscad_observed": "unknown", "rscad_observation_reason": "No executable version metadata reader or live version call was used",
                         "python_api_supported": "1.1", "python_api_observed": observed_api},
            "configuration": configuration, "package_versions": packages, "release_integrity": release,
            "installation_files": files, "api_source_files": api_files, "runtime_api_inspection": inspection,
            "parameter_catalog": catalog, "poppler_available": renderer is not None, "policy": policy, "features": features,
            "version_profile": {"configured_fx": configuration["configured_rscad_version"], "observed_fx": "unknown",
                "sdk_version": observed_api, "sdk_source_sha256": sha256_json(api_files) if api_files else None,
                "definition_set_sha256": definition_profile["sha256"], "definition_profile": definition_profile,
                "qualified_live_structural_operations": [], "native_log_grammar": "unqualified",
                "tool_profiles": ["core", "engineering", "full"], "default_tool_profile": "full"},
            "qualification": {"integration_qualified": False, "state": "not_evaluated", "reason": "No current-installation RSCAD/rack qualification evidence was evaluated",
                              "required_conditions": ["Explicit authorization for the particular test", "Confirmed installation and permitted source/document roots",
                                                      "Specified rack/actions, signal/control meanings and external I/O effects", "Verified restore, stop and cleanup plan"]},
            "mutations_performed": False, "sdk_imported": False, "live_rscad_connection_opened": False,
            "rack_query_called": False, "subprocess_called": False, "automatic_uploads": False}
