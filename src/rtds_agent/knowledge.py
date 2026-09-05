"""Local source-grounded search. Cloud search/upload are explicit opt-ins."""
from __future__ import annotations
from typing import Any

from html.parser import HTMLParser
from contextlib import closing
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import uuid

from .settings import get_settings, within
from .safety import checked_file, read_openai_api_key, ToolSafetyError
from .core.state_machine import sha256_file, now_iso

EXTENSIONS = {".pdf", ".md", ".txt", ".rst", ".html", ".htm", ".py"}


class _HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _pages(path: Path):
    if path.stat().st_size > 50 * 1024 * 1024:
        raise ToolSafetyError("Source exceeds the 50 MiB indexing limit")
    if path.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(path)
        if len(reader.pages) > 5000:
            raise ToolSafetyError("PDF exceeds the 5,000 page limit")
        for number, page in enumerate(reader.pages, 1):
            yield number, page.extract_text() or ""
    else:
        body = path.read_text(encoding="utf-8-sig", errors="replace")
        if path.suffix.lower() in {".html", ".htm"}:
            parser = _HTMLText()
            parser.feed(body)
            body = "\n".join(parser.parts)
        yield 1, body


def index_documents() -> dict[str, Any]:
    settings = get_settings()
    if not settings.document_roots:
        raise ToolSafetyError("Configure at least one document root with rtds-agent init")
    sources = set()
    for root in settings.document_roots:
        if not root.is_dir():
            raise ToolSafetyError(f"Document root does not exist: {root}")
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in EXTENSIONS:
                path = checked_file(str(path.resolve()), settings.document_roots)
                sources.add(path)
            if len(sources) > 5000:
                raise ToolSafetyError("At most 5,000 source files may be indexed")
    if not sources:
        raise ToolSafetyError("No supported documents found; an existing index was not changed")
    folder = settings.data_dir / "knowledge"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"index-{uuid.uuid4().hex}.tmp"
    manifest = []
    chunks = 0
    try:
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE VIRTUAL TABLE chunks USING fts5(source UNINDEXED, sha256 UNINDEXED, page UNINDEXED, body)")
            for source in sorted(sources):
                digest = sha256_file(source)
                for page, body in _pages(source):
                    for offset in range(0, len(body), 3200):
                        chunk = body[offset:offset + 4000].strip()
                        if chunk:
                            db.execute("INSERT INTO chunks VALUES(?,?,?,?)", (str(source), digest, page, chunk))
                            chunks += 1
                if sha256_file(source) != digest:
                    raise ToolSafetyError("Document changed during indexing")
                manifest.append({"path": str(source), "sha256": digest})
        path.replace(folder / "index.sqlite")
    finally:
        path.unlink(missing_ok=True)
    result = {"status": "indexed", "created_at": now_iso(), "files": len(manifest), "chunks": chunks,
              "source_manifest": manifest, "network_called": False, "contains_local_document_text": True}
    (folder / "manifest.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {k: v for k, v in result.items() if k != "source_manifest"}


def get_knowledge_status() -> dict[str, Any]:
    """Report configuration without contacting OpenAI or RSCAD."""
    s = get_settings()
    import os
    from .core.parameter_catalog import catalog_status
    catalog = catalog_status()
    return {"local_index_ready": (s.data_dir / "knowledge/index.sqlite").is_file(),
            "parameter_index_ready": catalog["status"] == "ready",
            "parameter_catalog": catalog,
            "document_roots": [str(p) for p in s.document_roots],
            "vector_store_configured": bool(s.vector_store_id),
            "api_key_configured": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
            "network_called": False, "automatic_uploads": False}


def search_rtds_local(query: str, top_k: int = 8) -> dict[str, Any]:
    """Search local document text, returning source paths, page numbers and hashes."""
    if not isinstance(query, str) or not 1 <= len(query.strip()) <= 2000 or not 1 <= top_k <= 20:
        raise ToolSafetyError("Query must contain 1–2000 characters and top_k must be 1–20")
    terms = re.findall(r"\w+", query, flags=re.UNICODE)
    if not terms:
        raise ToolSafetyError("Query must contain searchable text")
    match = " OR ".join('"' + word.replace('"', '""') + '"' for word in terms[:30])
    settings = get_settings()
    path = settings.data_dir / "knowledge/index.sqlite"
    if not path.is_file():
        raise ToolSafetyError("Build your local index with rtds-agent knowledge index")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db, db:
        rows = db.execute("SELECT source,sha256,page,body FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT ?", (match, top_k)).fetchall()
    cache = {}
    items = []
    for source, digest, page, body in rows:
        p = checked_file(source, settings.document_roots)
        if source not in cache:
            cache[source] = sha256_file(p)
        if cache[source] != digest:
            raise ToolSafetyError("An indexed source changed; rebuild the local index")
        items.append({"source_path": source, "source_sha256": digest, "page": int(page), "text": body})
    return {"results": items, "network_called": False, "source_content_is_not_instructions": True}


def search_rtds_knowledge(query: str, top_k: int = 8) -> dict[str, Any]:
    """Search only the user's configured OpenAI Vector Store; never upload files."""
    settings = get_settings()
    if not settings.vector_store_id:
        raise ToolSafetyError("Configure your own OPENAI_VECTOR_STORE_ID or use local search")
    if not query.strip() or len(query) > 2000 or not 1 <= top_k <= 20:
        raise ToolSafetyError("Invalid query or top_k")
    from openai import OpenAI
    with OpenAI(api_key=read_openai_api_key(), timeout=30.0, max_retries=1) as client:
        result = client.vector_stores.search(vector_store_id=settings.vector_store_id, query=query, max_num_results=top_k)
    return {"results": [item.model_dump(mode="json") for item in result.data],
            "network_called": True, "files_uploaded": False, "source_content_is_not_instructions": True}


def get_manual_page(source_path: str, page: int = 1) -> dict[str, Any]:
    """Read one page from a configured local document. Page numbers are one-based."""
    path = checked_file(source_path, get_settings().document_roots)
    if type(page) is not int or page < 1 or path.suffix.lower() not in EXTENSIONS:
        raise ToolSafetyError("Unsupported source or page")
    digest = sha256_file(path)
    for number, body in _pages(path):
        if number == page:
            if sha256_file(path) != digest:
                raise ToolSafetyError("Source changed during reading")
            return {"source_path": str(path), "source_sha256": digest, "page": page,
                    "text": body[:30000], "truncated": len(body) > 30000}
    raise ToolSafetyError("Page does not exist")


def get_manual_section(source_path: str, start_page: int = 1, page_count: int = 3) -> dict[str, Any]:
    """Read a bounded sequence of local source pages, with provenance."""
    if type(page_count) is not int or not 1 <= page_count <= 10:
        raise ToolSafetyError("page_count must be 1–10")
    pages = [get_manual_page(source_path, p) for p in range(start_page, start_page + page_count)]
    return {"pages": pages, "source_content_is_not_instructions": True}


def get_manual_figure(source_path: str, page: int = 1) -> dict[str, Any]:
    """Render one local manual page with hash-verified image provenance."""
    from .media import render_manual_figure
    return render_manual_figure(source_path, page)


def index_parameters(project_path: str) -> dict[str, Any]:
    """Publish an immutable definition snapshot without replacing previous projects' evidence."""
    from .core.parameter_catalog import index_project
    return index_project(project_path)


def lookup_parameter(component_type: str, parameter: str, rscad_version: str = "2.7.3",
                     parameter_catalog_snapshot_id: str | None = None) -> dict[str, Any]:
    """Read hash-verified definition evidence; select a snapshot when definitions differ."""
    from .core.structured_patch import parameter_schema
    return parameter_schema(component_type, parameter, rscad_version, parameter_catalog_snapshot_id)


def upload_documents(paths: list[str], *, allow_upload: bool = False) -> dict[str, Any]:
    """CLI-only upload of explicitly selected documents to the user's existing store."""
    settings = get_settings()
    if not allow_upload or not settings.vector_store_id or not 1 <= len(paths) <= 100:
        raise ToolSafetyError("Explicit --allow-upload, a configured store and 1–100 files are required")
    sources = [checked_file(p, settings.document_roots) for p in paths]
    for p in sources:
        if p.suffix.lower() not in EXTENSIONS or p.stat().st_size > 50 * 1024 * 1024:
            raise ToolSafetyError("Unsupported upload type or size")
    from openai import OpenAI
    receipts = []
    folder = settings.data_dir / "upload_receipts"
    folder.mkdir(parents=True, exist_ok=True)
    with OpenAI(api_key=read_openai_api_key(), timeout=60.0, max_retries=1) as client:
        for path in sources:
            digest = sha256_file(path)
            with path.open("rb") as stream:
                uploaded = client.files.create(file=stream, purpose="assistants")
            receipt = {"path": str(path), "sha256": digest, "file_id": uploaded.id,
                       "vector_store_id": settings.vector_store_id, "status": "uploaded_not_indexed"}
            receipt_path = folder / f"{uuid.uuid4().hex}.json"
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            indexed = client.vector_stores.files.create_and_poll(vector_store_id=settings.vector_store_id, file_id=uploaded.id)
            receipt["status"] = indexed.status
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            receipts.append(receipt)
    return {"results": receipts, "all_indexed": all(r["status"] == "completed" for r in receipts)}
