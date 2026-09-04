# RTDS/RSCAD Agent

Local MCP tools for RSCAD project inspection, document search, isolated numeric edits, Compile, and bounded simulation control.

**Early alpha — not an official RTDS Technologies product.** Live operation targets Windows, RSCAD FX 2.7.3, vendor Python API 1.1 and Python 3.12. You must supply your own licensed RSCAD installation and permitted rack access. This repository includes no RTDS software, manuals, MLIB, vendor example projects, API keys, active authorizations, or historical experiment results.

[한국어 시작 안내](docs/QUICKSTART.ko.md) · [Safety and recovery](docs/SAFETY.md) · [Runtime workflow](docs/WORKFLOWS.md) · [Validation](docs/VALIDATION.md)

## Install

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

`doctor` only inspects files and configuration; it never connects to RSCAD. It reports unavailable optional features. To render PDF pages, install Poppler independently and put `pdftoppm` on PATH. Text retrieval does not require Poppler.

Paste the TOML printed by `mcp-config` into your MCP host's configuration without replacing other server entries. For Codex, see the [official MCP configuration documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). Restart the MCP connection after changing configuration. The server supports local STDIO only.

## Optional OpenAI search

Local search needs no OpenAI key. To use cloud search, pass `OPENAI_API_KEY` and `OPENAI_VECTOR_STORE_ID` through your MCP host environment. Use a key authorized for the project containing that store. A store ID alone does not grant access. See [OpenAI project permissions](https://developers.openai.com/api/docs/guides/rbac).

There are no automatic uploads. The CLI can upload explicitly selected documents to your existing store:

```powershell
.\.venv\Scripts\rtds-agent.exe knowledge upload "D:\MyDocs\approved-guide.pdf" --allow-upload
```

Only configured document roots are accepted. Check your right to upload the files and OpenAI storage/search charges first. Failed indexing can leave an uploaded file in your OpenAI project; inspect the local `upload_receipts` and remove unwanted resources through your account. Never commit your keys, generated indexes or upload receipts. HTML is optional; use it when it adds content not already present in indexed documents.

## Execution permissions

New installations are inactive. After reviewing [the boundaries and recovery procedure](docs/SAFETY.md), a local operator can opt in once:

```powershell
.\.venv\Scripts\rtds-agent.exe policy enable --actions compile offline_test runtime_start_stop runtime_controls --racks 1 2 --operator "Lab operator" --acknowledge-simulation-control
```

Replace `1 2` with racks you are authorized to use. The agent chooses an available rack within that set. Runtime must use the rack recorded by Compile. Within the selected scope, no application-level per-run prompt or CMD approval is required. Host or OS security prompts are separate.

Switches, sliders, dials, Runtime numeric inputs and supported machine/breaker LockFree switches require an exact target identity, expected initial value, write readback and restoration before stopping. Requests are limited to 64 actions and 30 seconds of warmup/control timing. The API connection and load-flow operations have separate timeouts. This is not a hard real-time watchdog.

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

After reviewing a code/schema change, refresh the release hash manifest with `python tools/release_manifest.py --write`, rerun tests and review the diff. This checksum detects accidental local changes; it is not a cryptographic publisher signature or protection against a malicious local administrator. Do not use manifest regeneration to bypass a failed safety check.

## License

Agent-authored code is under the [MIT License](LICENSE). Third-party libraries retain their own licenses. RSCAD/RTDS software, documentation, definitions and examples are not included or relicensed by this project. [RTDS RSCAD information](https://www.rtds.com/technology/graphical-user-interface)
