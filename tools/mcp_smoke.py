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
    "search_component_catalog", "get_component_schema", "check_rscad_model", "query_component_knowledge",
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
LOCAL_WRITE_TOOLS = frozenset({"capture_rtds_results", "prepare_extension_trial", "apply_parameter_patch_batch", "save_result_assessment", "get_manual_figure", "apply_parameter_patch", "prepare_workflow", "prepare_simulation_run"})
LIVE_TOOLS = frozenset({"edit_rscad_model", "run_experiment_suite", "compile_project", "run_offline_test", "run_simulation"})
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
    for name in ("apply_parameter_patch_batch", "evaluate_results", "save_result_assessment", "query_component_knowledge"):
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
    ir=await call("inspect_runtime_layout",{"project_path":str(model),"representation":"ir"})
    assert ir["runtime_ir"]["controls"][0]["component_id"]==8
    assert ir["runtime_ir"]["signal_references"][0]["draft_source"]["status"]=="unresolved"
    assert ir["runtime_ir"]["authoring_supported"] is False and model.read_bytes()==original
    listed=await call("list_rscad_projects",{})
    assert trial["working_project"] not in {p["path"] for p in listed["projects"]}
    return {"status":"passed", "trial":"prepared_unexecuted", "selector_node_impact_detected":True,
            "saved_runtime_inventory":True, "saved_runtime_ir":True, "live_calls_made":False, "integration_qualified":False}


async def engineering_calls(session,root,sources,project):
    def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    async def call(name,args):
        result=await session.call_tool(name,args)
        assert not result.is_error,(name,result)
        return result.structured_content
    found=await call("search_component_catalog",{"query":"synthetic_gain"})
    definition=await call("get_component_schema",{"component_type":"synthetic_gain","snapshot_id":found["catalog_snapshot_id"]})
    assert definition["parameters"]["Gain"]["data_type"]=="REAL"
    checked=await call("check_rscad_model",{"project_path":str(project)})
    assert checked["engineering_verdict"]=="not_evaluated"
    policy=sources/"rtds-component-policy.json"
    policy.write_text(json.dumps({"allowed_components":["synthetic_gain"],"denied_components":[],"allowed_parameters":{},"structural_edits":True}),encoding="utf-8")
    overview=await call("inspect_rscad_project",{"project_path":str(project),"representation":"mermaid"})
    assert overview["mermaid"].startswith("flowchart LR")
    request={"source_project":str(project),"source_sha256":digest(project),"snapshot_id":overview["snapshot_id"],
        "policy_sha256":overview["component_policy"]["sha256"],"project_label":"stdio-structure","mode":"preview","operations":[{
        "op":"move_component","component_id":1,"context":"subsystem:0","component_type":"synthetic_gain","expected_location":[0,0],"location":[32,32]}]}
    preview=await call("edit_rscad_model",{"request":request})
    auto=await call("edit_rscad_model",{"request":{**request,"backend":"auto"}})
    assert auto["backend"]=="static" and auto["live_calls_made"] is False
    denied_auto=await session.call_tool("edit_rscad_model",{"request":{**request,"backend":"auto","mode":"apply","preview_id":auto["preview_id"]}})
    assert denied_auto.is_error
    native=await call("edit_rscad_model",{"request":{**request,"backend":"native"}})
    assert native["backend"]=="native" and native["live_calls_made"] is False and native["integration_qualified"] is False
    reconstruction_source=sources/"synthetic-reconstruction.rtfx"
    with zipfile.ZipFile(project) as original,zipfile.ZipFile(reconstruction_source,"w") as candidate:
        for name in original.namelist():
            if name.endswith(".dfx"): candidate.writestr(name,original.read(name))
        candidate.writestr("synthetic.rtx",'VIEW-START: VIEW-ID: "1"\nVIEW-END:\n')
    reconstruction_overview=await call("inspect_rscad_project",{"project_path":str(reconstruction_source)})
    reconstruction_request={**request,"backend":"native","source_project":str(reconstruction_source),
        "source_sha256":digest(reconstruction_source),"snapshot_id":reconstruction_overview["snapshot_id"],
        "operations":[{"op":"rebuild_draft","strategy":"clipboard"}]}
    reconstruction=await call("edit_rscad_model",{"request":reconstruction_request})
    assert reconstruction["reconstruction_plan"]["runtime_records"]==0 and reconstruction["candidate_sha256"] is None
    assert reconstruction["live_calls_made"] is False
    edited=await call("edit_rscad_model",{"request":{**request,"mode":"apply","preview_id":preview["preview_id"]}})
    assert digest(project)==request["source_sha256"] and edited["integration_qualified"] is False
    ir=await call("inspect_rscad_project",{"project_path":edited["working_project"],"representation":"ir"})
    assert ir["ir"]["components"][0]["location"]==[32,32]
    raw=root/"data"/"native-authored.csv"
    raw.write_text("channel_id,signal_path,units,sample_index,time_s,value\nv,synthetic-only,V,0,0,1\nv,synthetic-only,V,1,1,0.5\nv,synthetic-only,V,2,2,1\n",encoding="utf-8")
    channels=[{"channel_id":"v","signal_path":"synthetic-only","units":"V","sign_convention":"as_recorded"}]
    captured=await call("capture_rtds_results",{"request":{"mode":"supplied_csv","source":{"data_path":str(raw),"data_sha256":digest(raw),
        "input_project":str(project),"input_project_sha256":digest(project),"run_id":"authored","attempt_id":"csv-1"},"channels":channels,"time_basis":"simulator_time"}})
    spec={"schema_version":"1.0","requirements":[{"requirement_id":"nadir","kind":"power_metric","metric":"voltage_nadir","metric_options":{},
        "channel_id":"v","units":"V","sign_convention":"as_recorded","time_unit":"s","time_basis":"simulator_time","start_time":0,"end_time":2,
        "provenance":{"kind":"user_defined","reference":"Authored metric; no engineering threshold"}}]}
    spec_hash=hashlib.sha256(json.dumps(spec,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    evaluated=await call("evaluate_results",{"request":{"source":captured["source"],"specification":spec,"specification_sha256":spec_hash}})
    assert evaluated["status"]=="not_evaluated" and evaluated["results"][0]["metrics"]["value"]==.5
    dsl={"schema_version":"1.0","test_id":"stdio-suite","controls":[],"initial_conditions":[],"events":[],"channels":channels,
        "capture_after_seconds":2,"minimum_samples_per_channel":2,"criteria":spec,"traceability":[]}
    request={"mode":"plan","source_project":str(project),"source_sha256":digest(project),"snapshot_id":overview["snapshot_id"],
        "grounding_paths":[str(sources/"synthetic-guide.md")],"specification":dsl,"sweep":{"mode":"cartesian","axes":[]}}
    plan=await call("run_experiment_suite",{"request":request})
    prepared=await call("run_experiment_suite",{"request":{**request,"mode":"prepare","suite_id":plan["suite_id"]}})
    run_id,row=next(iter(prepared["runs"].items()))
    denied=await session.call_tool("run_experiment_suite",{"request":{**request,"mode":"execute","suite_id":plan["suite_id"],
        "executions":[{"run_id":run_id,"action":"compile","workflow_sha256":digest(Path(row["workflow_path"]))}]}})
    assert denied.is_error
    native_project=sources/'authored-native-signals.rtfx'
    with zipfile.ZipFile(project) as original,zipfile.ZipFile(native_project,'w') as candidate:
        for name in original.namelist():
            if name.endswith('.dfx'):candidate.writestr(name,original.read(name))
        candidate.writestr('authored.rtx','''VIEW-START: view VIEW-TYPE: RUNTIME-VIEW VIEW-ID: "saved"
COMPONENT: PLOT
NAME: Container
UUID: 100
PLOT-DATA-START
GRAPH-START: GRAPH 1: 1 CURVE
GRAPH-DATA-START
NAME: Voltage
UUID: 101
GRAPH-DATA-END
CURVE-START
GROUP: Subsystem #1|Outputs
DESC: V
COMP_ID: 1
CURVE-END
GRAPH-END
PLOT-DATA-END
COMPONENT-END:
''')
    native_dsl={**dsl,'test_id':'stdio-native-arrays','acquisition_mode':'native_signal_arrays',
        'channels':[{'channel_id':'v','signal_path':'Subsystem #1|Outputs|V','units':'V','sign_convention':'as_recorded',
          'time_basis':'simulator_time','metadata_evidence':{'source_sha256':digest(sources/'synthetic-guide.md'),'locator':'Authored test declaration'},
          'runtime_identity':{'object_uuid':101,'object_name':'Voltage','object_subpage':'Plots'}}]}
    native_overview=await call('inspect_rscad_project',{'project_path':str(native_project)})
    native_request={**request,'source_project':str(native_project),'source_sha256':digest(native_project),
        'snapshot_id':native_overview['snapshot_id'],'specification':native_dsl}
    native_plan=await call('run_experiment_suite',{'request':native_request})
    native_suite=await call('run_experiment_suite',{'request':{**native_request,'mode':'prepare','suite_id':native_plan['suite_id']}})
    native_workflow=next(iter(native_suite['runs'].values()))['workflow_path']
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    native_capture=await call('capture_rtds_results',{'request':{'mode':'prepare_native','workflow_path':native_workflow}})
    assert native_capture['status']=='prepared_native_capture_unexecuted' and native_capture['grant_created'] is False
    assert native_capture['live_calls_made'] is False and before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    timing_channels=[{'channel_id':'state','signal_path':'Authored|State','units':'position','sign_convention':'0=open 1=closed'},
                     {'channel_id':'clock','signal_path':'Authored|Clock','units':'s','sign_convention':'elapsed since declared reset'}]
    timing_dsl={**dsl,'test_id':'stdio-timing','criteria':{'schema_version':'1.0','requirements':[]},'channels':timing_channels,
        'controls':[{'target_id':'switch','purpose':'switch_operation','object_uuid':20,'object_type':'switch','object_name':'Authored',
                     'object_group':'Authored|Controls','object_desc':'Switch','object_subpage':'Controls','attribute':'position','expected_initial_value':0,'units':'position'}],
        'events':[{'event_id':'on','kind':'operator_control','target_id':'switch','value':1,'units':'position','at_seconds':1}],
        'event_timing':{'mode':'model_native','clock_channel_id':'clock',
            'source_evidence':{'source_sha256':digest(sources/'synthetic-guide.md'),'locator':'Authored clock declaration, not simulator qualification'},
            'observations':[{'action_id':'event.on','channel_id':'state','window_start_seconds':0,'window_end_seconds':2,
                             'value_tolerance':0,'max_timing_error_seconds':.51,'max_sample_gap_seconds':.51}]}}
    timing_request={**request,'specification':timing_dsl}
    timing_plan=await call('run_experiment_suite',{'request':timing_request})
    assert timing_plan['plan']['runs'][0]['test_spec']['runtime_controls']['runtime_parameter_writes']==[]
    timing_prepared=await call('run_experiment_suite',{'request':{**timing_request,'mode':'prepare','suite_id':timing_plan['suite_id']}})
    timing_run,timing_row=next(iter(timing_prepared['runs'].items()))
    workflow=json.loads(Path(timing_row['workflow_path']).read_text(encoding='utf-8'))
    samples=root/'data'/'authored-timing.json'
    sample_data={'schema_version':'1.0','input_project_sha256':timing_row['input_project_sha256'],'run_id':workflow['workflow_id'],
        'attempt_id':'stdio-supplied','time_unit':'s','time_basis':'simulator_time',
        'channels':[{**timing_channels[0],'times':[100,100.5,101,101.5,102],'values':[0,0,1,1,1]},
                    {**timing_channels[1],'times':[100,100.5,101,101.5,102],'values':[0,.5,1,1.5,2]}]}
    samples.write_text(json.dumps(sample_data),encoding='utf-8')
    timing_ref={'data_path':str(samples),'data_sha256':digest(samples),'input_project':timing_row['input_project'],
        'input_project_sha256':timing_row['input_project_sha256'],'run_id':workflow['workflow_id'],'attempt_id':'stdio-supplied'}
    timing_result=await call('run_experiment_suite',{'request':{**timing_request,'mode':'assess','suite_id':timing_plan['suite_id'],
        'captures':[{'run_id':timing_run,'source':timing_ref}]}})
    assert timing_result['timing_status_counts']=={'passed':1} and timing_result['deterministic_verified'] is False
    assert timing_result['assessments'][0]['event_timing']['events'][0]['observed_simulator_time']==1
    no_grant=await session.call_tool('prepare_simulation_run',{'workflow_path':timing_row['workflow_path']})
    assert no_grant.is_error and not list(Path(timing_row['workflow_path']).parent.glob('runtime-request-*.json'))
    point={'P':{'value':1,'units':'pu','sign_convention':'authored injection','pu_base':100}}
    initialization={'schema_version':'1.0','mode':'preconditions','input_project_sha256':digest(project),
        'entities':[{'entity_id':'source1','role':'source','context':'subsystem:0','component_id':1,
            'component_type':'synthetic_gain','requested_operating_point':point,
            'parameter_bindings':[{'quantity':'P','parameter':'Gain','expected_stored_value':'1',
                'calculated_parameter':'Gain','expected_calculated_stored_value':'1'}]}],
        'provenance':[{'source_path':str(sources/'synthetic-guide.md'),'source_sha256':digest(sources/'synthetic-guide.md'),
                       'locator':'Authored mapping, not a solver result'}]}
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    checked_init=(await call('check_rscad_model',{'project_path':str(project),'initialization':initialization}))['initialization']
    assert checked_init['status']=='preconditions_checked' and checked_init['execution_authorized'] is False
    assert before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    lf_data=root/'data'/'supplied-initialization.json'
    lf_data.write_text(json.dumps({'schema_version':'1.0','evidence_id':'authored-only',
        'initialization_plan_sha256':checked_init['initialization_plan_sha256'],'input_project_sha256':digest(project),
        'after_project_sha256':digest(project),'solver_report':{'reported_status':'converged','warnings':[]},
        'calculated_states':[{'entity_id':'source1','operating_point':point}],'parameter_changes':[]}),encoding='utf-8')
    supplied_init=(await call('check_rscad_model',{'project_path':str(project),'initialization':{
        **initialization,'mode':'supplied_evidence','evidence':{'data_path':str(lf_data),'data_sha256':digest(lf_data),
            'after_project':str(project),'after_project_sha256':digest(project),'after_snapshot_id':checked_init['snapshot_id']}}}))['initialization']
    assert supplied_init['status']=='consistent_supplied_evidence' and supplied_init['integration_qualified'] is False
    assert supplied_init['loadflow_called'] is False and supplied_init['mutations_performed'] is False
    legacy_spec={**plan['plan']['runs'][0]['test_spec'],'loadflow_initialization':{'enabled':True,'timeout_seconds':30,
        'zero_impedance_threshold_pu':1e-6,'flat_start':True,'method':'FAST_DECOUPLED'}}
    legacy=await call('prepare_workflow',{'source_project':str(project),'test_spec':legacy_spec,
        'grounding_paths':[str(sources/'synthetic-guide.md')]})
    refused_lf=await session.call_tool('prepare_simulation_run',{'workflow_path':legacy['workflow_path']})
    assert refused_lf.is_error and 'frequency, not timeout' in str(refused_lf)
    assert not list(Path(legacy['workflow_path']).parent.glob('runtime-request-*.json'))
    rule_definition=root/'synthetic_install'/'MLIB'/'COMPONENTS'/'authored_rule_device'
    rule_definition.write_text('PARAMETERS:\n R "Authored resistance" "Ohm" REAL 0 -10 10\n Mode "Mode" "Off;On" TOGGLE 1\nNODES:\n',encoding='utf-8')
    rule_model=sources/'authored-rule-device.rtfx'
    with zipfile.ZipFile(rule_model,'w') as archive:
        archive.writestr('authored.dfx','DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=authored_rule_device\n0 0 0 0 2\nPARAMETERS-START:\nR: 0\nMode: On\nPARAMETERS-END:\nUUID: 201\nSUBSYSTEM-END:\n')
    domain_request={'schema_version':'1.0','input_project_sha256':digest(rule_model),'packs':[{
        'pack_id':'authored-transformer','domain':'transformer','bindings':[{'binding_id':'r','context':'subsystem:0',
            'component_id':201,'component_type':'authored_rule_device','definition_sha256':digest(rule_definition),
            'parameter':'R','expected_value':'0','origin':'stored','quantity':'resistance','units':'Ohm',
            'basis':'Authored physical resistance reference','pu_base':None,'selectors':[{'parameter':'Mode','expected_value':'On'}]}],
        'rules':[{'rule_id':'nonnegative-r','check':'nonnegative_resistance','inputs':{'value':'r'},'limits':{},
            'source':[{'source_path':str(rule_definition),'source_sha256':digest(rule_definition),'locator':'Authored numeric declaration'}],
            'scope':'Authored fixture; no universal transformer requirement','severity':'warning',
            'confidence':{'level':'low','rationale':'Synthetic transport test'},'assumptions':[]}]}]}
    readonly_before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    checked_rules=(await call('check_rscad_model',{'project_path':str(rule_model),'rulepacks':domain_request}))['rulepacks']
    assert checked_rules['counts']['passed']==1 and checked_rules['source_hashes_verified'] is True
    assert checked_rules['execution_authorized'] is False and checked_rules['integration_qualified'] is False
    bad_selector=json.loads(json.dumps(domain_request))
    bad_selector['packs'][0]['bindings'][0]['selectors'][0]['expected_value']='Off'
    uncertain=await call('check_rscad_model',{'project_path':str(rule_model),'rulepacks':bad_selector})
    assert uncertain['rulepacks']['counts']['inconclusive']==1 and uncertain['status']=='inconclusive'
    bad_provenance=json.loads(json.dumps(domain_request))
    bad_provenance['packs'][0]['rules'][0]['source'][0]['source_sha256']='0'*64
    assert (await session.call_tool('check_rscad_model',{'project_path':str(rule_model),'rulepacks':bad_provenance})).is_error
    assert readonly_before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    # Authored saved evidence exercises parsing only; no Compile is dispatched.
    diag_workflow=Path(legacy['workflow_path']);diag_manifest=json.loads(diag_workflow.read_text(encoding='utf-8'))
    diag_inputs={'source_sha256':diag_manifest['project']['source_sha256'],'working_sha256':diag_manifest['project']['working_sha256']}
    diag_log=diag_workflow.parent/'authored-api-exception.txt'
    diag_log.write_text("rscad.library.RSCADException: Compile process failed to complete. See 'Compile Messages' tab for more details.",encoding='utf-8')
    diag_attempt_id='authored-native-diagnostics'
    diag_result={'schema_version':'1.0','backend':'ProductionRscadBackend','action':'compile',
        'evidence_kind':'synthetic_software_test','workflow_id':diag_manifest['workflow_id'],'attempt_id':diag_attempt_id,
        'hashes':{'source_before':diag_inputs['source_sha256'],'working_before':diag_inputs['working_sha256']},
        'diagnostic_log':{'schema_version':'1.0','complete':True,'entries':[]},
        'driver':{'errors':[{'type':'RSCADError','message':'Authored failed attempt'}],'cleanup_errors':[]},
        'native_compile_logs':{'schema_version':'1.0','workflow_id':diag_manifest['workflow_id'],
            'attempt_id':diag_attempt_id,'action':'compile',**diag_inputs,'logs':[{'path':str(diag_log),'sha256':digest(diag_log),
            'bytes':diag_log.stat().st_size,'encoding':'utf-8','format_id':'rscad_compile_api_exception_v1','collection_status':'partial'}]}}
    diag_artifact=diag_workflow.parent/'authored-compile-result.json';diag_artifact.write_text(json.dumps(diag_result),encoding='utf-8')
    diag_ref={'path':str(diag_artifact),'sha256':digest(diag_artifact)}
    diag_manifest['compile']={'succeeded':False,'artifact_sha256':None,'selected_rack':1,'result_ref':diag_ref}
    diag_workflow.write_text(json.dumps(diag_manifest),encoding='utf-8')
    (diag_workflow.parent/'compile.attempt.json').write_text(json.dumps({'schema_version':1,'workflow_id':diag_manifest['workflow_id'],
        'attempt_id':diag_attempt_id,'action':'compile','status':'finished','execution':'failed','cleanup':'succeeded',
        'input_hashes':diag_inputs,'result_ref':diag_ref}),encoding='utf-8')
    diag_before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    diag=await call('get_execution_diagnostics',{'workflow_path':str(diag_workflow)})
    assert diag['status']=='available' and diag['diagnostic_count']==1 and diag['no_diagnostics_found'] is False
    assert diag['native_compile_analysis']['diagnostics'][0]['category']=='rscad_api'
    assert diag['native_compile_analysis']['diagnostics'][0]['component_mapping']=='unknown'
    assert diag_before=={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    diag_log.write_text('Changed after receipt capture',encoding='utf-8')
    stale_diag=await call('get_execution_diagnostics',{'workflow_path':str(diag_workflow)})
    assert stale_diag['status']=='stale' and 'native_compile_analysis' not in stale_diag
    return {"catalog_schema":True,"static_editor_roundtrip":True,"native_preview_only":True,"native_reconstruction_preview":True,"auto_apply_denied":True,"model_check":True,"canonical_csv_metric":True,"suite_prepare":True,"suite_execution_denied":True,"native_capture_preparation":True,"native_timing_plan_and_supplied_assessment":True,"native_timing_grant_refused":True,
            "initialization_preconditions_and_supplied_evidence":True,"legacy_loadflow_grant_refused":True,
            "domain_rules_zero_resistance":True,"domain_rules_selector_inconclusive":True,"domain_rules_bad_provenance_refused":True,
            "native_compile_diagnostics_read_only":True,"native_log_tamper_refused":True,"empty_log_retains_operational_failure":True}


def line_cli_checks(root, sources, env):
    """Exercise packaged read-only input preview with an authored scalar file."""
    source = sources / 'authored-scalar.tli'
    request_file = sources / 'authored-line-preview.json'
    sections = {'Line Summary': {'Line Length': 75, 'Steady State Frequency': 50},
                'Line Constants Ground Data': {'GroundResistivity': 120},
                'RLC Options': {'Data Entry Format': 0,
                    'Positive Sequence Series Resistance': 0.03, 'Positive Sequence Series Ind Reactance': 0.4,
                    'Positive Sequence Series Cap Reactance': 0.2, 'Zero Sequence Series Resistance': 0.2,
                    'Zero Sequence Series Ind Reactance': 1.1, 'Zero Sequence Series Cap Reactance': 0.3,
                    'Number of Phases': 3}}
    source.write_text(''.join(name + ':\n  {\n' + ''.join(f'  {key} = {value}\n' for key, value in rows.items())
                              + '  }\n' for name, rows in sections.items()), encoding='utf-8')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    request_file.write_text(json.dumps({'schema_version': '1.0', 'profile_id': 'tline_rlc_3phase_ohmic_v1',
        'source': {'path': str(source), 'sha256': digest},
        'assumptions': {'ideally_transposed': True, 'frequency_independent_bergeron': True},
        'changes': [{'field': 'line_length_km', 'expected': 75, 'value': 80}],
        'provenance': [{'source_path': str(source), 'source_sha256': digest, 'locator': 'authored fixture'}]}), encoding='utf-8')
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    for args in (['list'], ['inspect', str(source), '--sha256', digest], ['preview', str(request_file)]):
        run = subprocess.run([sys.executable, '-m', 'rtds_agent', 'lines', *args], env=env,
                             capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
        report = json.loads(run.stdout)
        assert report['execution_authorized'] is False and report['integration_qualified'] is False
        if args[0] == 'preview':
            assert report['status'] == 'preview_only' and report['files_written'] == 0
            assert report['candidate']['persisted'] is False and report['candidate']['sha256'] != digest
    assert before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    source.write_bytes(source.read_bytes() + b'\n')
    stale = subprocess.run([sys.executable, '-m', 'rtds_agent', 'lines', 'preview', str(request_file)],
                           env=env, capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert stale.returncode == 1 and json.loads(stale.stdout)['error'] == 'ToolSafetyError'
    return {'cli_list_inspect_preview': True, 'no_files_written': True, 'stale_input_refused': True,
            'solver_called': False, 'compile_called': False}


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
                scenario["engineering"] = await engineering_calls(session,root,sources,project)
                graph_build = subprocess.run([sys.executable, '-m', 'rtds_agent', 'knowledge', 'graph', 'build', '--project', str(project)],
                    env=env, capture_output=True, text=True, encoding='utf-8', timeout=90, check=True)
                graph_id = json.loads(graph_build.stdout)['graph_id']
                graph_before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                graph_request = {'graph_id': graph_id, 'mode': 'search', 'query': 'synthetic_gain', 'limit': 1}
                graph_result = await session.call_tool('query_component_knowledge', {'request': graph_request})
                assert not graph_result.is_error, graph_result
                graph_content = graph_result.structured_content
                assert graph_content['status'] == 'found' and graph_content['compatibility_verified'] is False
                node_id = graph_content['nodes'][0]['node_id']
                for mode in ('get', 'neighbors'):
                    result = await session.call_tool('query_component_knowledge', {'request': {'graph_id': graph_id, 'mode': mode, 'node_id': node_id}})
                    assert not result.is_error and result.structured_content['mutations_performed'] is False, result
                malformed = await session.call_tool('query_component_knowledge', {'request': {**graph_request, 'depth': 2}})
                assert malformed.is_error
                assert graph_before == {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                definition = vendor/'MLIB'/'COMPONENTS'/'synthetic_gain'
                old_definition = definition.read_bytes()
                try:
                    definition.write_bytes(old_definition + b'\n// stale graph probe\n')
                    assert (await session.call_tool('query_component_knowledge', {'request': graph_request})).is_error
                finally:
                    definition.write_bytes(old_definition)
                scenario['component_knowledge'] = {'cli_build': True, 'read_only_search_get_neighbors': True, 'stale_source_refused': True}
                scenario['line_authoring'] = line_cli_checks(root, sources, env)
                summary={"scenario":scenario,"status": "passed", "transport": "stdio", "tool_count": len(tools.tools),
                                  "detail_normal_calls": 6, "detail_error_calls": 7, "forbidden_calls": len(FORBIDDEN_TOOLS),
                         "default_policy": "inactive", "live_actions_blocked": 4, "live_rscad_calls": False}
        profile_results=[]
        for profile,count in (("core",10),("engineering",30)):
            params=StdioServerParameters(command=sys.executable,args=["-m","rtds_agent","mcp","serve","--profile",profile],env=env)
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    await session.initialize()
                    tools=await session.list_tools()
                    assert len(tools.tools)==count,(profile,len(tools.tools))
                    blocked=await session.call_tool("execute_python",{})
                    assert blocked.is_error
                    profile_results.append({"profile":profile,"tool_count":count,"status":"passed","transport":"stdio"})
        print(json.dumps({**summary,"profiles":profile_results}))


if __name__ == "__main__":
    asyncio.run(smoke())
