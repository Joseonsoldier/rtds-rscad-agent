# RTDS/RSCAD Agent

WP-N10 adds [line input inspection and numeric preview](docs/LINE_AUTHORING.md) through the read-only `lines` CLI. The observed three-phase scalar TLI profile preserves all unrequested bytes and requires fresh constants output after edits. Cable/general authoring, native generation and Draft Compile integration remain unqualified.

WP-N09 adds [source-bound Compile diagnostics and parser corpus checks](docs/COMPILE_DIAGNOSTICS.md). Supplied raw logs remain separate from structured findings, unknown native messages stay unresolved, and empty logs cannot hide execution or cleanup failures. Four task-scoped local API trials are documented separately from the incomplete native-message grammar and public integration qualification.

WP-N08 adds optional source-bound numerical design criteria to `check_rscad_model(..., rulepacks=None)`. The [power-system rulepacks guide](docs/POWER_SYSTEM_RULEPACKS.md) describes explicit quantity/unit/base and selector bindings, provenance, conservative unresolved results and `rtds-agent rulepacks list`. These read-only checks do not establish engineering applicability or native acceptance.

WP-N04 adds opt-in native SDK signal arrays with source-bound channel metadata, current run/attempt/hash receipts and ordered recovery through existing execution gates. Read-only preparation and saved receipt conversion reuse `capture_rtds_results`. Synthetic integration and installed source inspection do not qualify live capture, freshness, atomicity or simulator-time events. See [native capture scope](docs/NATIVE_CAPTURE.md).

Local MCP tools for RSCAD inspection, installed component/API discovery, isolated numeric and structural candidates, static model checks, saved-result metrics, and guarded sequential experiments.

[WP-N03 saved Runtime IR](docs/RUNTIME_IR.md) adds pages, groups, controls, displays, graph/curve references and explicit saved Draft references to `inspect_runtime_layout`. Live writes now require an exact subpage and unique current type/name/ID lookup. Overlay authoring and live binding qualification remain unsupported/unverified; saved values are not current values.

The [native editing checkpoints](docs/NATIVE_EDITING.md) add existing flat Draft edits and source-derived new-case insertion/wiring or GROUP clipboard reconstruction, with explicit UUID mapping and protected publication. Fresh temporary-file identity, exact stored NAME values, empty Runtime metadata preservation and GROUP-local readback are implemented. Task-scoped local API reconstruction/save/reopen and separate Compile passed for Voltage Divider, CH5 indmac and CH6 gen1. Public policy-bound live apply, automatic selection and the Runtime closed loop remain unqualified. Default static behavior is preserved.

**Early alpha — not an official RTDS Technologies product.** Live operation targets Windows, RSCAD FX 2.7.3, vendor Python API 1.1 and Python 3.12. You must supply your own licensed RSCAD installation and permitted rack access. This repository includes no RTDS software, manuals, MLIB, vendor example projects, API keys, active authorizations, or historical experiment results.

[한국어 시작 안내](docs/QUICKSTART.ko.md) · [Safety and recovery](docs/SAFETY.md) · [Runtime workflow](docs/WORKFLOWS.md) · [Validation](docs/VALIDATION.md) · [Tool contracts](docs/TOOL_CONTRACTS.md) · [Migration](docs/MIGRATION.md) · [Implementation status](docs/IMPLEMENTATION_STATUS.md)

## Install

The [v2.0 engineering guide](docs/V2_DEVELOPMENT.md) documents six added tools, a JSON experiment DSL, fourteen sampled metrics, project component policy, nine packaged skills and optional tool profiles. The [component knowledge graph](docs/COMPONENT_KNOWLEDGE.md) adds explicit local indexing and a read-only search/get/neighbors tool while retaining the catalog. Current profiles expose 50 full, 10 core and 30 engineering tools. Software/static-source tests are separate from native structural, Compile-log and rack qualification; see [implementation status](docs/IMPLEMENTATION_STATUS.md).

The partial WP-N05 checkpoint adds explicit debug/model-native event timing contracts and offline evidence from supplied clock-channel values; see [event timing](docs/EVENT_TIMING.md). Timing evidence has conservative error brackets and is not simulator-clock or scheduler qualification. Omit the timing field to retain legacy behavior; schemas are suite 1.3 and Runtime 1.5.

In PowerShell, from this repository:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\rtds-agent.exe demo
```

The demo uses synthetic in-memory drivers. It is not a simulation and does not change your execution policy. The repository is not currently published to PyPI; install from a checked-out source tree or a supplied wheel.

## Configure your installation

Replace paths with your installation. Code and user data should be kept separate.

```powershell
.\.venv\Scripts\rtds-agent.exe init --rscad-home "D:\RTDS\RSCAD"
.\.venv\Scripts\rtds-agent.exe doctor
.\.venv\Scripts\rtds-agent.exe knowledge index
.\.venv\Scripts\rtds-agent.exe mcp-config
```

Settings default to `%LOCALAPPDATA%\rtds-agent\config.json`. Set `RTDS_AGENT_CONFIG` to an absolute JSON path before initialization to use another location. `--data-dir`, repeatable `--source-root` and repeatable `--document-root` customize the permitted directories. By default, Examples and DOC under your RSCAD installation are used. Include the directory containing your licensed Python API documentation if you want it indexed too. Never configure a source/document root that contains your data directory.

`doctor` only inspects files and configuration; it never connects to RSCAD. It includes `get_capabilities` evidence separating software support, dependency availability, static API inspection, configured policy, and unverified live qualification. To render PDF pages, install Poppler independently and put `pdftoppm` on PATH. Text retrieval does not require Poppler.

Paste the TOML printed by `mcp-config` into your MCP host's configuration without replacing other server entries. For Codex, see the [official MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). Restart the MCP connection after changing configuration. The server supports local STDIO only.

## Resolve unknown information

Prefer current project evidence, installed definitions/API, exact local manual context, then explicitly optional supplementary Vector Store search. The new read-only search_rscad_api and lookup_rscad_api tools inspect installed source without importing the SDK. Missing evidence remains unresolved. A Vector Store is not an authoritative installed API catalog. See [discovery paths and limits](docs/UNKNOWN_RESOLUTION.md).

## Optional OpenAI search

Local search needs no OpenAI key. To use cloud search, pass `OPENAI_API_KEY` and `OPENAI_VECTOR_STORE_ID` through your MCP host environment. Use a key authorized for the project containing that store. A store ID alone does not grant access. See [OpenAI project permissions](https://developers.openai.com/api/docs/guides/rbac).

There are no automatic uploads. The CLI can upload explicitly selected documents to your existing store:

```powershell
.\.venv\Scripts\rtds-agent.exe knowledge upload "D:\MyDocs\approved-guide.pdf" --allow-upload
```

Only configured document roots are accepted. Check your right to upload the files and OpenAI storage/search charges first. Failed indexing can leave an uploaded file in your OpenAI project; inspect the local `upload_receipts` and remove unwanted resources through your account. Never commit your keys, generated indexes or upload receipts. HTML is optional; use it when it adds content not already present in indexed documents.

## Inspect, edit, and assess without a rack

Use project snapshots to navigate hierarchy, components, stored parameters, and ports. Build parameter catalog evidence with `rtds-agent knowledge parameters --project PATH`; indexing another project preserves earlier generations. `apply_parameter_patch_batch` applies related REAL/INTEGER changes in one validated isolated-copy transaction. Re-read the copy and use `compare_project_versions` for detailed settings/parameter/topology differences; `compare_projects` retains its summary meaning.

`get_manual_figure` returns actual MCP image content plus source/page/image hashes when Poppler is available. `evaluate_results` assesses supplied, hash-bound JSON samples against explicit interval/range/settling/reference-error requirements. It does not directly ingest existing Runtime CSV, infer engineering criteria, convert units, or certify a real model. [Follow the Kp/Ki workflow and inspect its limitations](docs/WORKFLOWS.md#change-kp-and-ki-together-while-preserving-the-original).

For optional structural/GUI investigation, `rtds-agent extensions` reads installed API declarations without connecting. New tools preview TOGGLE node impacts, prepare unchanged isolated trial copies, and inventory saved Runtime headers. They do not apply live structural edits or verify a GUI target. See [extension scope and pending qualification](docs/EXTENSION_QUALIFICATION.md).

Nine task skills with versioned capability manifests are bundled as installed package resources. To export into a chosen repository directory:

```powershell
rtds-agent skills list
rtds-agent skills export --destination ".agents\skills" --dry-run
rtds-agent skills export --destination ".agents\skills"
```

Export refuses conflicts and path redirection, and does not modify host settings. See [discovery evidence and installation details](docs/WORKFLOWS.md#optional-task-skills).

## Execution permissions

New installations are inactive. After reviewing [the boundaries and recovery procedure](docs/SAFETY.md), a local operator can opt in once:

```powershell
.\.venv\Scripts\rtds-agent.exe policy enable --actions compile offline_test runtime_start_stop runtime_controls --racks 1 2 --operator "Lab operator" --acknowledge-simulation-control
```

Replace `1 2` with racks you are authorized to use. The agent chooses an available rack within that set. Runtime must use the rack recorded by Compile. Within the selected scope, no application-level per-run prompt or CMD approval is required. Host or OS security prompts are separate.

Switches, sliders, dials, Runtime numeric inputs and supported machine/breaker LockFree switches require an exact target identity, expected initial value, write readback and restoration before stopping. Requests are limited to 64 actions and 30 seconds of warmup/control timing. The API connection has a separate timeout. Enabled legacy load-flow execution is unsupported. This is not a hard real-time watchdog.

WP-N06A adds optional read-only `check_rscad_model(..., initialization=None)` planning and supplied-evidence inspection; see [load-flow initialization](docs/LOADFLOW_INITIALIZATION.md). An enabled legacy Runtime load-flow initialization request is refused before backend, rack, or grant access; omitted or disabled initialization remains unchanged. The installed SDK expects frequency as its first argument, and load-flow initialization must precede Compile. No live qualification or automatic compiled-artifact mutation is implied.

The MCP server cannot enable policy, deploy, change rack configuration, save running cases, write vendor source files or configure external hardware I/O. See [workflow examples and limitations](docs/WORKFLOWS.md).

## What is and is not verified

The repository includes synthetic regression tests, packaging checks and a mock demo. This portable alpha must be qualified on your isolated, licensed environment before use with a real rack. A completed Compile/Runtime, matching evidence hashes, or a parsed definition is not an electrical/dynamic engineering acceptance result. No validation results or authorizations from the private prototype are inherited.

Failures and result evidence remain in your local data directory. Error records are not automatically promoted into trusted recovery instructions or shared with anyone.

## Development

```powershell
.\.venv\Scripts\python.exe -m pip install ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/release_manifest.py --check
.\.venv\Scripts\python.exe tools/release_check.py
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m twine check dist/*
```

The unittest harness uses temporary product configuration/data and clears inherited API keys before application imports. Optional installed-host discovery is enabled only with `RTDS_TEST_CODEX_DISCOVERY=1`; normal software tests make no RSCAD/rack calls.

After reviewing a code/schema/bundled-skill change, refresh the release hash manifest with `python tools/release_manifest.py --write`, rerun tests and review the diff. This checksum detects accidental local changes; it is not a cryptographic publisher signature or protection against a malicious local administrator. Do not use manifest regeneration to bypass a failed safety check.

Use `python tools/wheel_check.py PATH_TO_WHEEL` to verify a built wheel in a separate temporary venv with constrained dependencies, installed imports, synthetic demo, actual STDIO, and skill resource/export checks. The repository [AGENTS.md](AGENTS.md) provides development navigation.

## License

Agent-authored code is under the [MIT License](LICENSE). Third-party libraries retain their own licenses. RSCAD/RTDS software, documentation, definitions and examples are not included or relicensed by this project. [RTDS RSCAD information](https://www.rtds.com/technology/graphical-user-interface)
