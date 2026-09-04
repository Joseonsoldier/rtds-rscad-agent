"""Installation-local operator opt-in. No MCP tool can change this policy."""
from contextlib import contextmanager
from pathlib import Path
import json
import os

from .settings import Settings
from .core.state_machine import now_iso, sha256_json

ALLOWED = {"compile", "offline_test", "runtime_start_stop", "runtime_controls"}


def policy_path(settings: Settings) -> Path:
    return settings.data_dir / "execution_policy.json"


def read_policy(settings: Settings) -> dict:
    path = policy_path(settings)
    if not path.is_file():
        return {"schema_version": 1, "status": "inactive", "actions": [], "allowed_racks": []}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or value.get("settings_sha256") != sha256_json(settings.as_dict())
            or not isinstance(value.get("actions"), list)
            or not set(value["actions"]).issubset(ALLOWED)
            or not isinstance(value.get("allowed_racks"), list)
            or any(type(r) is not int or r < 1 for r in value["allowed_racks"])):
        raise PermissionError("Execution policy is invalid or settings changed; reconfigure locally")
    return value


def configure_policy(settings: Settings, actions: list[str], racks: list[int], operator: str) -> dict:
    if not operator.strip() or not set(actions).issubset(ALLOWED):
        raise ValueError("An operator and supported actions are required")
    if actions and (not racks or any(type(r) is not int or r < 1 for r in racks)):
        raise ValueError("Opt-in requires at least one allowed positive rack number")
    if "runtime_controls" in actions and "runtime_start_stop" not in actions:
        raise ValueError("Runtime controls require Runtime start/stop permission")
    value = {"schema_version": 1, "status": "active" if actions else "inactive",
             "actions": sorted(set(actions)), "allowed_racks": sorted(set(racks)),
             "operator": operator.strip(), "configured_at": now_iso(),
             "settings_sha256": sha256_json(settings.as_dict()),
             "per_run_human_confirmation": False, "single_use_grants": True,
             "same_compile_rack": True, "readback_and_restore": True}
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = policy_path(settings)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return value


def require_action(settings: Settings, action: str, *, controls: bool = False) -> dict:
    value = read_policy(settings)
    if value.get("status") != "active" or action not in value["actions"] or not value["allowed_racks"]:
        raise PermissionError(f"{action} is not enabled by the local operator; no live calls made")
    if controls and "runtime_controls" not in value["actions"]:
        raise PermissionError("Runtime controls are not enabled by the local operator")
    return value


@contextmanager
def execution_lock(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "execution.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise PermissionError("Another execution or interrupted process holds execution.lock; inspect Runtime state before manual recovery") from None
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "started_at": now_iso()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        yield
    finally:
        path.unlink()
