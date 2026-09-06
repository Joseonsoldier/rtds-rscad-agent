"""Exact live control scope checks, called only inside authorized Runtime execution."""
import os
from pathlib import Path
from .state_machine import sha256_file


def bind_live_control(case, working_copy, source_sha256, action):
    """A stored UUID is insufficient: lookup must be unique by type/name/page."""
    normalize=lambda p:os.path.normcase(os.path.abspath(str(p)))
    if normalize(case.file)!=normalize(working_copy) or sha256_file(Path(working_copy))!=source_sha256:
        raise ValueError("Runtime binding case/file hash changed")
    page=action.get("object_subpage")
    if not isinstance(page,str) or not page.strip():raise ValueError("Runtime binding requires an exact live object_subpage")
    candidates=case.runtime.get_objects(action["object_type"],action["object_name"])
    if not isinstance(candidates,list) or len(candidates)!=1:
        raise ValueError("Runtime type/name lookup is missing or ambiguous")
    handle=candidates[0]
    if type(handle.unique_id) is not int or handle.unique_id!=action["object_uuid"]:
        raise ValueError("Runtime lookup object ID mismatch")
    if handle.subtab!="Runtime" or handle.subpage!=page:
        raise ValueError("Runtime lookup subtab/subpage mismatch")
    # A second exact-ID lookup must agree; caches never supply authority for a
    # different page, case or type/name query.
    exact=case.runtime.get_object(action["object_uuid"])
    if exact is None or type(exact.unique_id) is not int or exact.unique_id!=handle.unique_id or exact.subtab!="Runtime" or exact.subpage!=page:
        raise ValueError("Runtime exact object lookup disagrees")
    return handle,{"case_sha256":source_sha256,"object_uuid":action["object_uuid"],"object_type":action["object_type"],
                   "object_name":action["object_name"],"object_subpage":page,"lookup_count":1,"identity_verified":True,
                   "value_verified":False,"basis":"current type/name and exact ID lookups; subtab/subpage readback"}
