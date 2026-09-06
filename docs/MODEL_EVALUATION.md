# Model-driven evaluation checkpoint

WP-N11 adds a separate ten-task contract in `evals/native_tasks.json`. The original nine tasks in `evals/tasks.json` and `tools/run_evals.py` remain unchanged. No production tool, backend, policy action, skill or dependency is added; MCP profiles remain full50/core10/engineering30.

This checkpoint executes **EVAL-N01** (static API discovery), **EVAL-N02** (exact project/component inspection) and **EVAL-N09** (inactive-policy Compile rejection). EVAL-N03–08 and EVAL-N10 are declared but unsupported by this runner. Their model-driven construction, diagnosis, experiment, capture, analysis and GROUP fixtures remain unexecuted. Previous native tutorial successes do not qualify these model tasks.

## Running a declared cohort

From a source checkout or source distribution with dependencies installed:

```powershell
python tools/run_model_evals.py --list
python tools/run_model_evals.py --execute --case EVAL-N01 --case EVAL-N02 --case EVAL-N09 --repetitions 2 --output C:/lab-evaluations/new-cohort
```

`--list` does not call a model, import the vendor SDK or launch a tool server. `--execute` explicitly uses the installed Codex login and its model usage. It defaults to Astra low, supports one to three predeclared repetitions, and requires a fresh absolute output directory. Unsupported cases, reused outputs, optimized Python and unreviewed Codex versions are refused before model execution. The reviewed host is Windows with Codex CLI 0.153.4; other host/protocol versions require review.

Each attempt creates a deterministic authored model, component definition, Python API declaration and guide in an independent fixture. Writable data is separate from protected sources/configuration/definitions. No vendor tutorial, manual or SDK is copied into the fixture or sent to the model. Expected parameter values, hashes and signatures remain collector-side oracles; the model obtains them from tool responses. Prompts specify the requested work and output references: these are constrained task evaluations, not unrestricted engineering-agent benchmarks.

The runner uses `codex exec --json`, an explicit evaluation MCP server, ephemeral sessions, ignored user configuration, a read-only host sandbox and disabled shell/app/plugin/browser/agent features. It does not read/copy authentication files, change user settings, ignore execpolicy rules or bypass the sandbox. The installed Astra catalog declares `tool_mode=code_mode_only`; its internal code-mode host must remain enabled for MCP discovery/invocation. Disabling it caused the first retained calibration failure. Passive host skill-catalog notices are recorded; this does not qualify skill use or host-wide tool isolation. Requested model/effort are recorded; provider-side model identity is not independently authenticated. See [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) and [configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Real tools and bounded dispatch

`tools/eval_mcp_server.py` exposes eleven existing production functions through an evaluation-only STDIO server. Calls are schema checked and constrained to the fresh synthetic fixture. The server clears inherited RTDS/RSCAD/OpenAI settings, prohibits importing `rtds`, blocks native backend creation/processes/sockets, and audits file access. These Python guards are defense in depth, not an OS security boundary.

Only exact authored `prepare_workflow` inputs may create a copy. `compile_project` accepts only an owned, hash-pinned workflow while policy remains absent/inactive. The real public function rejects Compile before the backend. A denial is **not a native Compile attempt or success**. Policy creation, Runtime, rack, LF, GUI and arbitrary code/write tools are unavailable in this MCP server. Original inventories and hashes are checked before/after dispatch and after process cleanup.

Windows process creation atomically places Codex inside a fresh owned Job Object using `PROC_THREAD_ATTRIBUTE_JOB_LIST`; only duplicated standard-I/O handles are inherited. The job owns descendants, bounds time/output and verifies no active processes remain during cleanup. It never targets an existing simulator or unrelated process. This follows Microsoft's [process creation attribute contract](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute). Unconfirmed cleanup or protection failure stops subsequent cohort attempts. Each tool call checks protection again; a restored source can permit another call within the same model turn, but the recorded failure still fails the attempt.

## Evidence and metrics

The server durably records each started/completed call and returns the same envelope with `call_id`; its `result` is the production result, including errors. Codex independently emits its own MCP events. `tools/eval_collector.py` requires an ordered complete turn, matching identities/arguments/results, completion of every started call and a saved final answer identical to the agent message. Unexpected host operations are retained as violations. Missing, duplicated, changed or unfinished evidence cannot become a successful collection.

Final evidence uses `{call_id, pointer, value}`. The RFC6901 pointer addresses the production result in that envelope. `tools/eval_metrics.py` compares exact returned values with the fixture oracle. Missing evidence, wrong snapshots/identities, invented declarations and a Compile success alongside a denial fail the contract. Harmless extra inspection calls affect selection/unnecessary-call metrics, not safety violations merely because they were optional.

Metrics cover task success, tool selection, unsupported API claims, wrong components, unnecessary calls, edit/Compile success, diagnostic correctness, safety violations and evidence completeness. Inapplicable or unobserved operation metrics are `null`, never zero. Task success and evidence completeness grade the supplied submission, so a missing submission still fails with zero evidence; known wrong claims and violations remain recorded. Repetitions group only by exact task, requested model, contract hash and stable fixture hash. Population variance requires at least two observations. If an attempted run cannot be scored, aggregate rates stay unavailable rather than excluding it from the denominator. Predeclared repetitions are fresh trials, not automatic retries for success.

An aggregate metric is available only if every eligible attempt has that observation; otherwise it remains `null`. Individual reports still retain any known violations. The pure scorer checks **supplied record consistency only**; it cannot authenticate arbitrary files as model-generated. The explicit runner can describe its observed local process and paired transcripts, bound to fixture, implementation, prompt and artifact hashes. That evidence remains within the local account/filesystem trust boundary. It does not prove general reliability, native integration, engineering correctness, simulator timing or certification.

Private cohort files include the plan, prompt/schema, raw Codex/MCP JSONL, final answer, process evidence, protected hashes and receipts. Preserve failures unchanged; do not publish unredacted logs or generated models. Actual software/model counts are recorded separately in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and [VALIDATION.md](VALIDATION.md).
