"""Public contract tests with expectations separate from the server registry."""
import test_environment  # isolate config and credentials before application imports
import asyncio
import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest
import test_public_release

_spec = importlib.util.spec_from_file_location("mcp_smoke_contract", Path(__file__).resolve().parents[1] / "tools" / "mcp_smoke.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


class MCPContractTests(unittest.TestCase):
    setUp = test_public_release.PublicReleaseTests.setUp
    # Reuse only fixture setup, not the inherited public-release test methods.
    def test_registry_matches_independent_contract(self):
        from rtds_agent.mcp_server import server
        contract.assert_contract(asyncio.run(server.list_tools()))

    def test_contract_detects_one_missing_tool_even_with_same_count(self):
        from rtds_agent.mcp_server import server
        tools = asyncio.run(server.list_tools())
        missing = [tool for tool in tools if tool.name != "compare_project_versions"]
        missing.append(tools[0].model_copy(update={"name": "invented_replacement"}))
        with self.assertRaisesRegex(AssertionError, "Missing required tools"):
            contract.assert_contract(missing)

    def test_detail_reads_cannot_write_connect_or_query_racks(self):
        from rtds_agent.mcp_server import server
        from rtds_agent import execution
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with patch.object(execution, "_backend", side_effect=AssertionError("SDK backend accessed")), \
             patch.object(execution, "inspect_installation", side_effect=AssertionError("Installation queried")), \
             patch("socket.create_connection", side_effect=AssertionError("Network accessed")), \
             patch.object(Path, "write_text", side_effect=AssertionError("File write")), \
             patch.object(Path, "write_bytes", side_effect=AssertionError("File write")), \
             patch.object(Path, "mkdir", side_effect=AssertionError("Directory mutation")):
            for name, arguments in contract.detail_calls(self.project).items():
                result = asyncio.run(server.call_tool(name, arguments))
                self.assertFalse(result.is_error, name)
                self.assertFalse(result.structured_content["rack_query_called"], name)
                self.assertFalse(result.structured_content["mutations_performed"], name)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
