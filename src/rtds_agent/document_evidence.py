"""Additive document provenance; configured roots do not authenticate publishers."""
from __future__ import annotations
import hashlib
from pathlib import Path
import re
from .settings import Settings, within


def document_evidence(path: Path, body: str, settings: Settings) -> dict:
    installed = settings.rscad_home is not None and within(path, settings.rscad_home / "DOC")
    versions = sorted(set(re.findall(r"\bRSCAD\s+(?:FX\s+)?(?:version\s*:?\s*)?(\d+(?:\.\d+){1,3})\b", body, re.I)))
    match = "compatible_unknown"
    if len(versions) == 1:
        detected = versions[0]
        if detected == settings.expected_rscad_version:
            match = "exact"
        elif not settings.expected_rscad_version.startswith(detected + "."):
            match = "mismatch"
    headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", body)
    return {"source_type": "official_local_documentation" if installed else "local_documentation",
            "evidence_level": "documented", "document_title": path.stem,
            "title_origin": "filename", "section_heading": headings[0][:300] if headings else None,
            "detected_rscad_versions": versions, "version_match": match,
            "version_evidence": "text_mentions_only; unknown does not establish compatibility",
            "configured_rscad_version": settings.expected_rscad_version, "publisher_verified": False,
            "source_classification_basis": "installed DOC path" if installed else "operator-configured document root"}


def chunk_identity(source: str, digest: str, page: int, rowid: int, body: str) -> str:
    return hashlib.sha256(f"{source}\0{digest}\0{page}\0{rowid}\0{body}".encode("utf-8")).hexdigest()
