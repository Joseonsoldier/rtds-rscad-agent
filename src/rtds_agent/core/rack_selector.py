"""Deterministic selection from caller-supplied available racks; no I/O."""
from typing import Iterable

def select_rack(available_racks: Iterable[int], configured_racks: Iterable[int], project_rack: int | None=None, preferred_rack: int | None=None) -> dict:
    available = sorted(set((int(value) for value in available_racks)))
    configured = sorted(set((int(value) for value in configured_racks)))
    if not available:
        return {'status': 'blocked_no_available_rack', 'selected_rack': None, 'available_racks': available, 'configured_racks': configured, 'reason': 'RSCAD FX reported no available rack.'}
    if preferred_rack is not None and preferred_rack in available:
        selected, reason = (preferred_rack, 'explicit preferred rack is currently available')
    elif project_rack is not None and project_rack in available:
        selected, reason = (project_rack, 'project-configured rack is currently available')
    else:
        selected, reason = (available[0], 'selected the lowest numbered currently available rack deterministically')
    return {'status': 'selected', 'selected_rack': selected, 'available_racks': available, 'configured_racks': configured, 'project_rack': project_rack, 'preferred_rack': preferred_rack, 'reason': reason}
