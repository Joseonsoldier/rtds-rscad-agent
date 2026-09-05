"""Explicit synthetic resolution recipes, not model-driven skill evaluations."""
import test_environment
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import test_public_release as fixture
from rtds_agent import api_discovery, knowledge, project_tools
from rtds_agent.document_evidence import document_evidence
from rtds_agent.safety import sha256_file


class DocumentationDiscoveryTests(unittest.TestCase):
    def setUp(self):
        fixture.PublicReleaseTests.setUp(self)
        sdk = self.settings.sdk_root / "rtds"
        sdk.mkdir(parents=True)
        (sdk / "__init__.py").write_text('__version__ = "1.1"\n', encoding="utf-8")
        (sdk / "api.py").write_text('def known_signal(name: str) -> str:\n    """Synthetic signal lookup."""\n    raise RuntimeError("Do not call")\n', encoding="utf-8")

    def forbid_fallback(self):
        stack = ExitStack()
        for name in ("search_rtds_local", "get_manual_page", "search_rtds_knowledge"):
            stack.enter_context(patch.object(knowledge, name, side_effect=AssertionError("Unexpected fallback")))
        return stack

    def test_current_value_recipe_stops_at_project_evidence(self):
        with self.forbid_fallback():
            result = project_tools.get_component_parameters(str(self.project), 1)
        self.assertEqual(result["component"]["parameters"]["Gain"], "1")
        self.assertEqual(result["component"]["parameter_origins"]["Gain"], "stored")
        self.assertEqual(result["source_type"], "current_project")
        self.assertEqual(result["source_hash_rechecked"], sha256_file(self.project))

    def test_schema_recipe_uses_existing_hashed_catalog(self):
        knowledge.index_parameters(str(self.project))
        with self.forbid_fallback():
            result = knowledge.lookup_parameter("synthetic_gain", "Gain")
        self.assertEqual(result["source_type"], "installed_definition")
        self.assertEqual(result["evidence_level"], "direct")
        self.assertEqual(result["data_type"], "REAL")
        self.assertEqual(result["definition_sha256"], sha256_file(self.defs / "synthetic_gain"))
        self.assertEqual(result["version_match"], "compatible_unknown")
        self.assertEqual(result["rscad_version_evidence"], "configured_version_not_installation_verified")

    def test_known_api_recipe_stops_at_installed_lookup(self):
        with self.forbid_fallback(), patch.object(api_discovery, "search_rscad_api", side_effect=AssertionError("Exact lookup should not invoke search")):
            result = api_discovery.lookup_rscad_api("rtds.api.known_signal", "1.1")
        self.assertEqual(result["status"], "found")
        self.assertIn("name: str", result["result"]["signature"])
        self.assertFalse(result["sdk_imported"])

    def test_manual_search_then_exact_context_retains_hash_page_and_chunk(self):
        self.guide.write_text("# Synthetic control\nRSCAD FX 2.7.3\nA proportional response is described here.\n", encoding="utf-8")
        knowledge.index_documents()
        with patch.object(knowledge, "search_rtds_knowledge", side_effect=AssertionError("Cloud unnecessary")):
            search = knowledge.search_rtds_local("proportional")
            hit = search["results"][0]
            page = knowledge.get_manual_page(hit["source_path"], hit["page"])
        self.assertEqual(page["source_sha256"], hit["source_sha256"])
        self.assertEqual(page["source_sha256"], sha256_file(self.guide))
        self.assertEqual(page["page"], 1)
        self.assertTrue(page["context_verified"])
        self.assertFalse(hit["context_verified"])
        self.assertEqual(hit["source_type"], "official_local_documentation")
        self.assertFalse(hit["publisher_verified"])
        self.assertEqual(hit["version_match"], "exact")
        self.assertEqual(hit["section_heading"], "Synthetic control")
        self.assertEqual(len(hit["chunk_id"]), 64)
        self.assertEqual(hit["chunk_id"], knowledge.search_rtds_local("proportional")["results"][0]["chunk_id"])
        self.assertEqual(hit["relevance"]["method"], "sqlite_fts5_rank")

    def test_installed_doc_path_classification_is_not_publisher_authentication(self):
        official = self.vendor / "DOC/manual.md"
        official.parent.mkdir(exist_ok=True)
        official.write_text("RSCAD FX 2.7\nSynthetic installed guide", encoding="utf-8")
        with patch.object(knowledge, "get_settings", return_value=replace(self.settings, document_roots=(official.parent,))):
            result = knowledge.get_manual_page(str(official))
        self.assertEqual(result["source_type"], "official_local_documentation")
        self.assertFalse(result["publisher_verified"])
        self.assertEqual(result["version_match"], "compatible_unknown")

    def test_user_document_root_is_not_automatically_official(self):
        folder = self.root / "user-guides"
        folder.mkdir()
        path = folder / "RTDS Official claimed title.md"
        path.write_text("# User supplied guide\nRSCAD FX 2.7.3", encoding="utf-8")
        with patch.object(knowledge, "get_settings", return_value=replace(self.settings, document_roots=(folder,))):
            result = knowledge.get_manual_page(str(path))
        self.assertEqual(result["source_type"], "local_documentation")
        self.assertFalse(result["publisher_verified"])

    def test_other_release_and_multi_release_text_do_not_imply_current_support(self):
        result = document_evidence(self.guide, "RSCAD FX 3.0", self.settings)
        self.assertEqual(result["version_match"], "mismatch")
        result = document_evidence(self.guide, "RSCAD FX 2.7.3 supersedes RSCAD FX 2.6.0", self.settings)
        self.assertEqual(result["version_match"], "compatible_unknown")

    def test_changed_manual_requires_reindex_no_hash_refresh(self):
        knowledge.index_documents()
        hit = knowledge.search_rtds_local("Runtime")["results"][0]
        self.guide.write_text("Modified guide", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "indexed source changed"):
            knowledge.search_rtds_local("Runtime")
        self.assertNotEqual(hit["source_sha256"], knowledge.get_manual_page(str(self.guide))["source_sha256"])

    def test_manual_section_rejects_mixed_source_versions(self):
        rows = [{"source_sha256": digest, "source_path": str(self.guide)} for digest in ("a" * 64, "b" * 64)]
        with patch.object(knowledge, "get_manual_page", side_effect=rows):
            with self.assertRaisesRegex(ValueError, "changed across"):
                knowledge.get_manual_section(str(self.guide), 1, 2)

    def cloud(self, data):
        client = MagicMock()
        client.__enter__.return_value = client
        client.vector_stores.search.return_value = SimpleNamespace(data=data)
        stack = ExitStack()
        stack.enter_context(patch.object(knowledge, "get_settings", return_value=replace(self.settings, vector_store_id="vs_synthetic")))
        stack.enter_context(patch.object(knowledge, "read_openai_api_key", return_value="synthetic-not-a-credential"))
        stack.enter_context(patch("openai.OpenAI", return_value=client))
        return stack, client

    def test_explicit_vector_fallback_preserves_provenance_without_upload(self):
        knowledge.index_documents()
        self.assertEqual(knowledge.search_rtds_local("companyworkflow")["status"], "unresolved")
        citation = {"file_id": "synthetic-file", "filename": "company-guide", "content": [{"text": "Supplementary guide"}]}
        stack, client = self.cloud([SimpleNamespace(model_dump=lambda **_: citation)])
        with stack:
            result = knowledge.search_rtds_knowledge("companyworkflow")
        self.assertEqual(result["results"], [citation])
        self.assertEqual(result["source_type"], "configured_vector_store")
        self.assertFalse(result["installed_api_verified"])
        self.assertFalse(result["files_uploaded"])
        client.files.create.assert_not_called()
        client.vector_stores.search.assert_called_once_with(vector_store_id="vs_synthetic", query="companyworkflow", max_num_results=8)

    def test_unconfigured_vector_store_fails_without_network(self):
        with patch("openai.OpenAI", side_effect=AssertionError("Cloud unconfigured")):
            with self.assertRaisesRegex(ValueError, "Configure your own"):
                knowledge.search_rtds_knowledge("missing")

    def test_all_sources_missing_remain_unresolved_in_explicit_recipe(self):
        knowledge.index_parameters(str(self.project))
        knowledge.index_documents()
        project = project_tools.get_component_parameters(str(self.project), 999)
        self.assertEqual(project["status"], "not_found")
        with self.assertRaisesRegex(ValueError, "outside the audited"):
            knowledge.lookup_parameter("synthetic_gain", "invented_gain")
        api = api_discovery.lookup_rscad_api("rtds.api.invented_gain")
        local = knowledge.search_rtds_local("invented_gain")
        stack, _ = self.cloud([])
        with stack:
            cloud = knowledge.search_rtds_knowledge("invented_gain")
        self.assertEqual([api["status"], local["status"], cloud["status"]], ["unresolved"] * 3)
        self.assertIsNone(api["result"])
        self.assertEqual(local["results"], [])
        self.assertEqual(cloud["results"], [])
        self.assertEqual(cloud["evidence_level"], "unknown")
        # No production mega-resolver exists: the calling skill reports these
        # actual attempted sources, and cannot label the fixture a model evaluation.
