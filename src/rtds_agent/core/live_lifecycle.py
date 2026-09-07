"""Bounded state observation and non-forced cleanup of an owned SDK case."""
from __future__ import annotations

import os


def _normal(path):
    return os.path.normcase(os.path.abspath(str(path)))


def claim_case(case, working_copy):
    """Called only after an absent-path check and a successful open."""
    identity = case.caseid
    if type(identity) is not int or identity < 0 or _normal(case.file) != _normal(working_copy):
        raise ValueError("Opened case ownership does not match the isolated working copy")
    return identity


def require_absent_case(app, working_copy):
    observed = app._get_case_named(str(working_copy), False)
    if observed is not None and (type(observed) is not int or observed != -1):
        raise ValueError("Working copy is already open or absence is unresolved")


def assert_owned_case(app, case, working_copy, identity):
    if identity is None or claim_case(case, working_copy) != identity:
        raise ValueError("Owned case identity changed")
    # The installed get_case() wrapper caches handles and suppresses RSCADError.
    # Use its connected lookup directly so a failed remote read is not absence.
    observed = app._get_case_named(str(working_copy), False)
    if type(observed) is not int or observed != identity:
        raise ValueError("Current remote case does not match the owned identity")


def close_owned_case(app, case, working_copy, identity):
    assert_owned_case(app, case, working_copy, identity)
    if str(case.state.run_state).lower() != "stopped":
        raise ValueError("Refusing to close a case without confirmed stopped state")
    if case.state.modified is not False:
        raise ValueError("Refusing to close a modified case or force-discard its changes")
    returned = case.close(force=False)
    if returned is not True:
        raise ValueError("Non-forced case close did not return True")
    remaining = app._get_case_named(str(working_copy), False)
    if remaining is not None and (type(remaining) is not int or remaining != -1):
        raise ValueError("Closed case absence was not confirmed")
    return {"case_id": identity, "close_return_value": True,
            "case_absence_confirmed": True, "force": False}


def observe_state(case, expected, sleeper, *, attempts=121, interval=0.25):
    """At most 30 seconds of controller waits; no simulator-time claim."""
    observations = []
    for index in range(attempts):
        state = str(case.state.run_state).lower()
        observations.append(state)
        if state == expected:
            break
        if state not in {"stopped", "running", "downloading"}:
            break
        if index + 1 < attempts:
            sleeper(interval)
    return observations
