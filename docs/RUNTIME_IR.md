# Saved Runtime IR and control identity — WP-N03

WP-N03 Phase A/B implements a bounded saved-file parser and semantic IR. Phase C overlay construction is unsupported. This checkpoint makes no SDK connection, opens no RSCAD case, and performs no Compile, Runtime, rack or load-flow action. Source inspection and synthetic driver tests do not qualify live control binding.

## Read contract

Call `inspect_runtime_layout(project_path, representation="ir")`. The default `representation="inventory"` retains paginated records. IR is whole-document and accepts the default `offset=0, limit=100` only. Both representations bind the project snapshot and parser/IR module hashes. Changing source bytes, dependencies or these modules invalidates a prior layout snapshot. The IR additionally records project/member hashes and a deterministic `ir_sha256`.

The [Runtime IR schema](../src/rtds_agent/schemas/runtime_ir.schema.json) describes six entity arrays: `RuntimePage`, `RuntimeGroup`, `RuntimeControl`, `RuntimeDisplay`, `RuntimePlot` and `RuntimeSignalReference`. Keys identify saved records within one snapshot. Pages retain `VIEW-ID` and canvas dimensions; groups retain visual nesting. Controls retain saved ranges, positions and labels, with the SDK type's value/position attribute. METER/LIGHT records are displays. Plots retain separate container and graph IDs, graph fields and curve references. Unsupported types remain in `unknown_records`.

An explicit saved `COMP_ID` may identify a Draft source candidate. Runtime UUID, name and displayed GROUP text are never fallback Draft identities. Duplicate Draft UUIDs across contexts return all candidates as ambiguous; absent/invalid references remain unresolved. `unique_saved_reference` means one parsed saved Draft candidate, not a verified signal path, unit, live handle or execution target. Any ambiguous/unresolved reference makes IR status partial. Legacy tagged/plain duplicates are retained; the parser does not choose an active serialization variant.

`current_value`, `units`, expected current value and live page name remain null; stored units and values have separate fields. `live_target_verified` and `authoring_supported` remain false. `VIEW-ID` does not establish the SDK subpage name. GUI-DATA and unknown data blocks cannot overwrite graph identity. NaN axis strings remain strings. Numeric sample payloads, scripts, undocumented graph options and arbitrary RTX serialization are outside coverage. EOF or the next view header may terminate a saved page, as observed in installed examples; unclosed components, graphs, curves and data blocks are rejected.

Limits: 16 MiB RTX, 10,000 components, nesting depth 32, 256 pages, 2,000 graphs, 256 curves per graph, 20,000 references, 10,000 characters per line, 4,096 per field and 10 MiB serialized IR. Inventory pagination remains at most 500 records. Bounds and partial evidence are not full format qualification.

## Guarded control binding

Existing authorized Runtime writes now require `object_subpage`, the exact live SDK page name supplied with the operator's target evidence. The driver verifies current case path/file hash, a unique `get_objects(type, name)` result, exact Runtime ID, `subtab == "Runtime"`, exact subpage and agreement with a second ID lookup. It repeats binding before each write and before restoration. The existing expected current value check occurs before writing; readback, restoration, stop and cleanup remain mandatory. A duplicate candidate is rejected even if one ID matches. Saved control discovery shares the bounded parser, handles nested GROUP references and PUSHBUTTON aliases, and rejects duplicate or incomplete stored identities before connecting.

The read-only IR tool cannot invoke this binder. It is used only inside the existing policy/grant-bound Runtime driver. Binding receipts distinguish identity verification from the separately checked expected value. A changed target during restoration records cleanup failure and does not write to the changed target; remaining stop/cleanup attempts continue. This protection cannot guarantee physical recovery and adds no live authorization.

Runtime test schema ID advances to 1.2 and experiment suite schema ID to 1.1. Old write plans lacking `object_subpage` fail closed; refresh cached schemas, source observations, workflow preparation and grants. Do not edit historical hashes or consumed approvals. Read-only plans with an empty write list remain compatible. Tool counts 49/10/29, nine skills, Python/dependencies, default-inactive policy and package version remain unchanged.

## Installed evidence and limits

Read-only inspection covered the installed Python API 1.1 declarations, its local HTML reference, ten Introductory Course saved projects and Java method bytecode. Source paths/hashes, line references, private model copies and raw excerpts are retained locally under ignored `.validation/runtime-ir-20260906`; no vendor code or model is distributed. The actual source inspection recognizes both bare `@ConnectedProperty` and explicit read-only variants; the connector documents that bare form as read-only. Running RSCAD version is unknown in this checkpoint.

| Surface | Observed source evidence | Qualification |
|---|---|---|
| Saved pages/groups/controls/displays/graphs | Tagged and plain legacy records; explicit GROUP/DESC/COMP_ID tuples; nested graph/curve sections | Read-only parser/IR subset; duplicates remain partial |
| Runtime typed lookup | `rtx.Runtime.get_objects(comp_type, name)` and `get_object(comp_id)` | Declarations inspected; exact binding tested with synthetic handles |
| Component scope | `component.Component.subtab/subpage`; Java `RTFXComponentController` delegates to view type and top-level view name | Read-only scope semantics inspected; no live lookup |
| Inherited authoring wrappers | RuntimeSubpage inherits insert/copy/paste from ComponentCompatible; HTML documents inheritance | Declaration alone does not establish effective authoring |
| Java RuntimeController | `insertComponent`/`createWire` return without construction; copy/paste/selectArea select a page and return | Installed implementation lacks effective content authoring on these paths; no adapter/RTX writer added |
| Runtime page creation | `doAddSubpage` contains implementation | Page creation alone does not establish controls or signal attachment; unexecuted |

See [actual validation results](VALIDATION.md) and [work-package status](IMPLEMENTATION_STATUS.md). General version/grammar qualification, live lookup/write/readback/restoration, graph acquisition and engineering acceptance remain unverified. WP-N04 signal acquisition is the next software stage; Runtime/rack trials still require their own authorized scope.

The final installed-copy read test passed ten cases with 37 protected files unchanged. The two empty layouts are available; all eight nonempty layouts remain partial. CH5 indmac retains 4 control records, 32 displays and 6 explicit graphs; CH6 gen1 retains 12 controls, 20 displays, 6 explicit graphs and 10 unsupported drawings. These counts include legacy duplicates. There is no claim that overlays were recreated or opened in the local app at this checkpoint.
