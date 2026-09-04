"""Numeric-only working-copy edits; never modifies source projects."""
from typing import Any
from .core.structured_patch import apply_parameter_patch_request, build_single_parameter_request


def apply_parameter_patch(source_project: str, source_sha256: str, component_id: int,
                          context: str, component_type: str, parameter: str,
                          expected_old_value: str, new_value: str,
                          project_label: str | None = None, rscad_version: str = "2.7.3") -> dict[str, Any]:
    """Create a new copy with one exact REAL/INTEGER edit using local definition evidence.

    Requires UUID/context/type/old value and source hash. No live calls.
    """
    request = build_single_parameter_request(source_project, component_id, component_type, parameter,
        expected_old_value, new_value, context=context, project_label=project_label,
        rscad_version=rscad_version, expected_source_sha256=source_sha256)
    return apply_parameter_patch_request(request)
