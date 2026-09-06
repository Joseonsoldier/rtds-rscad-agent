"""Qualification checks before execution, grant creation or rack discovery."""
from collections.abc import Mapping

from .event_timing import require_executable_timing


def require_executable_spec(test_spec):
    require_executable_timing(test_spec)
    initialization = test_spec.get("loadflow_initialization", {"enabled": False})
    if not isinstance(initialization, Mapping) or initialization.get("enabled") is not False:
        raise ValueError(
            "Legacy Runtime loadflow_initialization is unsupported: the installed SDK "
            "takes frequency, not timeout, and initialization requires evidence and "
            "recompile before Runtime. Use read-only initialization inspection; no live calls made."
        )
