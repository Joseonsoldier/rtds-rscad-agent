"""Synthetic media bounds, cache and real STDIO image-block regressions."""
import test_environment  # isolate config and credentials before application imports
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch
from pypdf import PdfWriter
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import test_public_release
from media_fixture import synthetic_png, fake_renderer
from rtds_agent import media


class ManualMediaTests(unittest.TestCase):
    setUp = test_public_release.PublicReleaseTests.setUp

    def pdf(self):
        path = self.docs / "synthetic.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=80)
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def render(self, source=None, side_effect=fake_renderer):
        source = source or self.pdf()
        with patch.object(media.shutil, "which", return_value="synthetic-renderer"), \
             patch.object(media.subprocess, "run", side_effect=side_effect):
            return media.render_manual_figure(str(source))

    def test_image_and_structured_provenance_are_decodable(self):
        source = self.pdf()
        result = self.render(source)
        content = media.manual_figure_result(result)
        image = content.content[1]
        self.assertEqual(image.type, "image")
        self.assertEqual(image.mime_type, "image/png")
        data = base64.b64decode(image.data, validate=True)
        self.assertEqual(media.validate_png(data), (3, 2))
        self.assertEqual(content.structured_content["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertEqual(content.structured_content["image_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(json.loads(content.content[0].text), result)
        self.assertEqual(result["page"], 1)
        self.assertEqual(result["mime_type"], "image/png")

    def test_cache_reused_and_source_hash_changes_cache_key(self):
        source = self.pdf()
        first = self.render(source)
        with patch.object(media.subprocess, "run", side_effect=AssertionError("Cache should be used")):
            second = media.render_manual_figure(str(source))
        self.assertEqual(first, second)
        source.write_bytes(source.read_bytes() + b"\n% synthetic modification\n")
        third = self.render(source)
        self.assertNotEqual(first["cache_key"], third["cache_key"])
        self.assertTrue(Path(first["path"]).is_file())

    def test_identical_documents_have_correct_individual_provenance(self):
        source = self.pdf()
        copy = self.docs / "copy.pdf"
        copy.write_bytes(source.read_bytes())
        first, second = self.render(source), self.render(copy)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        self.assertNotEqual(first["cache_key"], second["cache_key"])
        self.assertEqual(second["source_path"], str(copy))

    def test_cache_symlink_is_rejected_before_delivery(self):
        result = self.render()
        image_path = Path(result["path"])
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda path: path == image_path or original(path)):
            with self.assertRaisesRegex(ValueError, "cache path"):
                media.manual_figure_result(result)

    def test_bad_page_and_outside_root_fail_before_renderer(self):
        source = self.pdf()
        with patch.object(media.subprocess, "run") as renderer:
            for page in (0, -1, True, 2):
                with self.assertRaises(ValueError):
                    media.render_manual_figure(str(source), page)
            outside = self.root / "outside.pdf"
            outside.write_bytes(source.read_bytes())
            with self.assertRaises(ValueError):
                media.render_manual_figure(str(outside))
            renderer.assert_not_called()

    def test_renderer_absent_does_not_break_text_read(self):
        from rtds_agent.knowledge import get_manual_page
        source = self.pdf()
        with patch.object(media.shutil, "which", return_value=None):
            self.assertEqual(get_manual_page(str(self.guide))["page"], 1)
            with self.assertRaisesRegex(ValueError, "Install Poppler"):
                media.render_manual_figure(str(source))

    def test_renderer_failure_and_timeout_publish_nothing(self):
        source = self.pdf()
        for failure in (subprocess.CalledProcessError(1, "synthetic"), subprocess.TimeoutExpired("synthetic", 45)):
            with self.assertRaises(ValueError):
                self.render(source, failure)
            self.assertEqual(list((self.data / "knowledge_cache").iterdir()), [])

    def test_source_change_during_render_publishes_nothing(self):
        source = self.pdf()
        def changing(arguments, **kwargs):
            fake_renderer(arguments, **kwargs)
            source.write_bytes(source.read_bytes() + b"\n% changed during rendering\n")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            self.render(source, changing)
        self.assertEqual(list((self.data / "knowledge_cache").iterdir()), [])

    def test_corrupt_png_cache_is_rejected(self):
        source = self.pdf()
        result = self.render(source)
        Path(result["path"]).write_bytes(b"invalid PNG")
        with self.assertRaisesRegex(ValueError, "PNG"):
            media.render_manual_figure(str(source))

    def test_cache_metadata_mismatch_is_rejected(self):
        source = self.pdf()
        result = self.render(source)
        metadata_path = Path(result["path"]).with_name("metadata.json")
        metadata = json.loads(metadata_path.read_text())
        metadata["image_sha256"] = "0" * 64
        metadata_path.write_text(json.dumps(metadata))
        with self.assertRaisesRegex(ValueError, "integrity"):
            media.render_manual_figure(str(source))

    def test_oversized_or_high_resolution_image_is_rejected(self):
        source = self.pdf()
        for data in (b"x" * (media.MAX_IMAGE_BYTES + 1), synthetic_png(width=1801, height=1)):
            def oversized(arguments, **kwargs):
                Path(arguments[-1]).with_suffix(".png").write_bytes(data)
            with self.assertRaises(ValueError):
                self.render(source, oversized)
        self.assertEqual(list((self.data / "knowledge_cache").iterdir()), [])

    def test_image_changed_before_delivery_is_rejected(self):
        result = self.render()
        Path(result["path"]).write_bytes(synthetic_png(2, 2))
        with self.assertRaisesRegex(ValueError, "changed before MCP"):
            media.manual_figure_result(result)

    def test_png_crc_and_compressed_content_are_validated(self):
        image = synthetic_png()
        with self.assertRaisesRegex(ValueError, "checksum"):
            media.validate_png(image[:-1] + bytes([image[-1] ^ 1]))
        with self.assertRaises(ValueError):
            media.validate_png(image[:-12])

    def test_real_stdio_receives_image_from_internal_fake_renderer(self):
        source = self.pdf()
        async def receive():
            env = {key: value for key, value in os.environ.items() if key not in {"OPENAI_API_KEY", "OPENAI_VECTOR_STORE_ID", "RSCAD_HOME", "RTDS_AGENT_DATA_DIR", "PYTHONPATH"}}
            env["RTDS_AGENT_CONFIG"] = str(self.config)
            params = StdioServerParameters(command=sys.executable, args=[str(Path(__file__).with_name("media_fixture.py"))], env=env)
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    result = await session.call_tool("get_manual_figure", {"source_path": str(source), "page": 1})
                    self.assertFalse(result.is_error, result)
                    images = [item for item in result.content if item.type == "image"]
                    self.assertEqual(len(images), 1)
                    self.assertEqual(images[0].mime_type, "image/png")
                    data = base64.b64decode(images[0].data, validate=True)
                    self.assertEqual(media.validate_png(data), (3, 2))
                    self.assertEqual(result.structured_content["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
                    self.assertEqual(result.structured_content["image_sha256"], hashlib.sha256(data).hexdigest())
        asyncio.run(receive())

    @unittest.skipUnless(shutil.which("pdftoppm"), "Optional Poppler integration: pdftoppm is not installed")
    def test_poppler_renders_authored_pdf(self):
        result = media.render_manual_figure(str(self.pdf()))
        self.assertGreater(result["width"], 0)
        self.assertGreater(result["height"], 0)
        self.assertEqual(result["mime_type"], "image/png")
