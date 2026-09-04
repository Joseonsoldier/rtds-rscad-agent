"""Check a real STDIO handshake and inactive policy, without credentials or RSCAD."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def smoke():
    with tempfile.TemporaryDirectory(prefix="rtds-mcp-smoke-") as directory:
        root = Path(directory)
        config = root / "config.json"
        config.write_text(json.dumps({"schema_version": 1, "data_dir": str(root / "data"), "rscad_home": None,
                                      "source_roots": [], "document_roots": [], "vector_store_id": ""}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "OPENAI_VECTOR_STORE_ID", "RSCAD_HOME", "RTDS_AGENT_DATA_DIR"}}
        env["RTDS_AGENT_CONFIG"] = str(config)
        env["PYTHONUTF8"] = "1"
        params = StdioServerParameters(command=sys.executable, args=["-m", "rtds_agent", "mcp", "serve"], env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert len(names) == 25, names
                assert not any(name in names for name in ("enable_policy", "grant_runtime", "write_runtime_parameter", "configure_io"))
                policy = await session.call_tool("get_execution_policy", {})
                assert not policy.is_error, policy
                result = policy.structured_content
                assert result["status"] == "inactive" and result["actions"] == [], result
                blocked = await session.call_tool("compile_project", {"workflow_path": str(root / "missing.json")})
                assert blocked.is_error, blocked
                print(json.dumps({"status": "passed", "transport": "stdio", "tool_count": len(names),
                                  "default_policy": "inactive", "compile_blocked": True, "live_rscad_calls": False}))


if __name__ == "__main__":
    asyncio.run(smoke())
