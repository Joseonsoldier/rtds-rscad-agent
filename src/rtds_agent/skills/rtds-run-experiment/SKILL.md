---
name: rtds-run-experiment
description: Prepare and, within explicit operator authorization, execute a bounded RTDS experiment with hash-bound evidence and verified Runtime restoration and cleanup.
---

# Run a bounded RTDS experiment

## Use when

Prepare a reproducible experiment or perform a specifically authorized live compile, offline test, or Runtime run in a supported installation.

## Do not use when

The task needs deployment, rack or hardware I/O configuration, saving a running case, arbitrary shell/API execution, or policy activation by the agent. A configured active policy alone does not authorize live equipment use for an unrelated development task.

## Prerequisites

Confirm this task's live authorization, installation capabilities, policy actions/rack, project and dependency hashes, grounded test plan, channels and units, duration, and exact control identities. Runtime controls require expected initial values, readback, restoration, and verified stop/cleanup. Use an existing authorized scope without introducing redundant approval prompts.

Control write entries require the exact live `object_subpage` together with type/name/Runtime ID. Saved VIEW-ID or IR candidates cannot supply that value. The driver requires a unique current typed/name lookup and matching Runtime subtab, page, ID and case/hash, then rechecks scope before each write and restoration. An old plan without subpage must be prepared again from actual target evidence; never alter historical hashes or reuse consumed grants. Binding has synthetic tests and is not live qualification.

## Tool order

1. Call `get_execution_policy()` and `get_capabilities()`. Prepare unsupported or unauthorized live portions as pending while continuing independent offline analysis.
2. Use `prepare_workflow(source_project, test_spec, grounding_paths)` with the advertised structured test schema and actual source evidence. Preserve the returned workflow path and hashes.
3. When live compile is authorized and ready, use `compile_project(workflow_path)`, then `get_workflow_status(workflow_path)` and `revalidate_execution_evidence(workflow_path)`.
4. For an authorized offline test use `run_offline_test(workflow_path)`. For Runtime use `prepare_simulation_run(workflow_path)` immediately before `run_simulation(workflow_path, request_path, request_sha256)` with the freshly returned request path/hash. Preserve rack binding; never reuse a consumed request.
5. Re-read status and evidence. Check restoration, stop, and cleanup outcomes explicitly before reporting completion.

For opt-in `native_signal_arrays`, first supply exact saved graph/live page identity and source-hash/locator evidence for units, sign, time basis and pu base. `capture_rtds_results` mode `prepare_native` is read-only and creates no execution grant. Execute through the same authorized workflow, then convert with `workflow_native` to preserve the actual attempt receipt. Array reads have no meter/CSV fallback. Check local acquisition dispatch stop, control restoration, Runtime stop and owned-handle release separately. The installed SDK does not establish remote abort, atomic snapshots, fresh data or authoritative simulator-time events; preserve those unverified fields.

## Completion

For precise event work, explicitly choose the suite DSL `event_timing` contract. `model_native` currently supports offline plan/preparation and supplied-sample assessment only; Compile, Runtime request creation and execution are refused before backend dispatch because no scheduler/clock-epoch adapter is qualified. Native initial conditions are unsupported and must be empty. Omitted timing keeps existing host scheduling; `wall_clock_debug` labels it explicitly. Never present sleep/write delays or Runtime value readback as measured simulator event timing.

Report the actual backend and attempt, policy/plan/project binding, raw captures, control writes and readback, restored values, stop/cleanup evidence, and any incomplete outcome. Compile success and completed simulation do not establish engineering acceptance.

## On failure

After uncertain Runtime state or cleanup failure, stop the automated sequence and report the exact incomplete recovery steps for operator handling. Do not automatically restart, reuse authority, write an expected success into evidence, or weaken validation to retry.
