"""Bounded local PDF rendering and native MCP image content; no uploads."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib
from typing import Any

from .core.state_machine import sha256_file
from .settings import get_settings, within
from .safety import checked_file, ToolSafetyError

RENDER_SETTINGS = {"renderer": "pdftoppm", "format": "png", "scale_to": 1800, "single_file": True, "schema_version": 1}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 50 * 1024 * 1024
RENDER_TIMEOUT_SECONDS = 45


def validate_png(data: bytes) -> tuple[int, int]:
    """Check bounded non-interlaced 8-bit PNG framing, CRC and decoded rows."""
    if len(data) > MAX_IMAGE_BYTES:
        raise ToolSafetyError("Rendered image exceeds the 8 MiB limit")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ToolSafetyError("Invalid PNG signature")
    offset, dimensions, compressed, ended = 8, None, bytearray(), False
    while offset < len(data):
        if offset + 12 > len(data):
            raise ToolSafetyError("Truncated PNG chunk")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > len(data):
            raise ToolSafetyError("Truncated PNG payload")
        payload = data[offset + 8:end]
        if zlib.crc32(kind + payload) & 0xffffffff != struct.unpack(">I", data[end:end + 4])[0]:
            raise ToolSafetyError("PNG checksum mismatch")
        if dimensions is None and kind != b"IHDR":
            raise ToolSafetyError("PNG must begin with IHDR")
        if kind == b"IHDR":
            if dimensions is not None or len(payload) != 13:
                raise ToolSafetyError("Invalid PNG header")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not 1 <= width <= RENDER_SETTINGS["scale_to"] or not 1 <= height <= RENDER_SETTINGS["scale_to"]:
                raise ToolSafetyError("Image resolution exceeds rendering limits")
            if depth != 8 or color not in {0, 2, 4, 6} or compression or filtering or interlace:
                raise ToolSafetyError("Unsupported PNG encoding")
            dimensions = (width, height)
            channels = {0: 1, 2: 3, 4: 2, 6: 4}[color]
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            if payload or end + 4 != len(data):
                raise ToolSafetyError("Invalid PNG end")
            ended = True
        elif kind[:1].isupper() and kind != b"PLTE":
            raise ToolSafetyError("Unsupported critical PNG chunk")
        offset = end + 4
    if not ended or not dimensions or not compressed:
        raise ToolSafetyError("Incomplete PNG")
    row_bytes = 1 + dimensions[0] * channels
    expected_bytes = row_bytes * dimensions[1]
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes(compressed), expected_bytes + 1)
        if not decoder.eof or decoder.unused_data or len(raw) != expected_bytes:
            raise ToolSafetyError("PNG decoded size mismatch")
        if any(raw[index] > 4 for index in range(0, len(raw), row_bytes)):
            raise ToolSafetyError("Invalid PNG row filter")
    except zlib.error:
        raise ToolSafetyError("Corrupted PNG compression") from None
    return dimensions


def _cache_root() -> Path:
    settings = get_settings()
    root = settings.data_dir / "knowledge_cache"
    if root.is_symlink() or not within(root, settings.data_dir):
        raise ToolSafetyError("Image cache escapes the configured data root")
    return root


def _image_bytes(path: Path, root: Path) -> bytes:
    if path.is_symlink() or not within(path, root) or not path.is_file():
        raise ToolSafetyError("Invalid image cache path")
    if path.stat().st_size > MAX_IMAGE_BYTES:
        raise ToolSafetyError("Rendered image exceeds the 8 MiB limit")
    data = path.read_bytes()
    validate_png(data)
    return data


def _read_cache(folder: Path, expected: dict[str, Any]) -> dict[str, Any]:
    root = _cache_root()
    if folder.is_symlink() or not within(folder, root):
        raise ToolSafetyError("Image cache directory escapes its root")
    image_path, metadata_path = folder / "image.png", folder / "metadata.json"
    if metadata_path.is_symlink() or not metadata_path.is_file() or metadata_path.stat().st_size > 20000:
        raise ToolSafetyError("Invalid image cache metadata")
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise ToolSafetyError("Corrupted image cache metadata") from None
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in expected.items()):
        raise ToolSafetyError("Image cache provenance mismatch")
    data = _image_bytes(image_path, root)
    width, height = validate_png(data)
    if (metadata.get("image_sha256") != hashlib.sha256(data).hexdigest()
            or metadata.get("bytes") != len(data) or metadata.get("width") != width or metadata.get("height") != height):
        raise ToolSafetyError("Image cache integrity mismatch")
    return {**metadata, "path": str(image_path.resolve())}


def render_manual_figure(source_path: str, page: int = 1) -> dict[str, Any]:
    """Render or revalidate a local PDF page; preserve legacy path/hash/page fields."""
    settings = get_settings()
    source = checked_file(source_path, settings.document_roots, ".pdf")
    if type(page) is not int or page < 1:
        raise ToolSafetyError("page must be a positive integer")
    if source.stat().st_size > MAX_SOURCE_BYTES:
        raise ToolSafetyError("Source exceeds the 50 MiB rendering limit")
    digest = sha256_file(source)
    from pypdf import PdfReader
    try:
        reader = PdfReader(source)
        if len(reader.pages) > 5000 or page > len(reader.pages):
            raise ToolSafetyError("Page does not exist or PDF exceeds 5,000 pages")
    except ToolSafetyError:
        raise
    except Exception:
        raise ToolSafetyError("Cannot read local PDF page structure") from None
    key = hashlib.sha256(json.dumps({"source_path": str(source), "source_sha256": digest, "page": page, "rendering": RENDER_SETTINGS}, sort_keys=True).encode()).hexdigest()
    expected = {"source_path": str(source), "source_id": "sha256:" + digest, "source_sha256": digest,
                "page": page, "mime_type": "image/png", "rendering": dict(RENDER_SETTINGS), "cache_key": key}
    root = _cache_root()
    folder = root / key
    if folder.exists():
        result = _read_cache(folder, expected)
    else:
        executable = shutil.which("pdftoppm")
        if not executable:
            raise ToolSafetyError("Install Poppler and add pdftoppm to PATH for page images")
        root.mkdir(parents=True, exist_ok=True)
        # Recheck after creating the cache to reject a redirected parent.
        if _cache_root().resolve() != root.resolve():
            raise ToolSafetyError("Image cache root changed")
        with tempfile.TemporaryDirectory(prefix=".render-", dir=root) as directory:
            temporary = Path(directory)
            prefix = temporary / "image"
            try:
                subprocess.run([executable, "-f", str(page), "-l", str(page), "-scale-to", str(RENDER_SETTINGS["scale_to"]),
                                "-singlefile", "-png", str(source), str(prefix)],
                               check=True, capture_output=True, timeout=RENDER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                raise ToolSafetyError("PDF renderer exceeded the 45 second time limit") from None
            except (subprocess.CalledProcessError, OSError):
                raise ToolSafetyError("PDF renderer failed; no image was published") from None
            data = _image_bytes(prefix.with_suffix(".png"), root)
            width, height = validate_png(data)
            if sha256_file(source) != digest:
                raise ToolSafetyError("Source changed during rendering")
            metadata = {**expected, "image_sha256": hashlib.sha256(data).hexdigest(), "width": width, "height": height, "bytes": len(data)}
            (temporary / "metadata.json").write_text(json.dumps(metadata, sort_keys=True), encoding="utf-8")
            try:
                temporary.rename(folder)
            except FileExistsError:
                # A concurrent renderer may have published the same immutable key.
                pass
            result = _read_cache(folder, expected)
    if sha256_file(source) != digest:
        raise ToolSafetyError("Source changed during image retrieval")
    return result


def manual_figure_result(metadata: dict[str, Any]):
    """Native MCP content plus structured legacy/provenance metadata (SDK 2.1)."""
    from mcp.types import CallToolResult, ImageContent, TextContent
    settings = get_settings()
    source = checked_file(metadata["source_path"], settings.document_roots, ".pdf")
    data = _image_bytes(Path(metadata["path"]), _cache_root())
    if hashlib.sha256(data).hexdigest() != metadata["image_sha256"] or sha256_file(source) != metadata["source_sha256"]:
        raise ToolSafetyError("Source or image changed before MCP delivery")
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(metadata, sort_keys=True)),
                                  ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mime_type="image/png")],
                          structured_content=metadata)
