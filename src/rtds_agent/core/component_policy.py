"""Operator-authored project component policy; no API writes or enables it."""
import json
from rtds_agent.safety import ToolSafetyError, sha256_file
from rtds_agent.settings import within
from rtds_agent.input_contracts import validate

POLICY_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["allowed_components", "denied_components", "allowed_parameters", "structural_edits"],
    "properties": {
        "allowed_components": {"type": "array", "maxItems": 500, "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
        "denied_components": {"type": "array", "maxItems": 500, "uniqueItems": True, "items": {"type": "string", "minLength": 1}},
        "allowed_parameters": {"type": "object", "maxProperties": 500, "additionalProperties": {"type": "array", "uniqueItems": True, "maxItems": 500, "items": {"type": "string", "minLength": 1}}},
        "structural_edits": {"type": "boolean"}}}


def read_component_policy(source):
    path = source.parent / "rtds-component-policy.json"
    default = {"allowed_components": [], "denied_components": [], "allowed_parameters": {}, "structural_edits": False}
    if not path.exists():
        return {"policy": default, "path": str(path), "sha256": None, "status": "absent_default_deny"}
    if path.is_symlink() or path.is_junction() or not within(path, source.parent) or path.stat().st_size > 100000:
        raise ToolSafetyError("Invalid project component policy file")
    raw = path.read_bytes()
    from rtds_agent.assessment import _pairs
    value = json.loads(raw, object_pairs_hook=_pairs)
    validate(value, POLICY_SCHEMA)
    import hashlib
    digest = hashlib.sha256(raw).hexdigest()
    if sha256_file(path) != digest:
        raise ToolSafetyError("Component policy changed while reading")
    return {"policy": value, "path": str(path), "sha256": digest, "status": "present"}


def authorize(policy, component_type, parameter=None):
    rules = policy["policy"]
    if not rules["structural_edits"] or component_type not in rules["allowed_components"] or component_type in rules["denied_components"]:
        raise ToolSafetyError("Project component policy denies this edit")
    if parameter is not None and parameter not in rules["allowed_parameters"].get(component_type, []):
        raise ToolSafetyError("Project component policy denies this parameter")
