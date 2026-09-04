"""Validate packaged schemas without ever fetching remote references."""
import json
from pathlib import Path
from urllib.parse import urljoin
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.exceptions import NoSuchResource


def _deny_remote(uri):
    raise NoSuchResource(ref=uri)


def validate_workflow(value):
    root = Path(__file__).parent / "schemas"
    registry = Registry(retrieve=_deny_remote)
    schemas = {}
    for path in root.glob("*.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[path.name] = schema
        resource = Resource.from_contents(schema)
        registry = registry.with_resource(schema["$id"], resource)
        registry = registry.with_resource(urljoin(schema["$id"], path.name), resource)
    Draft202012Validator(schemas["workflow_manifest.schema.json"], registry=registry).validate(value)
