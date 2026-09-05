# Native closed-loop checkpoint 1

This checkpoint implements a bounded native editor and GROUP inspection. It is **not completion of WP-N01 through WP-N11**, nor qualification of a native construction/Runtime closed loop. Existing v1/v2 tools and execution safeguards remain.

## Public editor

`edit_rscad_model` accepts optional `backend: static | native | auto`. Omission preserves the static file transaction. Native preview performs static validation and installed-source inspection without importing the SDK or connecting. Its preview ID binds the original static preview, requested backend, supported scope, SDK source hashes, executable hash and adapter/worker hashes. Changed inputs require a new review.

Explicit native apply currently supports existing, flat Draft `set_parameter`, `set_selector`, `set_string`, `rename_component` and `move_component` operations. It requires the same operator-authored project component policy, definition evidence, exact old values and reviewed preview as static editing. It cannot create/activate policy. Models containing GROUP or hierarchy and native insert/clone/wire/remove operations remain outside this adapter scope. Stored text is compared exactly; unsupported native normalization rejects publication.

The SDK is loaded in a separate bounded worker process. The worker opens a private input copy, applies the fixed operations with readback, saves to a different new file, confirms close, reopens that exact saved path, repeats readback and verifies cleanup. The parent checks the full parsed candidate against the reviewed static expectation, stored settings, non-DFX archive members, companions, original/snapshot hashes, current policy, SDK and model-check findings before publishing. Native changes beyond the preview are rejected. The source snapshot is never opened by RSCAD.

This first scope uses `open_case` on an isolated copy. It does **not** implement the work order's `new_case` construction, per-component insertion or complete clipboard reconstruction. The earlier tutorial construction scripts have not been promoted wholesale into the public tool.

`auto` currently returns a **static preview only** and refuses apply. No operation-scoped construction/Compile qualification is installed, so it cannot silently select native or fall back to static apply. Per-attempt `integration_qualified` remains false. A successful bounded edit is not the work order's complete native construction DoD.

The mixed-mode MCP tool now has live/destructive annotations because explicit native apply can connect to the local application. There are still 49/10/29 tools in full/core/engineering. Static calls remain local file operations. This local edit policy does not grant Compile, Runtime, rack or load-flow permission; those existing execution policies/grants are unchanged.

## Journal and recovery

`native_journal.json` persists intent with flush/fsync before a potentially mutating call. It records owned case identity, last operation, possible mutation, fixed API calls, native RPCs, expected/actual values, save/close/reopen and separate cleanup results. A wrapper exception is not proof that no mutation occurred.

Unknown identity, worker timeout or unverifiable cleanup retains the private attempt and creates `native_recovery_required.json` in the configured data directory. The shared execution lock blocks further native apply, Compile and Runtime dispatch. The agent does not retry, force-close, touch another case or issue Compile/Runtime calls to recover. An operator must inspect the exact case/attempt and resolve it using the existing [recovery procedure](SAFETY.md) before manually removing a stale marker. Preview remains available.

The worker's fixed transport guard denies rack, Runtime, load-flow, Compile and unrequested mutations. Python socket connections are loopback-only. This guard does not inspect all networking performed internally by the Java application and is not evidence that the application has no background network activity.

## GROUP representation

GROUP containers have no vendor UUID in the observed format. They are separate entities with context, snapshot-relative `group_id`, parent, members, location, anchor bounds and header metadata. Nested GROUP membership and hierarchy context are retained. Component counts continue to count UUID-bearing component records; `coverage.group_count` is additive. Bounds describe member anchor coordinates, not symbol extents.

IR includes `groups`. Semantic comparison adds group-added/removed/member-changed/moved/structure-changed results. `compare_project_versions` provides bounded group-change pagination. Group IDs use context and local GROUP ordinal: insertion/reordering may change them, and they must never be used as persistent SDK IDs.

The internal paste adapter records native `-1` GROUP sentinels without calling `get_object(-1)`. It requires an owned verified case and returns `structure_verified: false`; saved GROUP/member comparison is still required. This helper is not a public grouped mutation capability and has synthetic, not new live paste, qualification. Static/numeric mutation of grouped records remains rejected, avoiding component/block index mismatches.

## Measured local evidence

Installed SDK inspection read/hash-checked 24 Python files, observed version 1.1 and all required declarations. A separate read-only probe blocked SDK imports, process launches and sockets. It parsed nine installed CH1–CH6 models, retaining every original hash. CH5 `indmac` has 77 component records plus one GROUP; CH6 `gen1` has 135 plus one GROUP. This removes the former need to strip GROUP headers in private verification code.

Two explicitly authorized isolated Voltage Divider adapter trials changed only resistor UUID 2, context `subsystem:0`, `R: 1.0 -> 2.0`. The transport-instrumented trial verified all three old/new/reopened readbacks, exact close/reopen, cleanup, unchanged topology and 56 protected file hashes. The model check found no errors and retained one potential-unconnected-ground-port warning; electrical acceptance remains unevaluated. SDK-reported FX was 2.7, with no patch-level observation.

The second candidate was copied again for one separately authorized Compile: return `True`, success text in the fresh log, empty error log and a 107,329-byte output binary. Stored target rack 1 is compiler configuration; no rack-query/reservation/connection or Runtime API was called. Compile cleanup and 26 protected hashes passed. The candidate and Compile input hashes matched. These are task-scoped adapter/Compile trials, **not an execution of the public policy-bound native apply tool**, because the actual model had no operator-authored component policy. Synthetic tests exercise that full public transaction without creating a real operator policy.

Private models, SDK sources, logs and receipts remain under ignored `.validation/native-closed-loop-20260905`; none is distributed. [Validation](VALIDATION.md) records software and packaging checks.

## Remaining dependency order

WP-N01 remains partial: implement and qualify native new-case construction, insertion/wires/copy/paste and explicit UUID mapping before enabling automatic native selection. WP-N02 remains partial: validate saved GROUP/hierarchy reconstruction through the public transaction and verify paste-failure recovery; inspection and defensive journaling are implemented.

After those pass, proceed to WP-N03 Runtime IR/binding and confirmed authoring APIs, WP-N04 native capture integration, WP-N05 simulator-time event evidence and WP-N06 load-flow/initialization. Their software work and source investigation are pending in this checkpoint. Runtime/rack execution remains unauthorized. WP-N07–N11 (component knowledge, rulepacks, native failure corpus, line/cable authoring and model-driven evaluation) remain pending behind the specified prerequisites. No synthetic scorer run is described as a model-driven evaluation.
