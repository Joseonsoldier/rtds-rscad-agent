from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence


class WorkflowError(RuntimeError):
    """Base error for a rejected workflow operation."""


class InvalidTransition(WorkflowError):
    pass


class ApprovalRequired(WorkflowError):
    pass


class ApprovalScopeMismatch(WorkflowError):
    pass


class SafetyViolation(WorkflowError):
    pass


class WorkflowState(str, Enum):
    CREATED = "created"
    INSPECTED = "inspected"
    GROUNDED = "grounded"
    STATIC_VALIDATED = "static_validated"
    AWAITING_COMPILE_APPROVAL = "awaiting_compile_approval"
    COMPILE_APPROVED = "compile_approved"
    COMPILED = "compiled"
    AWAITING_OFFLINE_TEST_APPROVAL = "awaiting_offline_test_approval"
    OFFLINE_TEST_APPROVED = "offline_test_approved"
    OFFLINE_TEST_COMPLETED = "offline_test_completed"
    AWAITING_RUNTIME_APPROVAL = "awaiting_runtime_approval"
    RUNTIME_APPROVED = "runtime_approved"
    RUNTIME_COMPLETED = "runtime_completed"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"


class ApprovalAction(str, Enum):
    COMPILE = "compile"
    OFFLINE_TEST = "offline_test"
    RUNTIME = "runtime_start_stop"
    RUNTIME_PARAMETER_WRITE = "runtime_parameter_write"
    HARDWARE_IO = "hardware_io_change"
    DEPLOYMENT_OR_RACK_CONFIGURATION = "deployment_or_rack_configuration_change"
    ORIGINAL_OVERWRITE = "original_overwrite"


RISK_LEVELS = {
    ApprovalAction.COMPILE: "L2",
    ApprovalAction.OFFLINE_TEST: "L2",
    ApprovalAction.RUNTIME_PARAMETER_WRITE: "L3",
    ApprovalAction.RUNTIME: "L4",
    ApprovalAction.HARDWARE_IO: "L4",
    ApprovalAction.DEPLOYMENT_OR_RACK_CONFIGURATION: "L4",
    ApprovalAction.ORIGINAL_OVERWRITE: "L4",
}

# Closed allow-list: future action additions cannot silently become standing-authorized.
STANDING_AUTHORIZATION_ACTIONS = frozenset(
    {ApprovalAction.COMPILE, ApprovalAction.OFFLINE_TEST}
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evidence_ref(path: str | Path) -> dict[str, Any]:
    target = Path(path).resolve()
    return {"path": str(target), "sha256": sha256_file(target), "size": target.stat().st_size}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class Workflow:
    """JSON-serializable authorization and evidence state machine.

    Standing authorization is limited to compile and offline test. Every action
    still receives a fresh, hash-bound, single-use approval record.
    """

    def __init__(self, manifest: Mapping[str, Any]):
        self.manifest: dict[str, Any] = deepcopy(dict(manifest))
        self.manifest.setdefault("standing_authorizations", [])
        self.manifest.setdefault("offline_test", None)

    @classmethod
    def create(
        cls,
        *,
        workflow_id: str,
        project: Mapping[str, Any],
        test_spec: Mapping[str, Any],
        created_at: str | None = None,
    ) -> "Workflow":
        required = {
            "source_path", "source_sha256", "working_copy", "working_sha256",
            "working_root", "vendor_source_root",
        }
        missing = sorted(required - set(project))
        if missing:
            raise SafetyViolation(f"missing project safety fields: {missing}")
        source = Path(str(project["source_path"])).resolve()
        working = Path(str(project["working_copy"])).resolve()
        working_root = Path(str(project["working_root"])).resolve()
        vendor_root = Path(str(project["vendor_source_root"])).resolve()
        if source == working:
            raise SafetyViolation("source and working copy must be different paths")
        if not _is_relative_to(working, working_root):
            raise SafetyViolation("working copy is outside the approved working root")
        if _is_relative_to(working, vendor_root):
            raise SafetyViolation("working copy may not be inside the vendor source tree")
        for key in ("source_sha256", "working_sha256"):
            value = str(project[key])
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value.lower()):
                raise SafetyViolation(f"{key} is not a SHA-256 digest")
        project_record = deepcopy(dict(project))
        input_files = project_record.get("input_files", [])
        if not isinstance(input_files, list):
            raise SafetyViolation("input_files must be a list")
        canonical_inputs: list[dict[str, str]] = []
        seen_inputs: set[str] = set()
        for index, item in enumerate(input_files):
            if not isinstance(item, Mapping):
                raise SafetyViolation(f"input_files[{index}] must be an object")
            if "path" not in item or "sha256" not in item:
                raise SafetyViolation(
                    f"input_files[{index}] requires path and sha256"
                )
            input_path = Path(str(item["path"])).resolve()
            digest = str(item["sha256"]).lower()
            if not _is_relative_to(input_path, working.parent):
                raise SafetyViolation(
                    f"input_files[{index}] is outside the working directory"
                )
            if input_path == working:
                raise SafetyViolation(
                    f"input_files[{index}] duplicates the working copy"
                )
            normalized_path = str(input_path).lower()
            if normalized_path in seen_inputs:
                raise SafetyViolation(f"duplicate input file: {input_path}")
            if not input_path.is_file():
                raise SafetyViolation(f"input file does not exist: {input_path}")
            if len(digest) != 64 or any(
                c not in "0123456789abcdef" for c in digest
            ):
                raise SafetyViolation(
                    f"input_files[{index}].sha256 is not a SHA-256 digest"
                )
            if sha256_file(input_path) != digest:
                raise SafetyViolation(f"input file hash mismatch: {input_path}")
            seen_inputs.add(normalized_path)
            canonical_inputs.append({"path": str(input_path), "sha256": digest})
        if canonical_inputs:
            canonical_inputs.sort(key=lambda item: item["path"].lower())
            bundle_sha256 = sha256_json(canonical_inputs)
            supplied_bundle = project_record.get("input_bundle_sha256")
            if (
                supplied_bundle is not None
                and str(supplied_bundle).lower() != bundle_sha256
            ):
                raise SafetyViolation(
                    "input_bundle_sha256 does not match input_files"
                )
            project_record["input_files"] = canonical_inputs
            project_record["input_bundle_sha256"] = bundle_sha256
        else:
            project_record.pop("input_files", None)
            project_record.pop("input_bundle_sha256", None)
        discovery_sha256 = project_record.get(
            "companion_discovery_sha256"
        )
        if discovery_sha256 is not None:
            value = str(discovery_sha256).lower()
            if len(value) != 64 or any(
                character not in "0123456789abcdef"
                for character in value
            ):
                raise SafetyViolation(
                    "companion_discovery_sha256 is not a SHA-256 digest"
                )
            project_record["companion_discovery_sha256"] = value
        timestamp = created_at or now_iso()
        return cls({
            "schema_version": "1.0",
            "workflow_id": workflow_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "state": WorkflowState.CREATED.value,
            "project": project_record,
            "test_spec": dict(test_spec),
            "test_spec_sha256": sha256_json(test_spec),
            "evidence": {},
            "standing_authorizations": [],
            "approval_requests": [],
            "approvals": [],
            "compile": None,
            "offline_test": None,
            "runtime": None,
            "verdict": None,
            "events": [{
                "at": timestamp, "event": "workflow_created",
                "from": None, "to": WorkflowState.CREATED.value,
            }],
        })

    @property
    def state(self) -> WorkflowState:
        return WorkflowState(self.manifest["state"])

    def _transition(
        self,
        expected: WorkflowState | tuple[WorkflowState, ...],
        target: WorkflowState,
        event: str,
        details: Mapping[str, Any] | None = None,
        at: str | None = None,
    ) -> None:
        allowed = (expected,) if isinstance(expected, WorkflowState) else expected
        if self.state not in allowed:
            names = ", ".join(item.value for item in allowed)
            raise InvalidTransition(f"{event} requires state [{names}], current={self.state.value}")
        timestamp = at or now_iso()
        previous = self.state
        self.manifest["state"] = target.value
        self.manifest["updated_at"] = timestamp
        record: dict[str, Any] = {
            "at": timestamp, "event": event,
            "from": previous.value, "to": target.value,
        }
        if details:
            record["details"] = deepcopy(dict(details))
        self.manifest["events"].append(record)

    def record_stage(
        self,
        stage: str,
        *,
        passed: bool,
        evidence: list[Mapping[str, Any]],
        at: str | None = None,
    ) -> None:
        mapping = {
            "inspection": (WorkflowState.CREATED, WorkflowState.INSPECTED),
            "grounding": (WorkflowState.INSPECTED, WorkflowState.GROUNDED),
            "static_validation": (WorkflowState.GROUNDED, WorkflowState.STATIC_VALIDATED),
        }
        if stage not in mapping:
            raise WorkflowError(f"unknown stage: {stage}")
        expected, target = mapping[stage]
        refs = [deepcopy(dict(item)) for item in evidence]
        self.manifest["evidence"][stage] = {"passed": bool(passed), "refs": refs}
        if not passed:
            self._transition(expected, WorkflowState.FAILED, f"{stage}_failed", {"evidence": refs}, at)
            return
        self._transition(expected, target, f"{stage}_passed", {"evidence": refs}, at)

    def add_standing_authorization(
        self,
        actions: Sequence[ApprovalAction],
        *,
        actor: str,
        source: str,
        effective_at: str | None = None,
        authorization_id: str | None = None,
    ) -> str:
        normalized = tuple(dict.fromkeys(actions))
        if not normalized:
            raise SafetyViolation("standing authorization requires at least one action")
        rejected = [action for action in normalized if action not in STANDING_AUTHORIZATION_ACTIONS]
        if rejected:
            names = ", ".join(action.value for action in rejected)
            raise SafetyViolation(f"standing authorization is forbidden for: {names}")
        timestamp = effective_at or now_iso()
        identifier = authorization_id or str(uuid.uuid4())
        record = {
            "authorization_id": identifier,
            "actions": [action.value for action in normalized],
            "risk_levels": sorted({RISK_LEVELS[action] for action in normalized}),
            "actor": actor,
            "source": source,
            "effective_at": timestamp,
            "status": "active",
            "scope_policy": "fresh_hash_bound_single_use_approval_per_action",
        }
        self.manifest["standing_authorizations"].append(record)
        self.manifest["events"].append({
            "at": timestamp,
            "event": "limited_standing_authorization_added",
            "from": self.state.value,
            "to": self.state.value,
            "details": {"authorization_id": identifier, "actions": record["actions"]},
        })
        self.manifest["updated_at"] = timestamp
        return identifier

    def standing_authorization_for(self, action: ApprovalAction) -> dict[str, Any] | None:
        if action not in STANDING_AUTHORIZATION_ACTIONS:
            return None
        return next((
            item for item in reversed(self.manifest["standing_authorizations"])
            if item.get("status") == "active" and action.value in item.get("actions", [])
        ), None)

    def _scope_for(self, action: ApprovalAction) -> dict[str, Any]:
        scope = {
            "workflow_id": self.manifest["workflow_id"],
            "working_copy_sha256": self.manifest["project"]["working_sha256"],
            "source_sha256": self.manifest["project"]["source_sha256"],
            "test_spec_sha256": self.manifest["test_spec_sha256"],
        }
        input_bundle_sha256 = self.manifest["project"].get(
            "input_bundle_sha256"
        )
        if input_bundle_sha256:
            scope["input_bundle_sha256"] = input_bundle_sha256
        companion_discovery_sha256 = self.manifest["project"].get(
            "companion_discovery_sha256"
        )
        if companion_discovery_sha256:
            scope["companion_discovery_sha256"] = (
                companion_discovery_sha256
            )
        compile_result = self.manifest.get("compile")
        if action is ApprovalAction.OFFLINE_TEST and compile_result and compile_result.get("succeeded"):
            scope["compiled_artifact_sha256"] = compile_result["artifact_sha256"]
        if action is ApprovalAction.RUNTIME:
            if not compile_result or not compile_result.get("succeeded"):
                raise InvalidTransition("Runtime approval requires a successful compile")
            scope.update({
                "compiled_artifact_sha256": compile_result["artifact_sha256"],
                "compiled_rack": compile_result["selected_rack"],
            })
        return scope

    def request_approval(
        self,
        action: ApprovalAction,
        *,
        reason: str,
        at: str | None = None,
        request_id: str | None = None,
    ) -> str:
        transitions = {
            ApprovalAction.COMPILE: (
                WorkflowState.STATIC_VALIDATED, WorkflowState.AWAITING_COMPILE_APPROVAL
            ),
            ApprovalAction.OFFLINE_TEST: (
                (WorkflowState.STATIC_VALIDATED, WorkflowState.COMPILED),
                WorkflowState.AWAITING_OFFLINE_TEST_APPROVAL,
            ),
            ApprovalAction.RUNTIME: (
                WorkflowState.COMPILED, WorkflowState.AWAITING_RUNTIME_APPROVAL
            ),
        }
        if action not in transitions:
            raise WorkflowError(f"{action.value} requires its own privileged-action workflow")
        expected, target = transitions[action]
        identifier = request_id or str(uuid.uuid4())
        timestamp = at or now_iso()
        request = {
            "request_id": identifier,
            "action": action.value,
            "risk_level": RISK_LEVELS[action],
            "reason": reason,
            "scope": self._scope_for(action),
            "created_at": timestamp,
            "status": "pending",
        }
        self.manifest["approval_requests"].append(request)
        self._transition(
            expected, target, f"{action.value}_approval_requested",
            {"request_id": identifier}, timestamp,
        )
        standing = self.standing_authorization_for(action)
        if standing is not None:
            self.grant_approval(
                action,
                actor=str(standing["actor"]),
                source=f"standing authorization {standing['authorization_id']}: {standing['source']}",
                at=timestamp,
            )
        return identifier

    def grant_approval(
        self,
        action: ApprovalAction,
        *,
        actor: str,
        source: str,
        at: str | None = None,
        approval_id: str | None = None,
    ) -> str:
        transitions = {
            ApprovalAction.COMPILE: (
                WorkflowState.AWAITING_COMPILE_APPROVAL, WorkflowState.COMPILE_APPROVED
            ),
            ApprovalAction.OFFLINE_TEST: (
                WorkflowState.AWAITING_OFFLINE_TEST_APPROVAL,
                WorkflowState.OFFLINE_TEST_APPROVED,
            ),
            ApprovalAction.RUNTIME: (
                WorkflowState.AWAITING_RUNTIME_APPROVAL, WorkflowState.RUNTIME_APPROVED
            ),
        }
        if action not in transitions:
            raise WorkflowError(f"{action.value} requires its own privileged-action workflow")
        expected, target = transitions[action]
        pending = next((
            item for item in reversed(self.manifest["approval_requests"])
            if item["action"] == action.value and item["status"] == "pending"
        ), None)
        if pending is None:
            raise ApprovalRequired(f"no pending approval request for {action.value}")
        pending["status"] = "granted"
        identifier = approval_id or str(uuid.uuid4())
        timestamp = at or now_iso()
        self.manifest["approvals"].append({
            "approval_id": identifier,
            "request_id": pending["request_id"],
            "action": action.value,
            "risk_level": RISK_LEVELS[action],
            "actor": actor,
            "source": source,
            "scope": deepcopy(pending["scope"]),
            "granted_at": timestamp,
            "single_use": True,
            "status": "granted",
            "consumed_at": None,
            "rack_snapshot": None,
        })
        self._transition(
            expected, target, f"{action.value}_approval_granted",
            {"approval_id": identifier}, timestamp,
        )
        return identifier

    def _current_approval(self, action: ApprovalAction) -> dict[str, Any]:
        approval = next((
            item for item in reversed(self.manifest["approvals"])
            if item["action"] == action.value and item["status"] == "granted"
        ), None)
        if approval is None:
            raise ApprovalRequired(f"unconsumed approval required for {action.value}")
        return approval

    def consume_approval(
        self,
        action: ApprovalAction,
        *,
        rack_snapshot: Mapping[str, Any] | None = None,
        at: str | None = None,
    ) -> dict[str, Any]:
        expected = {
            ApprovalAction.COMPILE: WorkflowState.COMPILE_APPROVED,
            ApprovalAction.OFFLINE_TEST: WorkflowState.OFFLINE_TEST_APPROVED,
            ApprovalAction.RUNTIME: WorkflowState.RUNTIME_APPROVED,
        }.get(action)
        if expected is None:
            raise WorkflowError(f"unsupported workflow approval: {action.value}")
        if self.state is not expected:
            raise ApprovalRequired(f"{action.value} is not approved in state {self.state.value}")
        approval = self._current_approval(action)
        expected_scope = self._scope_for(action)
        if approval["scope"] != expected_scope:
            raise ApprovalScopeMismatch(f"{action.value} approval scope no longer matches workflow")

        selected: int | None = None
        if action in {ApprovalAction.COMPILE, ApprovalAction.RUNTIME}:
            if rack_snapshot is None:
                raise SafetyViolation("compile and Runtime require an immediate rack snapshot")
            available = [int(item) for item in rack_snapshot.get("available_racks", [])]
            selected_value = rack_snapshot.get("selected_rack")
            source = rack_snapshot.get("source")
            if source not in {"live_query_immediately_before_action", "historical_verified_execution"}:
                raise SafetyViolation("rack snapshot must come from an immediate live query or verified historical evidence")
            if selected_value is None or int(selected_value) not in available:
                raise SafetyViolation("selected rack is not currently available")
            selected = int(selected_value)
            if action is ApprovalAction.RUNTIME and selected != int(expected_scope["compiled_rack"]):
                raise SafetyViolation("Runtime rack does not match the rack used to compile the artifact")
        elif rack_snapshot is not None:
            raise SafetyViolation("offline test must not select or query a rack")

        timestamp = at or now_iso()
        approval["status"] = "consumed"
        approval["consumed_at"] = timestamp
        approval["rack_snapshot"] = (
            deepcopy(dict(rack_snapshot)) if rack_snapshot is not None else None
        )
        details: dict[str, Any] = {"approval_id": approval["approval_id"]}
        if selected is not None:
            details["selected_rack"] = selected
        self.manifest["events"].append({
            "at": timestamp,
            "event": f"{action.value}_approval_consumed",
            "from": self.state.value,
            "to": self.state.value,
            "details": details,
        })
        self.manifest["updated_at"] = timestamp
        return approval

    def record_compile_result(
        self,
        *,
        succeeded: bool,
        artifact_sha256: str | None,
        result_ref: Mapping[str, Any],
        at: str | None = None,
    ) -> None:
        approval = next((
            item for item in reversed(self.manifest["approvals"])
            if item["action"] == ApprovalAction.COMPILE.value
            and item["status"] == "consumed"
        ), None)
        if self.state is not WorkflowState.COMPILE_APPROVED or approval is None:
            raise ApprovalRequired("a consumed compile approval is required before recording compile")
        if succeeded and (not artifact_sha256 or len(artifact_sha256) != 64):
            raise WorkflowError("successful compile requires an artifact SHA-256")
        self.manifest["compile"] = {
            "succeeded": bool(succeeded),
            "artifact_sha256": artifact_sha256,
            "selected_rack": int(approval["rack_snapshot"]["selected_rack"]),
            "result_ref": deepcopy(dict(result_ref)),
        }
        target = WorkflowState.COMPILED if succeeded else WorkflowState.FAILED
        self._transition(
            WorkflowState.COMPILE_APPROVED, target,
            "compile_completed", {"succeeded": succeeded}, at,
        )

    def record_offline_test_result(
        self,
        *,
        succeeded: bool,
        raw_data_collected: bool,
        result_ref: Mapping[str, Any],
        at: str | None = None,
    ) -> None:
        approval = next((
            item for item in reversed(self.manifest["approvals"])
            if item["action"] == ApprovalAction.OFFLINE_TEST.value
            and item["status"] == "consumed"
        ), None)
        if self.state is not WorkflowState.OFFLINE_TEST_APPROVED or approval is None:
            raise ApprovalRequired("a consumed offline-test approval is required before recording its result")
        completed = bool(succeeded and raw_data_collected)
        self.manifest["offline_test"] = {
            "succeeded": bool(succeeded),
            "raw_data_collected": bool(raw_data_collected),
            "result_ref": deepcopy(dict(result_ref)),
        }
        target = WorkflowState.OFFLINE_TEST_COMPLETED if completed else WorkflowState.FAILED
        self._transition(
            WorkflowState.OFFLINE_TEST_APPROVED, target,
            "offline_test_completed", {"safe_completion": completed}, at,
        )

    def record_runtime_result(
        self,
        *,
        run_started: bool,
        stopped: bool,
        raw_data_collected: bool,
        result_ref: Mapping[str, Any],
        safe_completion: bool | None = None,
        at: str | None = None,
    ) -> None:
        approval = next((
            item for item in reversed(self.manifest["approvals"])
            if item["action"] == ApprovalAction.RUNTIME.value
            and item["status"] == "consumed"
        ), None)
        if self.state is not WorkflowState.RUNTIME_APPROVED or approval is None:
            raise ApprovalRequired("a consumed Runtime approval is required before recording Runtime")
        physical_completion = bool(
            run_started and stopped and raw_data_collected
        )
        completed = bool(
            physical_completion
            and (
                safe_completion is None
                or safe_completion is True
            )
        )
        self.manifest["runtime"] = {
            "run_started": bool(run_started),
            "stopped": bool(stopped),
            "raw_data_collected": bool(raw_data_collected),
            "safe_completion": completed,
            "selected_rack": int(approval["rack_snapshot"]["selected_rack"]),
            "result_ref": deepcopy(dict(result_ref)),
        }
        target = WorkflowState.RUNTIME_COMPLETED if completed else WorkflowState.FAILED
        self._transition(
            WorkflowState.RUNTIME_APPROVED, target,
            "runtime_completed", {"safe_completion": completed}, at,
        )

    def record_verdict(
        self,
        *,
        passed: bool,
        result_ref: Mapping[str, Any],
        notes: list[str] | None = None,
        at: str | None = None,
    ) -> None:
        self.manifest["verdict"] = {
            "passed": bool(passed),
            "result_ref": deepcopy(dict(result_ref)),
            "notes": list(notes or []),
        }
        target = WorkflowState.VERIFIED if passed else WorkflowState.FAILED
        self._transition(
            (WorkflowState.RUNTIME_COMPLETED, WorkflowState.OFFLINE_TEST_COMPLETED),
            target, "verdict_recorded", {"passed": passed}, at,
        )

    def has_authorization(self, action: ApprovalAction) -> bool:
        return any(item["action"] == action.value for item in self.manifest["approvals"])

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return target
