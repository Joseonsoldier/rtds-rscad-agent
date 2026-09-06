from __future__ import annotations

from typing import Any, Protocol

from rtds_agent.core.state_machine import ApprovalAction, ApprovalRequired, Workflow, WorkflowState


class ExecutionBackend(Protocol):
    def refresh_racks(self, action: str) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...

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
    ) -> dict[str, Any]: ...


class ApprovalGatedOrchestrator:
    """Orders safety checks around a backend without embedding RSCAD API calls."""

    def __init__(self, workflow: Workflow, backend: ExecutionBackend):
        self.workflow = workflow
        self.backend = backend

    def _backend_error_ref(self, operation: str, exc: Exception) -> dict[str, Any]:
        return {
            "backend_operation": operation,
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    def _project_args(self) -> dict[str, Any]:
        project = self.workflow.manifest["project"]
        return {
            "working_copy": project["working_copy"],
            "expected_working_sha256": project["working_sha256"],
            "source_path": project["source_path"],
            "expected_source_sha256": project["source_sha256"],
            "input_files": project.get("input_files"),
            "expected_input_bundle_sha256": project.get(
                "input_bundle_sha256"
            ),
            "expected_companion_discovery_sha256": project.get(
                "companion_discovery_sha256"
            ),
        }

    def execute_compile(self) -> dict[str, Any]:
        if self.workflow.state is not WorkflowState.COMPILE_APPROVED:
            raise ApprovalRequired(
                "compile authorization is required before rack discovery or compile"
            )
        from .event_timing import require_executable_timing
        require_executable_timing(self.workflow.manifest['test_spec'])
        rack_snapshot = self.backend.refresh_racks(ApprovalAction.COMPILE.value)
        self.workflow.consume_approval(
            ApprovalAction.COMPILE, rack_snapshot=rack_snapshot
        )
        selected_rack = int(rack_snapshot["selected_rack"])
        try:
            result = self.backend.compile(
                rack=selected_rack,
                **self._project_args(),
            )
        except Exception as exc:
            self.workflow.record_compile_result(
                succeeded=False,
                artifact_sha256=None,
                result_ref=self._backend_error_ref("compile", exc),
            )
            raise
        self.workflow.record_compile_result(
            succeeded=bool(result["succeeded"]),
            artifact_sha256=result.get("artifact_sha256"),
            result_ref=result.get("result_ref", {}),
        )
        return result

    def execute_offline_test(self) -> dict[str, Any]:
        if self.workflow.state is not WorkflowState.OFFLINE_TEST_APPROVED:
            raise ApprovalRequired(
                "offline-test authorization is required before tool execution"
            )
        from .event_timing import require_executable_timing
        require_executable_timing(self.workflow.manifest['test_spec'])
        self.workflow.consume_approval(ApprovalAction.OFFLINE_TEST)
        compile_result = self.workflow.manifest.get("compile") or {}
        try:
            result = self.backend.run_offline_test(
                test_spec=self.workflow.manifest["test_spec"],
                compiled_artifact_sha256=compile_result.get("artifact_sha256"),
                **self._project_args(),
            )
        except Exception as exc:
            self.workflow.record_offline_test_result(
                succeeded=False,
                raw_data_collected=False,
                result_ref=self._backend_error_ref("offline_test", exc),
            )
            raise
        self.workflow.record_offline_test_result(
            succeeded=bool(result["succeeded"]),
            raw_data_collected=bool(result["raw_data_collected"]),
            result_ref=result.get("result_ref", {}),
        )
        return result

    def execute_runtime(self, *, acquisition_context=None) -> dict[str, Any]:
        if self.workflow.state is not WorkflowState.RUNTIME_APPROVED:
            raise ApprovalRequired(
                "explicit per-action Runtime approval is required before rack discovery or start"
            )
        from .native_acquisition import MODE, native_channels, validate_grounding
        spec=self.workflow.manifest['test_spec']
        from .event_timing import require_executable_timing
        require_executable_timing(spec)
        native=spec.get('runtime_capture',{}).get('acquisition_mode')==MODE
        options={}
        if native:
            if not isinstance(acquisition_context,dict) or set(acquisition_context)!={'run_id','attempt_id'} or acquisition_context['run_id']!=self.workflow.manifest['workflow_id'] or not isinstance(acquisition_context['attempt_id'],str) or not acquisition_context['attempt_id']:
                raise ValueError('Native capture requires the current workflow/attempt context before rack discovery')
            project=self.workflow.manifest['project']
            hashes={project['source_sha256'],project['working_sha256'],*[r['sha256'] for r in self.workflow.manifest['evidence']['grounding']['refs']]}
            validate_grounding(native_channels(spec['measurement_channels']),hashes)
            options['acquisition_context']=dict(acquisition_context)
        rack_snapshot = self.backend.refresh_racks(ApprovalAction.RUNTIME.value)
        authorization = self.workflow.consume_approval(
            ApprovalAction.RUNTIME, rack_snapshot=rack_snapshot
        )
        selected_rack = int(rack_snapshot["selected_rack"])
        compile_result = self.workflow.manifest.get("compile") or {}
        try:
            result = self.backend.run_runtime(
                rack=selected_rack,
                test_spec=self.workflow.manifest["test_spec"],
                compiled_artifact_sha256=compile_result.get("artifact_sha256"),
                authorization=authorization,
                **options,
                **self._project_args(),
            )
        except Exception as exc:
            self.workflow.record_runtime_result(
                run_started=False,
                stopped=False,
                raw_data_collected=False,
                result_ref=self._backend_error_ref("runtime", exc),
                safe_completion=False,
            )
            raise
        self.workflow.record_runtime_result(
            run_started=bool(result["run_started"]),
            stopped=bool(result["stopped"]),
            raw_data_collected=bool(result["raw_data_collected"]),
            result_ref=result.get("result_ref", {}),
            safe_completion=bool(
                result.get(
                    "safe_completion",
                    result["run_started"]
                    and result["stopped"]
                    and result["raw_data_collected"],
                )
            ),
        )
        return result
