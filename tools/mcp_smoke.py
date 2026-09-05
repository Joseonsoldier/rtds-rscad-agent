"""Independent public contract and real STDIO checks using synthetic local inputs."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import base64
import shutil
import tempfile
import zipfile
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Deliberately independent of mcp_server.READ/LOCAL_WRITE/LIVE. New tools require a
# conscious public-contract update; a matching count cannot conceal a missing tool.
READ_TOOLS = frozenset({
    "search_rscad_api", "lookup_rscad_api",
    "inspect_extension_support", "preview_selector_change", "inspect_runtime_layout",
    "get_execution_diagnostics", "get_capabilities", "evaluate_results", "read_result_samples", "get_knowledge_status", "search_rtds_local", "get_manual_page", "get_manual_section",
    "lookup_parameter", "list_rscad_projects", "inspect_rscad_project",
    "get_project_hierarchy", "get_component_graph", "find_components", "get_component",
    "validate_project", "compare_projects", "trace_signal", "get_execution_policy",
    "get_workflow_status", "revalidate_execution_evidence", "list_components",
    "get_component_parameters", "find_project_parameters", "find_unconnected_ports",
    "compare_component_settings", "compare_project_versions",
})
LOCAL_WRITE_TOOLS = frozenset({"prepare_extension_trial", "apply_parameter_patch_batch", "save_result_assessment", "get_manual_figure", "apply_parameter_patch", "prepare_workflow", "prepare_simulation_run"})
LIVE_TOOLS = frozenset({"compile_project", "run_offline_test", "run_simulation"})
CLOUD_READ_TOOLS = frozenset({"search_rtds_knowledge"})
REQUIRED_TOOLS = READ_TOOLS | LOCAL_WRITE_TOOLS | LIVE_TOOLS | CLOUD_READ_TOOLS
FORBIDDEN_TOOLS = frozenset({
    "enable_policy", "configure_policy", "grant_runtime", "write_runtime_parameter",
    "configure_io", "configure_rack", "save_case", "deploy", "execute_python",
    "execute_shell", "write_file", "skip_validation", "unsafe", "mock_success",
})
DETAIL_REQUIRED_INPUTS = {
    "list_components": {"project_path"},
    "get_component_parameters": {"project_path", "component_id"},
    "find_project_parameters": {"project_path", "query"},
    "find_unconnected_ports": {"project_path"},
    "compare_component_settings": {"project_a", "project_b", "component_id"},
    "compare_project_versions": {"project_a", "project_b"},
}


def assert_contract(tools):
    by_name = {tool.name: tool for tool in tools}
    assert len(by_name) == len(tools), "Duplicate tool names"
    names = set(by_name)
    assert REQUIRED_TOOLS <= names, f"Missing required tools: {sorted(REQUIRED_TOOLS - names)}"
    assert names <= REQUIRED_TOOLS, f"Unreviewed public tools: {sorted(names - REQUIRED_TOOLS)}"
    assert not names & FORBIDDEN_TOOLS, f"Forbidden tools: {sorted(names & FORBIDDEN_TOOLS)}"
    for name, tool in by_name.items():
        assert tool.description and len(tool.description.strip()) >= 15, name
        assert tool.input_schema["type"] == "object", name
        annotation = tool.annotations
        assert annotation is not None, name
        expected = (name in READ_TOOLS | CLOUD_READ_TOOLS, name in LIVE_TOOLS,
                    name in READ_TOOLS | CLOUD_READ_TOOLS, name in LIVE_TOOLS | CLOUD_READ_TOOLS)
        actual = (annotation.read_only_hint, annotation.destructive_hint,
                  annotation.idempotent_hint, annotation.open_world_hint)
        assert actual == expected, (name, actual, expected)
    for name in ("apply_parameter_patch_batch", "evaluate_results", "save_result_assessment"):
        request = by_name[name].input_schema["properties"]["request"]
        assert request["type"] == "object" and request["additionalProperties"] is False, (name, request)
    for name in ("preview_selector_change", "prepare_extension_trial"):
        request = by_name[name].input_schema["properties"]["request"]
        assert request["additionalProperties"] is False and "snapshot_id" in request["required"], name
    batch = by_name["apply_parameter_patch_batch"].input_schema["properties"]["request"]
    assert batch["properties"]["operations"]["items"]["required"] == ["op", "component_id", "context", "component_type", "parameter", "expected_old_value", "new_value"]
    test_spec = by_name["prepare_workflow"].input_schema["properties"]["test_spec"]
    assert "measurement_channels" in test_spec["oneOf"][0]["required"], test_spec
    for name, required in DETAIL_REQUIRED_INPUTS.items():
        schema = by_name[name].input_schema
        assert set(schema.get("required", [])) == required, (name, schema)
        for field in required:
            assert schema["properties"][field]["type"] == ("integer" if field == "component_id" else "string"), (name, field)


def synthetic_project(root):
    """Small authored fixture; no installed vendor data is read."""
    vendor = root / "synthetic_install"
    definitions = vendor / "MLIB" / "COMPONENTS"
    sources = root / "sources"
    definitions.mkdir(parents=True)
    sources.mkdir()
    sdk = vendor / "python/internal interpreter/Lib/site-packages/rtds"
    sdk.mkdir(parents=True)
    (sdk / "__init__.py").write_text('__version__ = "1.1"\n', encoding="utf-8")
    (sdk / "authored.py").write_text('def signal(name: str) -> str:\n    """Synthetic runtime signal."""\n    raise AssertionError("Do not execute")\n', encoding="utf-8")
    (definitions / "synthetic_gain").write_text(
        'PARAMETERS:\n Gain "Synthetic gain" "pu" REAL 1 0 10\nNODES:\n', encoding="utf-8")
    project = sources / "synthetic.rtfx"
    with zipfile.ZipFile(project, "w") as archive:
        archive.writestr("synthetic.dfx", "DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 1\nPARAMETERS-START:\nGain: 1\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n")
    return vendor, sources, project


def detail_calls(project):
    value = str(project)
    return {
        "list_components": {"project_path": value},
        "get_component_parameters": {"project_path": value, "component_id": 1, "context": "subsystem:0"},
        "find_project_parameters": {"project_path": value, "query": "Gain"},
        "find_unconnected_ports": {"project_path": value},
        "compare_component_settings": {"project_a": value, "project_b": value, "component_id": 1},
        "compare_project_versions": {"project_a": value, "project_b": value},
    }



async def scenario_calls(session, root, vendor, sources, project, env):
    """Full authored software scenario over real STDIO; never an actual simulation."""
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    def canonical(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
    async def call(name, arguments):
        result = await session.call_tool(name, arguments)
        assert not result.is_error, (name,result)
        return result.structured_content
    definitions=vendor / "MLIB" / "COMPONENTS"
    (definitions/"synthetic_controller").write_text('PARAMETERS:\n Kp "Proportional" "pu" REAL 1 0 10\n Ki "Integral" "pu" REAL 1 0 10\n File "Input file" "" FILE companion.txt\nNODES:\n',encoding="utf-8")
    controller=sources/"controller.rtfx"
    with zipfile.ZipFile(controller,"w") as archive:
        archive.writestr("controller.dfx",'DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_controller\n0 0 0 0 3\nPARAMETERS-START:\nKp: 1\nKi: 1\nFile: companion.txt\nPARAMETERS-END:\nUUID: 10\nSUBSYSTEM-END:\n')
        archive.writestr("preserved.txt","unchanged")
    companion=sources/"companion.txt";companion.write_text("authored synthetic companion",encoding="utf-8")
    original=digest(controller); companion_hash=digest(companion)
    def index(path):
        completed=subprocess.run([sys.executable,"-m","rtds_agent","knowledge","parameters","--project",str(path)],env=env,capture_output=True,text=True,encoding="utf-8",timeout=60,check=True)
        return json.loads(completed.stdout)
    indexed=index(controller)
    index(project)  # B must not erase A's evidence.
    lookup=await call("lookup_parameter",{"component_type":"synthetic_controller","parameter":"Kp"})
    assert lookup["parameter_catalog_snapshot_id"] == indexed["parameter_catalog_snapshot_id"]
    overview=await call("inspect_rscad_project",{"project_path":str(controller)})
    request={"schema_version":"1.0","source_project":str(controller),"source_sha256":original,"rscad_version":"2.7.3","project_label":"two-gains","parameter_catalog_snapshot_id":indexed["parameter_catalog_snapshot_id"],"operations":[{"op":"set_parameter","component_id":10,"context":"subsystem:0","component_type":"synthetic_controller","parameter":name,"expected_old_value":"1","new_value":new} for name,new in (("Kp","2"),("Ki","3"))]}
    invalid=json.loads(json.dumps(request));invalid["operations"][1]["expected_old_value"]="wrong"
    failed=await session.call_tool("apply_parameter_patch_batch",{"request":invalid})
    assert failed.is_error
    assert not list((root/"data"/"projects").rglob("*.rtfx")), "Invalid batch published a copy"
    edited=await call("apply_parameter_patch_batch",{"request":request})
    working=Path(edited["working_project"])
    assert digest(controller)==original and digest(companion)==companion_hash
    assert digest(working.parent/companion.name)==companion_hash
    diff=await call("compare_project_versions",{"project_a":str(controller),"project_b":str(working)})
    assert diff["same_static_topology"] is True and diff["component_change_count"]==1
    assert {r["parameter"] for r in diff["component_changes"][0]["parameter_changes"]}=={"Kp","Ki"}
    assert edited["parameter_catalog_snapshot_ids"]==[indexed["parameter_catalog_snapshot_id"]]
    guide=sources/"synthetic-guide.md";guide.write_text("Authored test source. No engineering qualification.",encoding="utf-8")
    test_spec={"test_id":"synthetic-capture", "execution_mode":"runtime_read_only_signal_capture","runtime_required":True,"event":{"type":"none"},"runtime_controls":{"read_only_signal_capture":True,"runtime_parameter_writes":[],"hardware_io_changes":[],"rack_configuration_changes":[],"deployment_actions":[]},"runtime_capture":{"warmup_seconds":0,"minimum_samples_per_channel":3},"measurement_channels":[{"channel_id":"v","signal_path":"synthetic-only","units":"V"}],"output_requirements":{"raw_numeric_data_required":True,"screenshot_only_pass_fail_forbidden":True}}
    workflow=await call("prepare_workflow",{"source_project":str(working),"test_spec":test_spec,"grounding_paths":[str(guide)]})
    denied=await session.call_tool("compile_project",{"workflow_path":workflow["workflow_path"]})
    assert denied.is_error
    listed={t.name for t in (await session.list_tools()).tools}
    if "get_execution_diagnostics" in listed:
        diagnostics=await call("get_execution_diagnostics",{"workflow_path":workflow["workflow_path"]})
        assert diagnostics["status"]=="not_run",diagnostics
    spec={"schema_version":"1.0","requirements":[{"requirement_id":"SYN-RANGE","kind":"range","channel_id":"v","units":"V","sign_convention":"as_recorded","time_unit":"s","time_basis":"simulator_time","start_time":0,"end_time":3,"lower":0,"upper":1.2,"provenance":{"kind":"user_defined","reference":"Synthetic fixture threshold; not equipment/grid acceptance"}}]}
    assessments=[]
    for label,model,values in (("before",controller,[0,1,2,1]),("after",working,[0,1,1.1,1])):
        sample=root/"data"/(label+".json")
        value={"schema_version":"1.0","input_project_sha256":digest(model),"run_id":"synthetic-"+label,"attempt_id":"supplied-attempt","time_unit":"s","time_basis":"simulator_time","channels":[{"channel_id":"v","units":"V","sign_convention":"as_recorded","times":[0,1,2,3],"values":values}]}
        sample.write_text(json.dumps(value),encoding="utf-8")
        evaluation={"source":{"data_path":str(sample),"data_sha256":digest(sample),"input_project":str(model),"input_project_sha256":digest(model),"run_id":value["run_id"],"attempt_id":value["attempt_id"]},"specification":spec,"specification_sha256":canonical(spec)}
        result=await call("evaluate_results",{"request":evaluation})
        assert result==await call("evaluate_results",{"request":evaluation})
        assessments.append(result["status"])
    assert assessments==["failed","passed"],assessments
    saved=await call("save_result_assessment",{"request":evaluation})
    assert saved["workflow_modified"] is False
    sample.write_text("changed",encoding="utf-8")
    assert (await session.call_tool("evaluate_results",{"request":evaluation})).is_error
    image_status="skipped_poppler_unavailable"
    if shutil.which("pdftoppm"):
        from pypdf import PdfWriter
        pdf=sources/"authored.pdf"
        writer=PdfWriter();writer.add_blank_page(width=72,height=72)
        with pdf.open("wb") as stream:writer.write(stream)
        media=await session.call_tool("get_manual_figure",{"source_path":str(pdf),"page":1})
        assert not media.is_error,media
        images=[item for item in media.content if item.type=="image"]
        assert len(images)==1 and images[0].mime_type=="image/png"
        assert hashlib.sha256(base64.b64decode(images[0].data)).hexdigest()==media.structured_content["image_sha256"]
        image_status="passed_native_image"
    return {"scenario":"synthetic_two_gain_edit_and_supplied_data_assessment","parameter_changes":2,"source_and_companions_preserved":True,"catalog_A_B_A":True,"invalid_batch_unpublished":True,"assessment_statuses":assessments,"image":image_status,"actual_simulator_execution":False,"causal_effect_of_edits_proven":False}


async def extension_calls(session, root, vendor, sources):
    async def call(name, arguments):
        result = await session.call_tool(name, arguments)
        assert not result.is_error, (name, result)
        return result.structured_content
    definition=vendor/"MLIB/COMPONENTS/authored_selector"
    definition.write_text('PARAMETERS:\n Mode "Mode" "Off;On" TOGGLE Off\nNODES:\n #IF Mode=0\n OUT 1 0 OUTPUT INTEGER\n #ELSE\n NEW 1 0 OUTPUT REAL\n #END\n',encoding="utf-8")
    model=sources/"authored-selector.rtfx"
    with zipfile.ZipFile(model,"w") as archive:
        archive.writestr("selector.dfx",'DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=authored_selector\n0 0 0 0 1\nPARAMETERS-START:\nMode: Off\nPARAMETERS-END:\nUUID: 7\nSUBSYSTEM-END:\n')
        archive.writestr("selector.rtx",'VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "authored"\nCOMPONENT: TAGGED_V2.2_SWITCH\n NAME: synthetic\n GROUP: synthetic|inputs\n DESC: SW\n UUID: 8\nCOMPONENT-END:\nVIEW-END:\n')
    original=model.read_bytes()
    support=await call("inspect_extension_support",{})
    assert support["sdk_imported"] is False and support["integration_qualified"] is False
    overview=await call("inspect_rscad_project",{"project_path":str(model)})
    request={"source_project":str(model),"source_sha256":hashlib.sha256(original).hexdigest(),"snapshot_id":overview["snapshot_id"],"component_id":7,"context":"subsystem:0","component_type":"authored_selector","parameter":"Mode","expected_old_value":"Off","new_value":"On"}
    preview=await call("preview_selector_change",{"request":request})
    assert preview["node_structure_changed"] and preview["rtfx_modified"] is False
    invalid=await session.call_tool("prepare_extension_trial",{"request":{**request,"new_value":"unsafe"}})
    assert invalid.is_error and not list((root/"data/projects/.extension-trials").glob("*"))
    trial=await call("prepare_extension_trial",{"request":request})
    assert trial["status"]=="prepared_unexecuted" and trial["sdk_actions_executed"]==[]
    assert Path(trial["working_project"]).read_bytes()==original==model.read_bytes()
    layout=await call("inspect_runtime_layout",{"project_path":str(model)})
    assert layout["records"][0]["component_id"]==8 and layout["gui_observed"] is False
    listed=await call("list_rscad_projects",{})
    assert trial["working_project"] not in {p["path"] for p in listed["projects"]}
    return {"status":"passed", "trial":"prepared_unexecuted", "selector_node_impact_detected":True,
            "saved_runtime_inventory":True, "live_calls_made":False, "integration_qualified":False}


async def smoke():
    with tempfile.TemporaryDirectory(prefix="rtds-mcp-smoke-") as directory:
        root = Path(directory)
        vendor, sources, project = synthetic_project(root)
        config = root / "config.json"
        config.write_text(json.dumps({"schema_version": 1, "data_dir": str(root / "data"), "rscad_home": str(vendor),
                                      "source_roots": [str(sources)], "document_roots": [str(sources)], "vector_store_id": ""}), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k not in {"OPENAI_API_KEY", "OPENAI_VECTOR_STORE_ID", "RSCAD_HOME", "RTDS_AGENT_DATA_DIR"}}
        env["RTDS_AGENT_CONFIG"] = str(config)
        env["PYTHONUTF8"] = "1"
        params = StdioServerParameters(command=sys.executable, args=["-m", "rtds_agent", "mcp", "serve"], env=env)
        before = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert_contract(tools.tools)
                discovered = await session.call_tool("search_rscad_api", {"query": "runtime signal", "expected_api_version": "1.1"})
                assert not discovered.is_error and discovered.structured_content["status"] == "found"
                api_result = await session.call_tool("lookup_rscad_api", {"symbol": "rtds.authored.signal", "snapshot_id": discovered.structured_content["snapshot_id"]})
                assert not api_result.is_error and api_result.structured_content["result"]["signature"] == "signal(name: str) -> str"
                missing = await session.call_tool("lookup_rscad_api", {"symbol": "rtds.authored.imaginary_simulink_method"})
                assert not missing.is_error and missing.structured_content["status"] == "unresolved"
                assert missing.structured_content["sdk_imported"] is False
                for name, arguments in detail_calls(project).items():
                    result = await session.call_tool(name, arguments)
                    assert not result.is_error, (name, result)
                    assert result.structured_content["mutations_performed"] is False, (name, result)
                    assert result.structured_content["live_rscad_connection_opened"] is False, name
                    invalid = dict(arguments)
                    invalid["project_path" if "project_path" in invalid else "project_a"] = str(root / "missing.rtfx")
                    failed = await session.call_tool(name, invalid)
                    assert failed.is_error, (name, failed)
                summary = await session.call_tool("compare_projects", {"project_a": str(project), "project_b": str(project)})
                assert "component_type_count_deltas_b_minus_a" in summary.structured_content
                assert "component_changes" not in summary.structured_content
                bad_type = await session.call_tool("get_component_parameters", {"project_path": str(project), "component_id": "invalid"})
                assert bad_type.is_error, bad_type
                policy = await session.call_tool("get_execution_policy", {})
                assert not policy.is_error, policy
                result = policy.structured_content
                assert result["status"] == "inactive" and result["actions"] == [], result
                for name in ("compile_project", "run_offline_test", "run_simulation"):
                    args = {"workflow_path": str(root / "missing.json")}
                    if name == "run_simulation":
                        args.update(request_path=str(root / "missing-request.json"), request_sha256="0" * 64)
                    blocked = await session.call_tool(name, args)
                    assert blocked.is_error, (name, blocked)
                for name in sorted(FORBIDDEN_TOOLS):
                    blocked = await session.call_tool(name, {})
                    assert blocked.is_error, (name, blocked)
                after = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
                assert after == before, "Read/denied operations changed files"
                scenario = await scenario_calls(session,root,vendor,sources,project,env)
                scenario["extensions"] = await extension_calls(session,root,vendor,sources)
                print(json.dumps({"scenario":scenario,"status": "passed", "transport": "stdio", "tool_count": len(tools.tools),
                                  "detail_normal_calls": 6, "detail_error_calls": 7, "forbidden_calls": len(FORBIDDEN_TOOLS),
                                  "default_policy": "inactive", "live_actions_blocked": 3, "live_rscad_calls": False}))


if __name__ == "__main__":
    asyncio.run(smoke())
