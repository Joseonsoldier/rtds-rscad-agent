"""Packaged JSON Schema is the source of truth for MCP and direct-call validation."""
from importlib.resources import files
import json
import math
from typing import Annotated
from jsonschema import Draft202012Validator
from pydantic import BeforeValidator, WithJsonSchema


def schema(name):
    return json.loads(files("rtds_agent").joinpath("schemas", name).read_text(encoding="utf-8"))


def validate(value, contract):
    if not isinstance(value, dict):
        raise ValueError("Request must be a structured object")
    def supported_numbers(item):
        if isinstance(item, dict):
            for child in item.values(): supported_numbers(child)
        elif isinstance(item, list):
            for child in item: supported_numbers(child)
        elif type(item) in (int, float):
            try:
                if not math.isfinite(item): raise ValueError("Non-finite numeric input")
            except OverflowError as exc:
                raise ValueError("Numeric input exceeds the supported finite range") from exc
    supported_numbers(value)
    try:
        encoded = json.dumps(value, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError("Request must contain finite JSON values") from exc
    if len(encoded) > 100000:
        raise ValueError("Request exceeds 100,000 characters")
    errors = sorted(Draft202012Validator(contract).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        e = errors[0]
        raise ValueError("Invalid request at " + "/".join(map(str, e.path)) + ": " + e.message)
    return value


PATCH_SCHEMA = schema("parameter_patch_batch.schema.json")
RUNTIME_SCHEMA = schema("runtime_test_spec.schema.json")
OFFLINE_SCHEMA = schema("offline_test_spec.schema.json")
TEST_SCHEMA = {"title": "Prepared Runtime or offline FSAT test specification", "oneOf": [RUNTIME_SCHEMA, OFFLINE_SCHEMA]}


def validate_patch(value):
    return validate(value, PATCH_SCHEMA)


def validate_test_spec(value):
    validate(value, TEST_SCHEMA)
    if value.get("runtime_required") is True:
        from .core.runtime_backend import validate_runtime_test_spec
        validate_runtime_test_spec(value)
    elif value["scan"]["start_frequency_hz"] > value["scan"]["end_frequency_hz"]:
        raise ValueError("Scan start must not exceed scan end")
    return value


PatchBatchRequest = Annotated[dict, BeforeValidator(validate_patch), WithJsonSchema(PATCH_SCHEMA)]
TestSpecification = Annotated[dict, BeforeValidator(validate_test_spec), WithJsonSchema(TEST_SCHEMA)]


SELECTOR_SCHEMA = schema("selector_preview.schema.json")


def validate_selector(value):
    return validate(value, SELECTOR_SCHEMA)


SelectorRequest = Annotated[dict, BeforeValidator(validate_selector), WithJsonSchema(SELECTOR_SCHEMA)]
