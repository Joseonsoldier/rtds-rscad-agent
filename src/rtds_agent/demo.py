"""A synthetic state-machine demonstration. This is not an RTDS simulation."""
from pathlib import Path
import tempfile
from .core.state_machine import Workflow, ApprovalAction, sha256_file
from .core.orchestrator import ApprovalGatedOrchestrator
from .core.mock_backend import MockBackend


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="rtds-agent-demo-") as directory:
        root = Path(directory)
        source = root / "source/synthetic.txt"
        working = root / "data/projects/demo/working/synthetic.txt"
        source.parent.mkdir(parents=True)
        working.parent.mkdir(parents=True)
        source.write_text("synthetic fixture; not an RSCAD case\n", encoding="utf-8")
        working.write_bytes(source.read_bytes())
        digest = sha256_file(source)
        workflow = Workflow.create(workflow_id="synthetic-demo", project={
            "source_path": str(source), "source_sha256": digest,
            "working_copy": str(working), "working_sha256": digest,
            "working_root": str(root / "data/projects"), "vendor_source_root": str(source.parent)},
            test_spec={"test_id": "synthetic-only", "runtime_required": True})
        for stage in ("inspection", "grounding", "static_validation"):
            workflow.record_stage(stage, passed=True, evidence=[{"synthetic": True}])
        backend = MockBackend()
        orchestrator = ApprovalGatedOrchestrator(workflow, backend)
        for action, execute in ((ApprovalAction.COMPILE, orchestrator.execute_compile),
                                (ApprovalAction.RUNTIME, orchestrator.execute_runtime)):
            workflow.request_approval(action, reason="Synthetic in-memory demonstration")
            workflow.grant_approval(action, actor="mock", source="synthetic demo only")
            execute()
        return {"mode": "synthetic_mock_only", "state": workflow.state.value,
                "live_calls_made": False, "network_called": False, "policy_changed": False,
                "operations": [call["call"] for call in backend.call_log],
                "engineering_verdict": "not_evaluated"}
