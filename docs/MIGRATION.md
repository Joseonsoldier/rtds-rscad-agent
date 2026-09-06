# Compatibility and migration

WP-N04: runtime schema ID 1.3, suite schema ID 1.2 and capture schema ID 1.1 add optional native signal-array acquisition. Omitted acquisition mode preserves legacy canonical plans and execution behavior. Native receipt artifacts require `workflow_native`; legacy `workflow` cannot override their channel metadata. Canonical channel records add run/attempt/project identity and sample interval. No new tool or dependency. See [NATIVE_CAPTURE.md](NATIVE_CAPTURE.md).

WP-N03 adds `inspect_runtime_layout(..., representation="ir")`; the default inventory remains paginated. New parser/IR hashes invalidate prior layout/native previews. Runtime write entries now require exact live `object_subpage` (not inferred from `VIEW-ID`): Runtime schema ID 1.2, suite schema ID 1.1. Refresh cached schemas and prepare a new workflow/grant from verified target evidence; old write plans are refused without changing historical records. Empty-write read-only plans, tool profiles 49/10/29, nine skills, dependencies and inactive policy are unchanged. Saved legacy duplicate input IDs are now rejected before connection. [Runtime scope and unverified portions](RUNTIME_IR.md).

Native checkpoints are additive: optional editor `backend`, GROUP IR/coverage/pagination and sole `rebuild_draft` insert/clipboard operations. Existing calls without backend remain static; new reconstruction operations require explicit native/auto selection, and auto cannot apply. Construction previews have `candidate_sha256:null` because SDK serialization is not predicted; use the returned plan/preview ID and final observed candidate hash. UUID changes have an explicit mapping. Refresh cached previews after the adapter/plan/skill hash changes; the new temporary-file verifier is included in the SDK evidence binding. Nine skills and 49/10/29 tools remain. No operator policy or grants are migrated/activated. The prior cleanup incident is resolved; three task-scoped local reconstruction/Compile trials passed, while public live apply and general integration remain unqualified. See [scope and evidence](NATIVE_EDITING.md).

Reconstruction now accepts only a fresh empty SDK temporary file proven to appear during the owned call; a different Java temporary directory or unsupported archive format fails closed. Stored NAME spelling is preserved despite getter placeholder expansion. GROUP-local readback is bound to source observations. Empty Runtime canvas dimensions changed by native save can be reconciled after confirmed close by copying the exact source RTX, retaining raw native evidence and native DFX bytes. All other non-DFX changes remain rejected. These changes affect explicit native reconstruction only; no Runtime authoring or execution is added.

These changes retain Python 3.12, the declared MCP major version, unittest, setuptools, local STDIO, original-project protection, and default-inactive execution. No migration enables a policy, changes a rack, uploads data, or rewrites historical evidence.

## Existing clients

V2.0 adds six tools to default full mode (49 total), optional core/engineering profiles (10/29), optional overview representations/diagnostic grounding/Compile workflow hash, and `power_metric` assessment kinds. Existing 43 tools and old required fields remain. Saved native CSV conversion is explicit through `capture_rtds_results`, with independent provenance and hash validation. New structural edits require an operator-authored component policy and a reviewed preview; existing numeric edits do not. Nine skills now include JSON capability manifests. See [V2_DEVELOPMENT.md](V2_DEVELOPMENT.md) for scope and unqualified native operations.

`inspect_rscad_project` adds read-only component-policy status/hash so a pure MCP client can prepare the editor request. A malformed policy does not break legacy inspection but blocks the new editor. Runtime LockFree validation now requires an exact `Machines` or `Breakers` hierarchy segment; previously accepted near-substrings such as `NotMachines` and `BreakersBackup` are rejected. Exact intended targets are unchanged.

Existing tool names remain available. `compare_projects` retains count/coverage summary semantics; use `compare_project_versions` for detailed settings/parameter/topology differences. The six existing detail readers are now publicly advertised. New batch, capability, assessment, and diagnostic tools have separate names.

Project reads add snapshot evidence and optional snapshot/pagination arguments. Callers should accept additive result fields and preserve `snapshot_id` across pages. A nonzero `offset` now requires a snapshot. Comparisons use `snapshot_id_a` and `snapshot_id_b`. Changed project, definitions, companions, parser, or listing content requires a fresh observation; modification time and size are not sufficient. Default project listing remains published working copies; explicitly pass a configured `source_root` to inspect source projects.

`get_manual_figure` retains existing path/page/source-hash metadata but its MCP response also contains a native image. Clients must preserve content block types instead of JSON-stringifying every result. Rendering still requires independently installed Poppler; local text retrieval remains available without it.

The single numeric patch wrapper remains available, including its string-valued old/new inputs and optional project label/version. It delegates to the same strict batch validator. `prepare_workflow.test_spec` now advertises its inner Runtime/offline schema; fields prohibited by the schema or inconsistent types are rejected consistently through direct calls and MCP. Schema-permitted extension metadata remains supported, including existing Runtime top-level metadata. Do not change old plan hashes to make new validation accept them.

## Parameter catalog generations

The CLI remains:

```powershell
rtds-agent knowledge parameters --project "D:\Projects\controller.rtfx"
```

Each successful index publishes an immutable DB/audit generation and atomically replaces the catalog pointer. Indexing project B preserves project A's generations. `lookup_parameter(..., parameter_catalog_snapshot_id=...)` and patch requests can pin the evidence used. Without a snapshot, lookup requires one distinct matching definition identity; identical repeated evidence may resolve to the newest matching snapshot. Differing matching definition path/hash identities require an explicit snapshot. Live definition bytes are rechecked before use, so changed definitions invalidate stale evidence.

A validated legacy DB/audit pair remains readable in legacy mode when no snapshots exist. Before extending that catalog, explicitly run:

```powershell
rtds-agent knowledge migrate-parameters
```

Migration validates and copies the legacy evidence to an immutable generation. It preserves the old DB/audit and historical workflow hashes. Repeating migration of identical legacy bytes is idempotent. Missing/mismatched DB/audit, stale definitions, and paths outside the allowed roots fail validation; do not edit the old audit or substitute a current definition hash. Obtain fresh evidence for new work while retaining the historical record.

## Prepared result data

The numerical adapter accepts the documented canonical JSON sample structure and hash-bound request in [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md#numerical-assessment-request). Runtime long-form CSV is converted only by the explicit v2.0 acquisition tool with source provenance and validation. Synthetic native-format conversion tests do not qualify an actual simulator capture session.

Assessments are independent local artifacts. They do not add an engineering pass to previous workflows or change prior approvals. Match source/candidate/reference hashes, channel units/sign/pu bases, exact time axes, evaluation windows, and explicit criterion provenance. An inconclusive requirement must remain visible.

## Skills, distributions and release integrity

Nine instruction-only skills and capability manifests ship as package resources and can be explicitly exported with `rtds-agent skills export --destination PATH --dry-run`, followed by the same command without `--dry-run`. Export refuses existing skill directories and symlink/junction/path traversal targets. It does not choose a global location or modify host configuration. Use an empty chosen destination or separately review existing skills; there is no overwrite flag.

Release integrity now includes bundled Markdown skills as well as code and schemas. A missing, changed, or unexpected packaged skill fails integrity. Regenerate the release manifest only after reviewing a legitimate release change, then rerun the release and installed-wheel checks. This is accidental-change detection, not a publisher signature or a mechanism to re-authorize stale live work. Existing workflow/grant bindings remain subject to their original checks; prepare a new grounded workflow when evidence no longer matches.

See [WORKFLOWS.md](WORKFLOWS.md#optional-task-skills) for discovery paths and [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for measured software results and unverified live integration conditions.


## Extension follow-up

Four additive local tools are documented in [TOOL_CONTRACTS.md](TOOL_CONTRACTS.md#offline-extension-investigation-and-trials). No existing policy action is added or activated. Selector trial preparation stores unchanged copies and does not extend apply_parameter_patch to TOGGLE. Trial folders remain excluded from normal project listing. Runtime-layout pagination uses its own parser-bound snapshot, with project_snapshot_id returned separately. New schemas include stable local IDs so the existing workflow registry remains valid without network retrieval. SDK/source inspection does not imply exact running RSCAD version or live qualification.

## Observed local native-save compatibility

The later local RSCAD 2.7 trial preserved Microgrid1 circuit text and script_example static topology, but native save changed DFX/RTX serialization and added seven definition defaults to the older script example. Kp#/Ki# names resolve to Kp/Ki in the SDK. Re-read the actual saved files and regenerate snapshots; do not assume archive-byte equality, copy old approvals, or equate successful reopen with Compile/Runtime qualification. Existing policies and public API contracts are unchanged. See [the measured round-trip differences](LOCAL_RSCAD_QUALIFICATION.md).

## Documentation discovery addition

Two local read-only MCP names and a seventh optional packaged skill are additive. Existing local index files need no migration. Clients may ignore new provenance fields; source/hash/page/text and old parameter/catalog/project fields are preserved. Existing six exported skills are not overwritten automatically; export the new skill explicitly, and review any desired updates to an existing export. API/catalog/skill hashes change as reviewed release content. Default inactive policies, existing grants, and saved workflow evidence are never refreshed or enabled by discovery. See UNKNOWN_RESOLUTION.md for source and version limits.
