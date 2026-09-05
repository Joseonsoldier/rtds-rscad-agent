"""Numeric-only working-copy edits; never modifies source projects."""
from typing import Any
from .input_contracts import PatchBatchRequest, validate_patch
from .core.structured_patch import apply_parameter_patch_request, build_single_parameter_request


def apply_parameter_patch(source_project: str, source_sha256: str, component_id: int,
                          context: str, component_type: str, parameter: str,
                          expected_old_value: str, new_value: str,
                          project_label: str | None = None, rscad_version: str = "2.7.3",
                          parameter_catalog_snapshot_id: str | None = None) -> dict[str, Any]:
    """Create a new copy with one exact REAL/INTEGER edit using local definition evidence.

    Requires UUID/context/type/old value and source hash. No live calls.
    """
    request = build_single_parameter_request(source_project, component_id, component_type, parameter,
        expected_old_value, new_value, context=context, project_label=project_label,
        rscad_version=rscad_version, expected_source_sha256=source_sha256,
        parameter_catalog_snapshot_id=parameter_catalog_snapshot_id)
    return apply_parameter_patch_batch(request)


def apply_parameter_patch_batch(request: PatchBatchRequest) -> dict[str, Any]:
    """Atomically publish an isolated copy after 1–20 exact numeric edits and complete verification.

    Each operation requires context, UUID, type, old/new string values. Original
    project/companions and non-DFX members remain unchanged. No live calls.
    """
    validate_patch(request)
    return apply_parameter_patch_request(request)
