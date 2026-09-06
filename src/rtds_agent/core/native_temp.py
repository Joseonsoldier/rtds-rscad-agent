"""Prove that a new_case backing file appeared during this owned API call."""
from pathlib import Path
import re
import tempfile
import time
import zipfile

from ..safety import ToolSafetyError, sha256_file
from .topology_parser import parse_dfx_entities

NAME = re.compile(r"tempCaseFile[0-9]{1,20}\.rtfx")


def capture_temp_inventory():
    root = Path(tempfile.gettempdir()).absolute()
    if any(p.is_symlink() or p.is_junction() for p in (root,*root.parents)) or not root.is_dir():
        raise ToolSafetyError("Native temporary directory is linked or unavailable")
    names = [p.name for p in root.glob("tempCaseFile*.rtfx")]
    if len(names)>2000: raise ToolSafetyError("Native temporary inventory exceeds bounds")
    return {"directory":str(root),"existing_names":sorted(names),"started_ns":time.time_ns()}


def verify_new_temp(observed, inventory, returned_ns):
    """No arbitrary existing file, old temp, link, stale timestamp or nonempty model."""
    root = Path(inventory["directory"])
    path = Path(observed)
    if (not path.is_absolute() or path.parent != root or not NAME.fullmatch(path.name)
            or path.name in inventory["existing_names"] or not path.is_file()
            or any(p.is_symlink() or p.is_junction() for p in (path,*path.parents))):
        raise ToolSafetyError("New case lacks fresh temporary-file provenance")
    first = path.stat()
    created = getattr(first,"st_birthtime_ns",first.st_ctime_ns)
    if not inventory["started_ns"] <= created <= returned_ns or not 0<first.st_size<=1024*1024:
        raise ToolSafetyError("New case temporary creation time/size is outside its API call")
    digest = sha256_file(path)
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=2 or set(names)!={path.stem+".dfx",path.stem+".rtx"}:
            raise ToolSafetyError("Unexpected new temporary case archive members")
        if any(i.file_size>1024*1024 for i in archive.infolist()): raise ToolSafetyError("Temporary member exceeds bounds")
        dfx=archive.read(path.stem+".dfx").decode("utf-8-sig")
        rtx=archive.read(path.stem+".rtx").decode("utf-8-sig")
        rows,groups=parse_dfx_entities(dfx)
        # Reject unparsed records too, not just known parsed component types.
        if rows or groups or "COMPONENT_TYPE" in dfx or "COMPONENT:" in rtx:
            raise ToolSafetyError("New temporary case is not empty")
    last=path.stat()
    if (first.st_dev,first.st_ino,first.st_size,first.st_mtime_ns)!=(last.st_dev,last.st_ino,last.st_size,last.st_mtime_ns) or sha256_file(path)!=digest:
        raise ToolSafetyError("New temporary case changed while verifying")
    return {"path":str(path),"sha256":digest,"created_ns":created,"returned_ns":returned_ns,
            "file_identity":[first.st_dev,first.st_ino],"empty_saved_draft":True,"empty_saved_runtime":True,
            "existed_before_call":False}
