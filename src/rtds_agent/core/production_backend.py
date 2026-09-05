"""Production RSCAD FX compile and offline-FSAT backend.

Implements Compile and offline analytical frequency scans plus an optional,
driver-injected Runtime path. Runtime is disabled by default and separately gated.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, Callable

from rtds_agent.core.companion_dependencies import (
    CompanionDiscoveryError,
    discover_companion_dependencies,
    verify_declared_inputs,
)
from rtds_agent.core.state_machine import sha256_file, sha256_json
from rtds_agent.core.runtime_backend import (
    RuntimeContractError,
    validate_runtime_test_spec,
    validate_samples,
    write_raw_signal_csv,
)


class ProductionBackendError(RuntimeError):
    """Base error for production backend failures."""


class BackendSafetyViolation(ProductionBackendError):
    """Raised before an unsafe or out-of-scope backend action."""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def is_within(path: str | Path, root: str | Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def normalized(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def file_ref(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    stat = target.stat()
    return {
        "path": str(target),
        "sha256": sha256_file(target),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def parse_dtp_nodes(path: str | Path) -> dict[str, int]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    return {
        match.group(2): int(match.group(1))
        for match in re.finditer(r'NODE=\s*(\d+).*?NODENAME=\s*"([^"]+)"', text)
    }


def resolve_bus_nodes(
    parameters: dict[str, Any],
    dtp_nodes: dict[str, int],
) -> dict[str, Any]:
    """Resolve literal or BUSLABEL-number-expanded phase node templates."""

    templates = [str(parameters.get(name, "")) for name in ("NA", "NB", "NC")]
    if any(not name for name in templates):
        raise BackendSafetyViolation(
            "selected FSAT bus has incomplete phase nodes"
        )
    candidates: list[tuple[str, list[str]]] = [("exact", templates)]
    bus_number = str(parameters.get("Num", "")).strip()
    if bus_number and any("#" in name for name in templates):
        candidates.append((
            "buslabel_num_substitution",
            [name.replace("#", bus_number) for name in templates],
        ))
    for strategy, names in candidates:
        if all(name in dtp_nodes for name in names):
            numbers = [dtp_nodes[name] for name in names]
            if len(set(numbers)) == 3:
                return {
                    "node_templates": templates,
                    "resolved_node_names": names,
                    "selected_node_numbers": numbers,
                    "strategy": strategy,
                    "bus_number": bus_number or None,
                }
    raise BackendSafetyViolation(
        "DTP does not contain a unique three-phase expansion of the "
        "selected bus nodes"
    )


@dataclass(frozen=True)
class ProductionBackendConfig:
    rscad_root: Path
    agent_root: Path
    expected_rscad_version: str = "2.7.3"
    allowed_racks: tuple[int, ...] = ()
    preferred_rack: int | None = None
    project_rack: int | None = None
    connection_timeout_seconds: int = 60
    fsat_timeout_seconds: int = 120
    runtime_max_channels: int = 64
    runtime_max_warmup_seconds: float = 30.0
    runtime_max_samples_per_channel: int = 2_000_000

    @property
    def projects_root(self) -> Path:
        return self.agent_root / "projects"

    @property
    def vendor_root(self) -> Path:
        return self.rscad_root / "Examples"

    @property
    def rscad_executable(self) -> Path:
        return self.rscad_root / "BIN" / "RSCAD_FX.exe"

    @property
    def fs_executable(self) -> Path:
        return self.rscad_root / "BIN" / "fs.exe"

    @property
    def gcc_bin(self) -> Path:
        return self.rscad_root / "BIN" / "GCC" / "bin"

    @property
    def component_definitions_root(self) -> Path:
        return self.rscad_root / "MLIB" / "COMPONENTS"

    @property
    def rtds_site_packages(self) -> Path:
        return (
            self.rscad_root / "python" / "internal interpreter"
            / "Lib" / "site-packages"
        )


class RscadFxCompileDriver:
    """Thin wrapper around documented RSCAD FX Python API calls."""

    def __init__(self, config: ProductionBackendConfig) -> None:
        self.config = config

    def _new_connection(self) -> Any:
        sys.path.insert(0, str(self.config.rtds_site_packages))
        import rtds.comms.connection_setup as connection_setup
        import rtds.rscadfx

        connection_setup.executable = self.config.rscad_executable
        connection_setup.in_existing = True
        connection_setup.timeout = self.config.connection_timeout_seconds
        return rtds.rscadfx.remote_connection()

    def query_racks(self) -> dict[str, Any]:
        from rtds_agent.core.rack_selector import select_rack

        app = self._new_connection()
        connected = False
        try:
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                app.connect()
            connected = True
            version = str(app.get_version())
            if version != self.config.expected_rscad_version:
                raise ProductionBackendError(
                    f"unexpected RSCAD FX version: {version}"
                )
            configured = sorted(int(rack.num) for rack in app.racks)
            available = sorted(int(rack.num) for rack in app.get_available_racks())
            if self.config.allowed_racks:
                available = [r for r in available if r in self.config.allowed_racks]
            selection = select_rack(
                available,
                configured,
                project_rack=self.config.project_rack,
                preferred_rack=self.config.preferred_rack,
            )
            if selection["status"] != "selected":
                raise ProductionBackendError(selection["reason"])
            return {
                "source": "live_query_immediately_before_action",
                "refreshed_at": now_iso(),
                "rscad_fx_version": version,
                **selection,
            }
        finally:
            if connected:
                app.disconnect(terminate=False)

    def compile_case(self, *, working_copy: str, rack: int) -> dict[str, Any]:
        working = Path(working_copy).resolve()
        build_dir = working.parent / f"build_{working.stem}"
        dtp = build_dir / f"{working.stem}.dtp"
        rack_binary = build_dir / f"{working.stem}_r{rack}"
        result: dict[str, Any] = {
            "connected": False,
            "version": None,
            "available_racks": [],
            "opened_file": None,
            "starting_rack_before": None,
            "starting_rack_for_compile": rack,
            "starting_rack_changed_in_memory": False,
            "case_save_called": False,
            "compile_called": False,
            "compile_return_value": None,
            "case_closed": False,
            "disconnected": False,
            "artifacts": {"dtp": str(dtp), "rack_binary": str(rack_binary)},
            "errors": [],
            "cleanup_errors": [],
        }
        app = None
        case = None
        try:
            app = self._new_connection()
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                app.connect()
            result["connected"] = True
            result["version"] = str(app.get_version())
            if result["version"] != self.config.expected_rscad_version:
                raise ProductionBackendError(
                    f"unexpected RSCAD FX version: {result['version']}"
                )
            result["available_racks"] = sorted(
                int(item.num) for item in app.get_available_racks()
            )
            if rack not in result["available_racks"]:
                raise BackendSafetyViolation(
                    f"selected rack {rack} is no longer available"
                )
            existing = app.get_case(file=str(working), open_file=False)
            if existing is not None:
                raise BackendSafetyViolation(
                    "working copy is already open; refusing to reuse it"
                )
            case = app.open_case(str(working))
            result["opened_file"] = str(case.file)
            if normalized(case.file) != normalized(working):
                raise BackendSafetyViolation(
                    f"RSCAD opened unexpected file: {case.file}"
                )
            before_rack = int(case.settings.starting_rack)
            result["starting_rack_before"] = before_rack
            if before_rack != rack:
                case.settings.starting_rack = rack
                result["starting_rack_changed_in_memory"] = True
            if int(case.settings.starting_rack) != rack:
                raise BackendSafetyViolation(
                    "case starting_rack does not match selected rack"
                )
            result["compile_called"] = True
            compile_value = case.compile()
            result["compile_return_value"] = repr(compile_value)
            result["compile_return_succeeded"] = bool(compile_value)
        except Exception as exc:
            result["errors"].append({
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })
        finally:
            if case is not None:
                try:
                    case.close(force=True)
                    result["case_closed"] = True
                except Exception as exc:
                    result["cleanup_errors"].append({
                        "operation": "case.close(force=True)",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    })
            if result["connected"] and app is not None:
                try:
                    app.disconnect(terminate=False)
                    result["disconnected"] = True
                except Exception as exc:
                    result["cleanup_errors"].append({
                        "operation": "disconnect(terminate=False)",
                        "type": type(exc).__name__,
                        "message": str(exc),
                    })

        result["succeeded"] = bool(
            result["compile_called"]
            and result.get("compile_return_succeeded") is True
            and dtp.is_file()
            and rack_binary.is_file()
            and result["case_closed"]
            and result["disconnected"]
            and not result["errors"]
            and not result["cleanup_errors"]
        )
        return result


ProcessRunner = Callable[..., subprocess.CompletedProcess[str]]


class ProductionRscadBackend:
    """Compile/offline backend plus an explicitly enabled Runtime adapter."""

    def __init__(
        self,
        config: ProductionBackendConfig | None = None,
        *,
        compile_driver: Any | None = None,
        process_runner: ProcessRunner | None = None,
        runtime_driver: Any | None = None,
        runtime_enabled: bool = False,
    ) -> None:
        self.config = config
        if config is None:
            raise BackendSafetyViolation("Explicit installation configuration is required")
        self.compile_driver = compile_driver or RscadFxCompileDriver(self.config)
        self.process_runner = process_runner or subprocess.run
        self.runtime_driver = runtime_driver
        self.runtime_enabled = bool(runtime_enabled)
        self.call_log: list[dict[str, Any]] = []
        self._last_rack_snapshot: dict[str, Any] | None = None

    def _project_context(
        self,
        working_copy: str,
        expected_working_sha256: str,
        source_path: str,
        expected_source_sha256: str,
        input_files: list[dict[str, str]] | None = None,
        expected_input_bundle_sha256: str | None = None,
        expected_companion_discovery_sha256: str | None = None,
    ) -> tuple[
        Path,
        Path,
        Path,
        list[dict[str, str]],
        dict[str, Any],
    ]:
        source = Path(source_path).resolve()
        working = Path(working_copy).resolve()
        if not source.is_file():
            raise BackendSafetyViolation("source case does not exist")
        if not working.is_file():
            raise BackendSafetyViolation("working copy does not exist")
        if normalized(source) == normalized(working):
            raise BackendSafetyViolation("source and working copy are identical")
        if not is_within(working, self.config.projects_root):
            raise BackendSafetyViolation("working copy is outside agent projects")
        if is_within(working, self.config.vendor_root):
            raise BackendSafetyViolation("working copy is inside vendor source tree")
        if sha256_file(source) != expected_source_sha256:
            raise BackendSafetyViolation("source hash changed after inspection")
        if sha256_file(working) != expected_working_sha256:
            raise BackendSafetyViolation(
                "working-copy hash changed after authorization"
            )
        if working.parent.name != "working":
            raise BackendSafetyViolation(
                "working copy must be inside a run-specific working directory"
            )
        canonical_inputs: list[dict[str, str]] = []
        seen_inputs: set[str] = set()
        for index, item in enumerate(input_files or []):
            try:
                input_path = Path(str(item["path"])).resolve()
                digest = str(item["sha256"]).lower()
            except (KeyError, TypeError) as exc:
                raise BackendSafetyViolation(
                    f"invalid companion input record at index {index}"
                ) from exc
            if not is_within(input_path, working.parent) or input_path == working:
                raise BackendSafetyViolation(
                    "companion input is outside the working directory"
                )
            normalized_path = normalized(input_path)
            if normalized_path in seen_inputs:
                raise BackendSafetyViolation("duplicate companion input")
            if not input_path.is_file():
                raise BackendSafetyViolation("companion input is missing")
            if sha256_file(input_path) != digest:
                raise BackendSafetyViolation(
                    "companion input hash changed after authorization"
                )
            seen_inputs.add(normalized_path)
            canonical_inputs.append({"path": str(input_path), "sha256": digest})
        canonical_inputs.sort(key=lambda item: item["path"].lower())
        actual_bundle_sha256 = (
            sha256_json(canonical_inputs) if canonical_inputs else None
        )
        if actual_bundle_sha256 != expected_input_bundle_sha256:
            raise BackendSafetyViolation(
                "companion input bundle does not match authorization scope"
            )
        companion_discovery = {
            "mode": "legacy_declared_bundle_only",
            "required": False,
            "sha256": None,
            "reference_count": None,
            "file_count": len(canonical_inputs),
        }
        if expected_companion_discovery_sha256 is not None:
            try:
                discovered = discover_companion_dependencies(
                    working,
                    self.config.component_definitions_root,
                    search_root=working.parent,
                )
                if discovered["passed"] is not True:
                    raise CompanionDiscoveryError(
                        "RTIFX companion discovery is incomplete"
                    )
                if (
                    discovered["discovery_sha256"]
                    != str(expected_companion_discovery_sha256).lower()
                ):
                    raise CompanionDiscoveryError(
                        "RTIFX companion discovery fingerprint changed"
                    )
                verify_declared_inputs(discovered, canonical_inputs)
            except CompanionDiscoveryError as exc:
                raise BackendSafetyViolation(str(exc)) from exc
            companion_discovery = {
                "mode": discovered["mode"],
                "required": True,
                "sha256": discovered["discovery_sha256"],
                "reference_count": discovered["summary"][
                    "reference_count"
                ],
                "file_count": discovered["summary"]["file_count"],
            }
        return (
            source,
            working,
            working.parent.parent,
            canonical_inputs,
            companion_discovery,
        )

    def refresh_racks(self, action: str) -> dict[str, Any]:
        if action not in {"compile", "runtime_start_stop"}:
            raise BackendSafetyViolation(
                f"rack discovery is forbidden for action {action}"
            )
        snapshot = dict(self.compile_driver.query_racks())
        snapshot["action"] = action
        available = [int(item) for item in snapshot.get("available_racks", [])]
        selected = snapshot.get("selected_rack")
        if (
            snapshot.get("source") != "live_query_immediately_before_action"
            or selected is None
            or int(selected) not in available
        ):
            raise BackendSafetyViolation("invalid live rack snapshot")
        self._last_rack_snapshot = snapshot
        self.call_log.append({"call": "refresh_racks", "action": action})
        return snapshot

    def compile(
        self,
        *,
        working_copy: str,
        rack: int,
        expected_working_sha256: str,
        source_path: str,
        expected_source_sha256: str,
        input_files: list[dict[str, str]] | None = None,
        expected_input_bundle_sha256: str | None = None,
        expected_companion_discovery_sha256: str | None = None,
    ) -> dict[str, Any]:
        (
            source,
            working,
            run_dir,
            companion_inputs,
            companion_discovery,
        ) = self._project_context(
            working_copy,
            expected_working_sha256,
            source_path,
            expected_source_sha256,
            input_files,
            expected_input_bundle_sha256,
            expected_companion_discovery_sha256,
        )
        if (
            self._last_rack_snapshot is None
            or self._last_rack_snapshot.get("action") != "compile"
            or int(self._last_rack_snapshot.get("selected_rack", -1)) != int(rack)
        ):
            raise BackendSafetyViolation(
                "compile requires the matching immediate rack snapshot"
            )
        output_path = run_dir / "production_compile_execution.json"
        expected_build = working.parent / f"build_{working.stem}"
        expected_dtp = expected_build / f"{working.stem}.dtp"
        expected_binary = expected_build / f"{working.stem}_r{rack}"
        if output_path.exists():
            raise BackendSafetyViolation(
                "production compile manifest already exists; overwrite refused"
            )
        if expected_dtp.exists() or expected_binary.exists():
            raise BackendSafetyViolation(
                "compile artifact already exists; overwrite refused"
            )
        source_before = sha256_file(source)
        working_before = sha256_file(working)
        inputs_before = {
            item["path"]: sha256_file(item["path"])
            for item in companion_inputs
        }
        driver_result = self.compile_driver.compile_case(
            working_copy=str(working), rack=int(rack)
        )
        source_after = sha256_file(source)
        working_after = sha256_file(working)
        inputs_after = {
            item["path"]: sha256_file(item["path"])
            for item in companion_inputs
        }
        artifact_paths = {
            name: Path(path).resolve()
            for name, path in driver_result.get("artifacts", {}).items()
        }
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_boundary_ok = True
        for name, path in artifact_paths.items():
            if not is_within(path, working.parent):
                artifact_boundary_ok = False
            elif path.is_file():
                artifacts[name] = file_ref(path)
        succeeded = bool(
            driver_result.get("succeeded")
            and source_before == source_after == expected_source_sha256
            and working_before == working_after == expected_working_sha256
            and inputs_before == inputs_after
            and artifact_boundary_ok
            and {"dtp", "rack_binary"}.issubset(artifacts)
            and not driver_result.get("case_save_called", False)
        )
        manifest = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "backend": "ProductionRscadBackend",
            "action": "compile",
            "status": "compile_succeeded" if succeeded else "compile_failed",
            "source_path": str(source),
            "working_copy": str(working),
            "selected_rack": int(rack),
            "rack_snapshot": self._last_rack_snapshot,
            "hashes": {
                "source_before": source_before,
                "source_after": source_after,
                "source_unchanged": source_before == source_after,
                "working_before": working_before,
                "working_after": working_after,
                "working_unchanged": working_before == working_after,
                "companion_inputs_before": inputs_before,
                "companion_inputs_after": inputs_after,
                "companion_inputs_unchanged": inputs_before == inputs_after,
                "input_bundle_sha256": expected_input_bundle_sha256,
                "companion_discovery_sha256": (
                    companion_discovery["sha256"]
                ),
            },
            "companion_discovery": companion_discovery,
            "artifact_boundary_ok": artifact_boundary_ok,
            "artifacts": artifacts,
            "driver": driver_result,
            "safety": {
                "case_run_called": False,
                "runtime_write_called": False,
                "hardware_io_called": False,
                "rack_configuration_changed": False,
                "case_save_called": bool(
                    driver_result.get("case_save_called", False)
                ),
            },
        }
        write_json(output_path, manifest)
        self.call_log.append(
            {"call": "compile", "working_copy": str(working), "rack": int(rack)}
        )
        return {
            "succeeded": succeeded,
            "artifact_sha256": (
                artifacts["rack_binary"]["sha256"] if succeeded else None
            ),
            "result_ref": {
                **file_ref(output_path),
                "dtp": artifacts.get("dtp"),
                "rack_binary": artifacts.get("rack_binary"),
            },
        }

    def _compile_evidence(self, run_dir: Path) -> dict[str, Any]:
        candidates = [
            run_dir / "production_compile_execution.json",
            run_dir / "compile_execution.json",
        ]
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            raise BackendSafetyViolation("compile evidence is missing")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        return {
            "path": path,
            "manifest": manifest,
            "artifacts": manifest.get("artifacts", {}),
        }

    def run_offline_test(
        self,
        *,
        working_copy: str,
        test_spec: dict[str, Any],
        expected_working_sha256: str,
        compiled_artifact_sha256: str | None,
        source_path: str,
        expected_source_sha256: str,
        input_files: list[dict[str, str]] | None = None,
        expected_input_bundle_sha256: str | None = None,
        expected_companion_discovery_sha256: str | None = None,
    ) -> dict[str, Any]:
        (
            source,
            working,
            run_dir,
            companion_inputs,
            companion_discovery,
        ) = self._project_context(
            working_copy,
            expected_working_sha256,
            source_path,
            expected_source_sha256,
            input_files,
            expected_input_bundle_sha256,
            expected_companion_discovery_sha256,
        )
        notes = test_spec.get("execution_notes", {})
        if test_spec.get("runtime_required") is not False:
            raise BackendSafetyViolation("offline test must explicitly forbid Runtime")
        if notes.get("case_run_forbidden") is not True:
            raise BackendSafetyViolation("offline test must forbid case.run()")
        if test_spec.get("execution_mode") not in {"offline_analytical_frequency_scan", "offline_frequency_scan"}:
            raise BackendSafetyViolation("unsupported offline execution mode")
        scan = test_spec.get("scan", {})
        if scan.get("domain") != "DQ0":
            raise BackendSafetyViolation(
                "only the verified DQ0 FSAT contract is supported"
            )
        if compiled_artifact_sha256 is None:
            raise BackendSafetyViolation("compiled artifact hash is required")

        compile_evidence = self._compile_evidence(run_dir)
        artifacts = compile_evidence["artifacts"]
        try:
            dtp = Path(artifacts["dtp"]["path"]).resolve()
            rack_binary = Path(artifacts["rack_binary"]["path"]).resolve()
        except (KeyError, TypeError) as exc:
            raise BackendSafetyViolation(
                "compile artifact references are incomplete"
            ) from exc
        if not is_within(dtp, working.parent) or not is_within(
            rack_binary, working.parent
        ):
            raise BackendSafetyViolation(
                "compile artifact is outside working boundary"
            )
        if not dtp.is_file() or not rack_binary.is_file():
            raise BackendSafetyViolation("compile artifact is missing")
        if sha256_file(dtp) != artifacts["dtp"].get("sha256"):
            raise BackendSafetyViolation(
                "DTP hash changed after compile evidence was recorded"
            )
        if sha256_file(rack_binary) != artifacts["rack_binary"].get("sha256"):
            raise BackendSafetyViolation(
                "rack binary hash changed after compile evidence was recorded"
            )
        if sha256_file(rack_binary) != compiled_artifact_sha256:
            raise BackendSafetyViolation(
                "compiled artifact hash changed after approval"
            )

        topology_path = run_dir / "topology.json"
        if not topology_path.is_file():
            raise BackendSafetyViolation("topology evidence is missing")
        topology = json.loads(topology_path.read_text(encoding="utf-8"))
        selected_bus = str(scan.get("selected_bus", ""))
        bus_matches = [
            component
            for component in topology.get("components", [])
            if component.get("component_type") == "rtds_sharc_sld_BUSLABEL"
            and str(component.get("parameters", {}).get("BName", "")).rstrip("#")
            == selected_bus
        ]
        if len(bus_matches) != 1:
            raise BackendSafetyViolation(
                "selected FSAT bus must resolve uniquely"
            )
        parameters = bus_matches[0].get("parameters", {})
        bus_resolution = resolve_bus_nodes(
            parameters, parse_dtp_nodes(dtp)
        )
        selected_nodes = bus_resolution["selected_node_numbers"]

        if not self.config.fs_executable.is_file():
            raise BackendSafetyViolation("fs.exe is missing")
        if not self.config.gcc_bin.is_dir():
            raise BackendSafetyViolation("GCC/bin is missing")
        preflight_path = run_dir / "preflight.json"
        if preflight_path.is_file():
            preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
            expected_fs_hash = preflight.get(
                "offline_scan_tool", {}
            ).get("sha256")
            if (
                expected_fs_hash
                and sha256_file(self.config.fs_executable) != expected_fs_hash
            ):
                raise BackendSafetyViolation(
                    "fs.exe hash changed since preflight"
                )

        output_dir = (run_dir / "outputs").resolve()
        output_base = str(scan.get("output_basename", "frequency_scan"))
        extension = str(scan.get("expected_extension", ".fscn"))
        if extension.lower() != ".fscn":
            raise BackendSafetyViolation(
                "offline FSAT output must use .fscn"
            )
        output_file = output_dir / f"{output_base}{extension}"
        if not is_within(output_file, run_dir):
            raise BackendSafetyViolation(
                "offline output is outside run directory"
            )
        if output_file.exists():
            raise BackendSafetyViolation(
                "offline output already exists; overwrite refused"
            )

        relative_output = os.path.relpath(output_dir, start=working.parent)
        relative_output_base = str(Path(relative_output) / output_base)
        command = [
            str(self.config.fs_executable),
            str(dtp),
            str(self.config.gcc_bin),
            relative_output_base,
            str(float(scan["start_frequency_hz"])),
            str(float(scan["end_frequency_hz"])),
            "0",
            str(float(scan["frequency_increment_hz"])),
            "1",
            str(float(scan["system_frequency_hz"])),
            "false",
            *[str(node) for node in selected_nodes],
        ]
        command_path = run_dir / "production_offline_command.json"
        result_path = run_dir / "production_offline_execution.json"
        stdout_path = run_dir / "production_offline_stdout.txt"
        stderr_path = run_dir / "production_offline_stderr.txt"
        write_json(command_path, {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "backend": "ProductionRscadBackend",
            "command": {
                "executable": command[0],
                "arguments": command[1:],
                "working_directory": str(working.parent),
                "expected_output": str(output_file),
                "shell": False,
            },
            "bus_resolution": {
                "selected_bus": selected_bus,
                **bus_resolution,
            },
        })

        hashes_before = {
            "source": sha256_file(source),
            "working": sha256_file(working),
            "dtp": sha256_file(dtp),
            "rack_binary": sha256_file(rack_binary),
            "fs_exe": sha256_file(self.config.fs_executable),
        }
        hashes_before.update({
            f"companion:{item['path']}": sha256_file(item["path"])
            for item in companion_inputs
        })
        output_dir.mkdir(parents=True, exist_ok=True)
        completed: subprocess.CompletedProcess[str] | None = None
        timed_out = False
        errors: list[dict[str, str]] = []
        try:
            completed = self.process_runner(
                command,
                cwd=working.parent,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.config.fsat_timeout_seconds,
                shell=False,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            errors.append({
                "type": type(exc).__name__,
                "message": str(exc),
            })
        except Exception as exc:
            errors.append({
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            })

        stdout = completed.stdout if completed is not None else ""
        stderr = completed.stderr if completed is not None else ""
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        hashes_after = {
            "source": sha256_file(source),
            "working": sha256_file(working),
            "dtp": sha256_file(dtp),
            "rack_binary": sha256_file(rack_binary),
            "fs_exe": sha256_file(self.config.fs_executable),
        }
        hashes_after.update({
            f"companion:{item['path']}": sha256_file(item["path"])
            for item in companion_inputs
        })
        integrity = {
            f"{name}_unchanged": hashes_before[name] == hashes_after[name]
            for name in hashes_before
        }
        raw_collected = (
            output_file.is_file() and output_file.stat().st_size > 0
        )
        success_text = (
            "Frequency Scan completed successfully!" in stdout
        )
        error_text_absent = (
            "Error:" not in stdout and "Error:" not in stderr
        )
        succeeded = bool(
            completed is not None
            and completed.returncode == 0
            and raw_collected
            and success_text
            and error_text_absent
            and all(integrity.values())
            and not errors
        )
        outputs: dict[str, Any] = {
            "stdout": file_ref(stdout_path),
            "stderr": file_ref(stderr_path),
        }
        if output_file.is_file():
            outputs["fscn"] = file_ref(output_file)
        manifest = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "backend": "ProductionRscadBackend",
            "action": "offline_test",
            "status": (
                "offline_scan_completed"
                if succeeded else "offline_scan_failed"
            ),
            "compile_evidence": str(compile_evidence["path"]),
            "command_manifest": str(command_path),
            "companion_discovery": companion_discovery,
            "execution": {
                "called": completed is not None,
                "return_code": (
                    completed.returncode if completed is not None else None
                ),
                "timed_out": timed_out,
                "success_text_found": success_text,
                "error_text_absent": error_text_absent,
            },
            "outputs": outputs,
            "hashes_before": hashes_before,
            "hashes_after": hashes_after,
            "integrity_after": integrity,
            "safety": {
                "rscad_connection_opened": False,
                "rack_query_called": False,
                "case_compile_called": False,
                "case_run_called": False,
                "runtime_write_called": False,
                "hardware_io_called": False,
                "source_write_called": False,
                "shell": False,
            },
            "errors": errors,
        }
        write_json(result_path, manifest)
        self.call_log.append({
            "call": "run_offline_test",
            "working_copy": str(working),
        })
        return {
            "succeeded": succeeded,
            "raw_data_collected": raw_collected,
            "result_ref": {
                **file_ref(result_path),
                "command_manifest": str(command_path),
                "command_manifest_ref": file_ref(command_path),
                "stdout": outputs["stdout"],
                "stderr": outputs["stderr"],
                "fscn": outputs.get("fscn"),
            },
        }

    def run_runtime(
        self,
        *,
        working_copy: str,
        rack: int,
        test_spec: dict[str, Any],
        expected_working_sha256: str,
        compiled_artifact_sha256: str | None,
        source_path: str,
        expected_source_sha256: str,
        input_files: list[dict[str, str]] | None = None,
        expected_input_bundle_sha256: str | None = None,
        expected_companion_discovery_sha256: str | None = None,
        authorization: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.runtime_enabled:
            raise BackendSafetyViolation(
                "Runtime is disabled; construct the backend with an explicit "
                "driver and runtime_enabled=True only for an approved job"
            )
        if self.runtime_driver is None:
            raise BackendSafetyViolation(
                "Runtime is enabled but no reviewed Runtime driver was injected"
            )
        try:
            runtime_plan = validate_runtime_test_spec(
                test_spec,
                max_channels=self.config.runtime_max_channels,
                max_warmup_seconds=self.config.runtime_max_warmup_seconds,
            )
        except RuntimeContractError as exc:
            raise BackendSafetyViolation(str(exc)) from exc

        (
            source,
            working,
            run_dir,
            companion_inputs,
            companion_discovery,
        ) = self._project_context(
            working_copy,
            expected_working_sha256,
            source_path,
            expected_source_sha256,
            input_files,
            expected_input_bundle_sha256,
            expected_companion_discovery_sha256,
        )
        if (
            self._last_rack_snapshot is None
            or self._last_rack_snapshot.get("action") != "runtime_start_stop"
            or int(self._last_rack_snapshot.get("selected_rack", -1)) != int(rack)
        ):
            raise BackendSafetyViolation(
                "Runtime requires the matching immediate live rack snapshot"
            )
        rack_snapshot = dict(self._last_rack_snapshot)

        if not isinstance(authorization, dict):
            raise BackendSafetyViolation(
                "consumed single-use Runtime approval receipt is required"
            )
        scope = authorization.get("scope")
        approval_snapshot = authorization.get("rack_snapshot")
        if (
            authorization.get("action") != "runtime_start_stop"
            or authorization.get("status") != "consumed"
            or authorization.get("single_use") is not True
            or not authorization.get("approval_id")
            or not authorization.get("consumed_at")
            or not isinstance(scope, dict)
            or not isinstance(approval_snapshot, dict)
        ):
            raise BackendSafetyViolation("invalid Runtime approval receipt")
        expected_scope = {
            "working_copy_sha256": expected_working_sha256,
            "source_sha256": expected_source_sha256,
            "test_spec_sha256": sha256_json(test_spec),
            "compiled_artifact_sha256": compiled_artifact_sha256,
            "compiled_rack": int(rack),
        }
        if expected_input_bundle_sha256 is not None:
            expected_scope["input_bundle_sha256"] = expected_input_bundle_sha256
        if expected_companion_discovery_sha256 is not None:
            expected_scope["companion_discovery_sha256"] = (
                expected_companion_discovery_sha256
            )
        if any(scope.get(key) != value for key, value in expected_scope.items()):
            raise BackendSafetyViolation(
                "Runtime approval receipt does not match the execution scope"
            )
        if approval_snapshot != rack_snapshot:
            raise BackendSafetyViolation(
                "Runtime approval rack snapshot does not match the backend snapshot"
            )

        rack_binary = (
            working.parent / f"build_{working.stem}" / f"{working.stem}_r{rack}"
        ).resolve()
        if not rack_binary.is_file() or not is_within(rack_binary, working.parent):
            raise BackendSafetyViolation(
                "compiled rack binary is missing or outside the working directory"
            )
        artifact_before = file_ref(rack_binary)
        if artifact_before["sha256"] != compiled_artifact_sha256:
            raise BackendSafetyViolation(
                "compiled rack binary hash does not match Runtime approval"
            )

        hashes_before = {
            "source": sha256_file(source),
            "working": sha256_file(working),
            "compiled_artifact": artifact_before["sha256"],
            "companion_inputs": {
                item["path"]: sha256_file(item["path"])
                for item in companion_inputs
            },
        }
        token = (
            datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        runtime_root = run_dir / "runtime_runs"
        runtime_root.mkdir(parents=True, exist_ok=True)
        runtime_run_dir = runtime_root / token
        runtime_run_dir.mkdir(exist_ok=False)
        result_path = runtime_run_dir / "runtime_execution.json"
        raw_path = runtime_run_dir / "raw_signals_long.csv"

        self._last_rack_snapshot = None
        try:
            capture_options: dict[str, Any] = {
                "working_copy": str(working),
                "rack": int(rack),
                "channels": runtime_plan["measurement_channels"],
                "warmup_seconds": runtime_plan["runtime_capture"]["warmup_seconds"],
                "loadflow_initialization": runtime_plan["loadflow_initialization"],
                "capture_directory": str(runtime_run_dir),
            }
            planned_control_writes = runtime_plan["runtime_controls"][
                "runtime_parameter_writes"
            ]
            if planned_control_writes:
                capture_options["runtime_parameter_writes"] = planned_control_writes
            driver_result = self.runtime_driver.capture_case(**capture_options)
            if not isinstance(driver_result, dict):
                raise TypeError("Runtime driver result must be an object")
        except Exception as exc:
            driver_result = {
                "connected": False,
                "version": None,
                "available_racks": [],
                "opened_file": None,
                "starting_rack": None,
                "run_state_before": None,
                "execution": {
                    "run_call_attempted": False,
                    "run_started": False,
                    "loadflow_call_attempted": False,
                    "loadflow_succeeded": False,
                    "update_plots_called": False,
                    "raw_data_collected": False,
                    "stop_call_attempted": False,
                    "stop_succeeded": False,
                    "run_state_after_stop": None,
                },
                "cleanup": {
                    "case_close_attempted": False,
                    "case_closed": False,
                    "disconnected": False,
                },
                "safety": {},
                "signals": {},
                "runtime_controls": {
                    "planned": len(
                        runtime_plan["runtime_controls"]["runtime_parameter_writes"]
                    ),
                    "restore_targets_planned": len(
                        {
                            (int(item["object_uuid"]), str(item["attribute"]))
                            for item in runtime_plan["runtime_controls"][
                                "runtime_parameter_writes"
                            ]
                        }
                    ),
                    "applied": 0,
                    "restored": 0,
                    "all_readbacks_verified": False,
                    "all_restored": False,
                    "actions": [],
                },
                "samples": {},
                "errors": [{"type": type(exc).__name__, "message": str(exc)}],
                "cleanup_errors": [],
            }

        hashes_after = {
            "source": sha256_file(source),
            "working": sha256_file(working),
            "compiled_artifact": sha256_file(rack_binary),
            "companion_inputs": {
                item["path"]: sha256_file(item["path"])
                for item in companion_inputs
            },
        }
        integrity = {
            key + "_unchanged": hashes_after[key] == hashes_before[key]
            for key in hashes_before
        }
        execution = dict(driver_result.get("execution") or {})
        cleanup = dict(driver_result.get("cleanup") or {})
        safety = dict(driver_result.get("safety") or {})
        errors = list(driver_result.get("errors") or [])
        cleanup_errors = list(driver_result.get("cleanup_errors") or [])
        required_safety_flags = (
            "compile_called",
            "case_settings_write_called",
            "rack_power_change_called",
            "rack_security_change_called",
            "rack_configuration_changed",
            "deployment_called",
            "hardware_io_called",
            "case_save_called",
            "source_write_called",
        )
        loadflow_enabled = runtime_plan["loadflow_initialization"]["enabled"]
        loadflow_clean = bool(
            safety.get("load_flow_called") is loadflow_enabled
            and execution.get("loadflow_call_attempted") is loadflow_enabled
            and execution.get("loadflow_succeeded") is loadflow_enabled
        )
        planned_writes = runtime_plan["runtime_controls"]["runtime_parameter_writes"]
        planned_restore_targets = len(
            {
                (int(item["object_uuid"]), str(item["attribute"]))
                for item in planned_writes
            }
        )
        control_evidence = dict(driver_result.get("runtime_controls") or {})
        if planned_writes:
            controls_clean = bool(
                safety.get("runtime_parameter_write_called") is True
                and int(control_evidence.get("planned", -1)) == len(planned_writes)
                and int(control_evidence.get("applied", -1)) == len(planned_writes)
                and int(control_evidence.get("restore_targets_planned", -1))
                == planned_restore_targets
                and int(control_evidence.get("restored", -1))
                == planned_restore_targets
                and control_evidence.get("all_readbacks_verified") is True
                and control_evidence.get("all_restored") is True
            )
        else:
            # Legacy/read-only drivers need not emit control evidence. They must
            # still prove that no Runtime parameter write occurred.
            controls_clean = bool(
                safety.get("runtime_parameter_write_called") is False
                and int(control_evidence.get("planned", 0)) == 0
                and int(control_evidence.get("applied", 0)) == 0
                and int(control_evidence.get("restored", 0)) == 0
                and not control_evidence.get("actions")
            )
        safety_clean = bool(
            loadflow_clean
            and controls_clean
            and all(safety.get(name) is False for name in required_safety_flags)
        )
        non_artifact_integrity_clean = all(
            value
            for key, value in integrity.items()
            if key != "compiled_artifact_unchanged"
        )
        compiled_artifact_integrity_clean = bool(
            integrity.get("compiled_artifact_unchanged") is True
            or (
                loadflow_enabled
                and execution.get("loadflow_succeeded") is True
                and safety.get("load_flow_called") is True
            )
        )
        integrity_clean = bool(
            non_artifact_integrity_clean and compiled_artifact_integrity_clean
        )
        compiled_artifact_change_authorized_by_loadflow = bool(
            integrity.get("compiled_artifact_unchanged") is False
            and loadflow_enabled
            and execution.get("loadflow_succeeded") is True
            and safety.get("load_flow_called") is True
        )

        raw_data: dict[str, Any] | None = None
        channel_summaries: dict[str, dict[str, Any]] = {}
        try:
            canonical_samples = validate_samples(
                driver_result.get("samples") or {},
                runtime_plan["measurement_channels"],
                minimum_samples=runtime_plan["runtime_capture"][
                    "minimum_samples_per_channel"
                ],
                max_samples_per_channel=(
                    self.config.runtime_max_samples_per_channel
                ),
            )
            row_count = write_raw_signal_csv(
                raw_path,
                canonical_samples,
                runtime_plan["measurement_channels"],
            )
            raw_data = {**file_ref(raw_path), "rows": row_count}
            channel_summaries = {
                channel_id: {
                    "signal_path": item["signal_path"],
                    "units": item["units"],
                    "sample_count": len(item["values"]),
                    "time_min_s": min(item["times"]),
                    "time_max_s": max(item["times"]),
                    "value_min": min(item["values"]),
                    "value_max": max(item["values"]),
                }
                for channel_id, item in canonical_samples.items()
            }
        except Exception as exc:
            errors.append({"type": type(exc).__name__, "message": str(exc)})

        opened_file_matches = (
            driver_result.get("opened_file") is not None
            and normalized(driver_result["opened_file"]) == normalized(working)
        )
        run_started = execution.get("run_started") is True
        stopped = bool(
            execution.get("stop_succeeded") is True
            and str(execution.get("run_state_after_stop", "")).lower()
            == "stopped"
        )
        raw_collected = bool(
            execution.get("raw_data_collected") is True and raw_data is not None
        )
        cleanup_complete = bool(
            cleanup.get("case_closed") is True
            and cleanup.get("disconnected") is True
        )
        safe_completion = bool(
            driver_result.get("connected") is True
            and driver_result.get("version") == self.config.expected_rscad_version
            and int(rack) in [
                int(item) for item in driver_result.get("available_racks", [])
            ]
            and opened_file_matches
            and int(driver_result.get("starting_rack", -1)) == int(rack)
            and str(driver_result.get("run_state_before", "")).lower()
            == "stopped"
            and execution.get("run_call_attempted") is True
            and loadflow_clean
            and controls_clean
            and run_started
            and execution.get("update_plots_called") is True
            and raw_collected
            and execution.get("stop_call_attempted") is True
            and stopped
            and cleanup_complete
            and integrity_clean
            and safety_clean
            and not errors
            and not cleanup_errors
        )
        if not integrity_clean:
            errors.append(
                {"type": "IntegrityError", "message": "Runtime inputs changed during execution"}
            )
        if not safety_clean:
            errors.append(
                {
                    "type": "SafetyTelemetryError",
                    "message": (
                        "unauthorized Runtime operation, control write mismatch, restore failure, "
                        "or load-flow telemetry mismatch reported"
                    ),
                }
            )
        if safe_completion:
            status = "runtime_completed"
        elif execution.get("run_call_attempted") and not (
            stopped and cleanup_complete
        ):
            status = "runtime_cleanup_failed"
        else:
            status = "runtime_failed"

        authorization_evidence = {
            key: authorization[key]
            for key in (
                "approval_id",
                "request_id",
                "action",
                "risk_level",
                "actor",
                "source",
                "scope",
                "granted_at",
                "single_use",
                "status",
                "consumed_at",
                "rack_snapshot",
            )
            if key in authorization
        }
        driver_evidence = {
            key: value
            for key, value in driver_result.items()
            if key != "samples"
        }
        manifest = {
            "schema_version": "1.0",
            "created_at": now_iso(),
            "backend": "ProductionRscadBackend",
            "action": "runtime_start_stop",
            "status": status,
            "safe_completion": safe_completion,
            "run_directory": str(runtime_run_dir),
            "source_path": str(source),
            "working_copy": str(working),
            "selected_rack": int(rack),
            "authorization": authorization_evidence,
            "runtime_plan": runtime_plan,
            "runtime_plan_sha256": sha256_json(runtime_plan),
            "rack_snapshot": rack_snapshot,
            "compiled_artifact": artifact_before,
            "companion_discovery": companion_discovery,
            "hashes": {
                "before": hashes_before,
                "after": hashes_after,
                "integrity": integrity,
                "compiled_artifact_change_authorized_by_loadflow": (
                    compiled_artifact_change_authorized_by_loadflow
                ),
                "input_bundle_sha256": expected_input_bundle_sha256,
                "companion_discovery_sha256": companion_discovery["sha256"],
            },
            "execution": execution,
            "cleanup": cleanup,
            "signals": channel_summaries,
            "raw_data": raw_data,
            "safety": safety,
            "driver": driver_evidence,
            "errors": errors,
            "cleanup_errors": cleanup_errors,
        }
        write_json(result_path, manifest)
        self.call_log.append(
            {"call": "run_runtime", "working_copy": str(working), "rack": int(rack)}
        )
        return {
            "succeeded": safe_completion,
            "safe_completion": safe_completion,
            "run_started": run_started,
            "stopped": stopped,
            "raw_data_collected": raw_collected,
            "result_ref": {
                **file_ref(result_path),
                "raw_data": raw_data,
            },
        }


def validate_existing_run(run_dir: str | Path) -> dict[str, Any]:
    """Recompute hashes and validate an existing Compile/FSAT evidence bundle."""

    root = Path(run_dir).resolve()
    workflow_path = root / "workflow.json"
    compile_path = root / "compile_execution.json"
    offline_path = root / "offline_scan_execution.json"
    required = [workflow_path, compile_path, offline_path]
    if any(not item.is_file() for item in required):
        missing = [str(item) for item in required if not item.is_file()]
        raise ProductionBackendError(
            f"existing evidence is incomplete: {missing}"
        )

    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    compile_manifest = json.loads(
        compile_path.read_text(encoding="utf-8")
    )
    offline_manifest = json.loads(
        offline_path.read_text(encoding="utf-8")
    )
    project = workflow["project"]
    source = Path(project["source_path"]).resolve()
    working = Path(project["working_copy"]).resolve()
    compile_artifacts = compile_manifest.get("artifacts", {})
    dtp = Path(compile_artifacts["dtp"]["path"]).resolve()
    rack_binary = Path(
        compile_artifacts["rack_binary"]["path"]
    ).resolve()
    fscn = Path(
        offline_manifest["outputs"]["fscn"]["path"]
    ).resolve()

    checks = {
        "workflow_verified": workflow.get("state") == "verified",
        "source_hash_matches_workflow": (
            source.is_file()
            and sha256_file(source) == project.get("source_sha256")
        ),
        "working_hash_matches_workflow": (
            working.is_file()
            and sha256_file(working) == project.get("working_sha256")
        ),
        "compile_called": (
            compile_manifest.get("compile", {}).get("called") is True
        ),
        "compile_succeeded": (
            compile_manifest.get("compile", {}).get("succeeded") is True
        ),
        "compile_cleanup_complete": (
            compile_manifest.get("cleanup", {}).get("case_closed") is True
            and compile_manifest.get("cleanup", {}).get("disconnected") is True
            and not compile_manifest.get("cleanup_errors")
        ),
        "compile_runtime_forbidden": not any(
            compile_manifest.get("safety", {}).get(key, False)
            for key in (
                "case_run_called",
                "runtime_write_called",
                "rack_power_change_called",
                "rack_security_change_called",
                "case_save_called",
                "vendor_source_write_called",
            )
        ),
        "dtp_hash_matches": (
            dtp.is_file()
            and sha256_file(dtp)
            == compile_artifacts["dtp"].get("sha256")
        ),
        "rack_binary_hash_matches": (
            rack_binary.is_file()
            and sha256_file(rack_binary)
            == compile_artifacts["rack_binary"].get("sha256")
        ),
        "workflow_compile_artifact_matches": (
            workflow.get("compile", {}).get("artifact_sha256")
            == compile_artifacts["rack_binary"].get("sha256")
        ),
        "offline_called": (
            offline_manifest.get("execution", {}).get("called") is True
        ),
        "offline_return_code_zero": (
            offline_manifest.get("execution", {}).get("return_code") == 0
        ),
        "offline_not_timed_out": (
            offline_manifest.get("execution", {}).get("timed_out") is False
        ),
        "offline_integrity_passed": all(
            offline_manifest.get("integrity_after", {}).values()
        ),
        "offline_runtime_forbidden": not any(
            offline_manifest.get("safety", {}).get(key, False)
            for key in (
                "rscad_connection_opened",
                "rack_query_called",
                "case_compile_called",
                "case_run_called",
                "case_stop_called",
                "runtime_write_called",
                "hardware_io_called",
                "source_write_called",
            )
        ),
        "fscn_hash_matches": (
            fscn.is_file()
            and sha256_file(fscn)
            == offline_manifest["outputs"]["fscn"].get("sha256")
        ),
        "offline_result_recorded": (
            workflow.get("offline_test", {}).get("succeeded") is True
            and workflow.get("offline_test", {}).get(
                "raw_data_collected"
            ) is True
        ),
        "verdict_passed": (
            workflow.get("verdict", {}).get("passed") is True
        ),
    }
    return {
        "schema_version": "1.0",
        "checked_at": now_iso(),
        "run_dir": str(root),
        "adapter": "ProductionRscadBackend",
        "mode": "existing_evidence_revalidation_no_execution",
        "passed": all(checks.values()),
        "checks": checks,
        "evidence": {
            "workflow": file_ref(workflow_path),
            "compile": file_ref(compile_path),
            "offline": file_ref(offline_path),
            "dtp": file_ref(dtp),
            "rack_binary": file_ref(rack_binary),
            "fscn": file_ref(fscn),
        },
    }
