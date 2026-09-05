"""Public installed component catalog facade; no native API invocation."""
from typing import Any
from .core import component_catalog as catalog


def search_component_catalog(query: str, limit: int = 20, offset: int = 0,
                             snapshot_id: str | None = None) -> dict[str, Any]:
    """Search bounded installed component names/paths with a fresh definition snapshot."""
    return catalog.search_component_catalog(query,limit,offset,snapshot_id)


def get_component_schema(component_type: str, definition_id: str | None = None,
                          parameters: dict[str, str] | None = None, context: str = "subsystem:0",
                          snapshot_id: str | None = None) -> dict[str, Any]:
    """Read declared parameters, selectors and active ports; ambiguous names need a definition ID."""
    return catalog.get_component_schema(component_type,definition_id,parameters,context,snapshot_id)
