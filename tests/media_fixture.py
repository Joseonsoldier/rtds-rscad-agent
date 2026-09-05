"""Synthetic PDF/PNG fixtures and fake renderer for tests, never production flags."""
from pathlib import Path
import struct
import zlib


def synthetic_png(width=3, height=2):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    raw = b"".join(b"\0" + bytes([32, 96, 160]) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def fake_renderer(arguments, **kwargs):
    assert kwargs["timeout"] == 45 and kwargs["check"] is True
    Path(arguments[-1]).with_suffix(".png").write_bytes(synthetic_png())


def serve():
    # Internal test process only: production never accepts a fake-driver selector.
    from unittest.mock import patch
    import rtds_agent.media as media
    from rtds_agent.mcp_server import server
    with patch.object(media.shutil, "which", return_value="synthetic-renderer"), \
         patch.object(media.subprocess, "run", side_effect=fake_renderer):
        server.run(transport="stdio")


if __name__ == "__main__":
    serve()
