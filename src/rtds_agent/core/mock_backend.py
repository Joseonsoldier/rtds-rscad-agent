from __future__ import annotations

from typing import Any


class MockBackend:
    """In-memory backend used only for state-machine tests and dry runs."""

    def __init__(
        self,
        *,
        available_racks: list[int] | None = None,
        selected_rack: int = 1,
        compile_succeeds: bool = True,
        offline_test_succeeds: bool = True,
        runtime_stops: bool = True,
    ) -> None:
        self.available_racks = list(available_racks or [1])
        self.selected_rack = selected_rack
        self.compile_succeeds = compile_succeeds
        self.offline_test_succeeds = offline_test_succeeds
        self.runtime_stops = runtime_stops
        self.call_log: list[dict[str, Any]] = []
        self._refresh_counter = 0

    def refresh_racks(self, action: str) -> dict[str, Any]:
        self._refresh_counter += 1
        snapshot = {
            "source": "live_query_immediately_before_action",
            "refreshed_at": f"mock-refresh-{self._refresh_counter}",
            "action": action,
            "available_racks": list(self.available_racks),
            "selected_rack": self.selected_rack,
        }
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
        self.call_log.append({
            "call": "compile",
            "working_copy": working_copy,
            "rack": rack,
            "expected_working_sha256": expected_working_sha256,
            "source_path": source_path,
            "expected_source_sha256": expected_source_sha256,
        })
        return {
            "succeeded": self.compile_succeeds,
            "artifact_sha256": "a" * 64 if self.compile_succeeds else None,
            "result_ref": {"backend": "mock", "operation": "compile"},
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
        self.call_log.append({
            "call": "run_offline_test",
            "working_copy": working_copy,
            "expected_working_sha256": expected_working_sha256,
            "compiled_artifact_sha256": compiled_artifact_sha256,
            "source_path": source_path,
            "expected_source_sha256": expected_source_sha256,
        })
        return {
            "succeeded": self.offline_test_succeeds,
            "raw_data_collected": self.offline_test_succeeds,
            "result_ref": {
                "backend": "mock",
                "operation": "offline_test",
                "test_id": test_spec.get("test_id"),
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
        self.call_log.append({
            "call": "run_runtime",
            "working_copy": working_copy,
            "rack": rack,
            "expected_working_sha256": expected_working_sha256,
            "compiled_artifact_sha256": compiled_artifact_sha256,
            "source_path": source_path,
            "expected_source_sha256": expected_source_sha256,
        })
        return {
            "run_started": True,
            "stopped": self.runtime_stops,
            "raw_data_collected": True,
            "result_ref": {
                "backend": "mock",
                "operation": "runtime",
                "test_id": test_spec.get("test_id"),
            },
        }
