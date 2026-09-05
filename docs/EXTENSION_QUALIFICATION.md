# EXT-01 / EXT-02 investigation and software scope

Subsequent explicitly authorized local app tests are recorded in [LOCAL_RSCAD_QUALIFICATION.md](LOCAL_RSCAD_QUALIFICATION.md). The investigation and deferred-action table below preserve the earlier offline checkpoint; they are not the latest authorization state. Native unchanged-model open/read/save-as/reopen has since passed, while structural mutations, GUI binding, Compile and Runtime remain unqualified.

Read-only installed-source investigation: 2026-09-05. The user authorized local inspection, software implementation and isolated copies, and explicitly withheld all real RSCAD connection, Compile, Runtime and rack queries. No such operation was performed. Existing policy, grants, hashes and recovery behavior are unchanged.

## Observed evidence

The installed SDK `rtds/__init__.py` and the local `python/rscad-fx-python/doc/index.html` identify API 1.1. Source was parsed, never imported. The existing Runtime AST audit was also run against this installation: 24 checks passed. This is source compatibility evidence, not execution qualification.

`DOC/Release Notes.pdf`, pages 1-2, identifies the FX 2.7 family and documents component placement and draft-variable-dial changes. The launcher has no FileVersion/ProductVersion, and the JAR manifest inspected has no application version. The exact running FX patch version remains unknown; configured FX 2.7.3 is not substituted for an observation. No Java classes were decompiled or executed.

Additional local sources: `DOC/MISC/Draft_Find_Utility.pdf` and `DOC/MISC/Runtime_Window_Find_Utility.pdf`, each page 1; SDK module docstrings; API HTML anchors named in `inspect_extension_support`. Source hashes and method line ranges are captured in the local inspection report. No commercial source or PDF is copied into the package.

| Observed SDK file (relative to installed rtds package) | SHA-256 |
|---|---|
| `component.py` | `4730baa7070e52374f47b753de686a23534398818ae90afd1328d6d344fd6f6e` |
| `component_compatible.py` | `3c4489e12b4429c2dfe055cecd27a6fe75f41b43924a6996c8c0f9b87a34e200` |
| `case.py` | `b384a6926c828e42e8c5d1a75806bb13ec4bfb87058d1ba134eae8cb8e2a4c0d` |
| `rtx.py` | `5592163a700694b03f4885be7143f470b2c5644bb4f4b9961c5b18f54d60f446` |
| `rscadfx.py` | `66986cf95d0883931d7463393a98962eafe82f4c8bc472a6612bbe35a3b11bf6` |
| `comms/connector.py` | `473fd2c0696c8e1fe41ee0ff7ce32cc2d015770e9e8d42759af4d368a2df4da6` |

Local API HTML SHA-256: `47b399e238d69d727276893eebef592aa78a96757a2cfd3b62418e70fa71a1be`. These identify this read-only review, not all installations or future files.

## Native API findings and limits

| Operation | Confirmed source declarations | Consequence for implementation |
|---|---|---|
| Selector | `DraftComponent.set_parameter(param, val)`, `get_parameter(name)` | Connected operation; option semantics must be read from the exact definition. Only offline active-node impact is implemented now. |
| Insert / wire | `ComponentCompatible.insert_component(name,x,y)`, `create_wire(phase,coordinates)` | Remote wrappers; phase 1/3 is documented. Port meanings, collision rules, grid snapping and reopen/compile behavior require qualification before an executable adapter is exposed. |
| Copy / paste | `ComponentCompatible.copy(*components)`, `paste(location)` | Uses the application clipboard. An empty copy selection can use GUI selection. Do not treat it as an isolated file-copy API. No clone adapter is exposed. |
| Placement / selection | `DraftComponent.location`, `selected` | Getters/setters access the application. Placement may snap to the nearest valid grid. Disk coordinates are not screen coordinates. |
| Save / reopen | `Case.save(path)`, `RSCADFX.open_case(file)`, `Case.close(force=False)` | Save without a path overwrites; save-as writes a copy. Only future explicit candidate-path save is in scope. Do not save a running or unrelated case or force-close unsaved user work. |
| Case identity | `RSCADFX.get_case(file,caseid,open_file=True)`, `Case.file`, `State.modified`, `State.run_state` | Even identity/status properties are connected. Use `open_file=False` for a future lookup; no fallback opening without explicit scope. |
| Runtime objects | `Runtime.get_objects(comp_type,name)`, `get_object(comp_id)` | Connected typed lookup is documented; stored RTX IDs must still be matched to the actual case/subpage. Unknown units/control meanings are not fabricated. |
| Named signals | `Case.get_signal(name)` / `Runtime.get_signal(name)` | Exact named lookup exists. This is not evidence of a complete offline signal enumerator. |
| Graphics | `PlotSavable.save_data(...)` and `_graphic_saver.save_data(...)` | Plot export only. No reviewed Draft window screenshot or exact OS-window binding was found. Screen capture remains unsupported. |
| Connection | `RSCADFX.connect()` / `disconnect(terminate=False)` | SSL/TLS app requests; the SDK can invoke the executable and forward to an existing instance or launch one. Connecting is not an inert local read. |

## Implemented software

- `inspect_extension_support()` and CLI `rtds-agent extensions`: bounded AST/source/HTML evidence, signatures/decorators/line ranges, hashes, declared-versus-missing APIs and unqualified live state. No vendor import, process, connection, rack query, settings change or document upload.
- `preview_selector_change(request)`: strict [selector schema](../src/rtds_agent/schemas/selector_preview.schema.json); exact source hash, project snapshot, context/UUID/type and stored old/new labels. It reuses the existing definition and active-node parser, evaluates only in-memory component parameters, reports removed/added/changed nodes and affected existing nets. Unresolved conditions remain inconclusive; non-node semantics and dependency effects remain not_evaluated. No candidate RTFX is invented.
- `prepare_extension_trial(request)`: verifies the preview and complete current companion discovery, copies original bytes into separate source_snapshot/working folders, checks all hashes and atomically publishes an `extension_trial.json` with `prepared_unexecuted`. A failed copy leaves no completed trial. Trials are hidden from the normal published-project list. No changed model, SDK command execution, workflow approval or engineering pass is created.
- `inspect_runtime_layout(project_path,snapshot_id,offset,limit)`: bounded UTF-8 RTX header inventory with nested components, view/parent/record identity, stored names and signal references. It preserves duplicate UUIDs and unknown types as partial evidence. Plot internals, live units/current values, GUI/session state and target verification are not inferred. Its own snapshot binds the project snapshot and layout-parser bytes; use its returned snapshot for later pages.

This is real offline implementation, not a working live structural editor or GUI driver. Live application/round-trip, insertion/connection/clone adapters and exact window capture remain deferred or unsupported. No mock-success or execution bypass is public.

## Actual isolated local model observation

The licensed Introductory Course `CH7-Script/script_example.rtfx` was read under a dedicated temporary configuration. Its source SHA-256 is `87f3068f2db2d09ea4858b74db47ad0df86d24b95f833f5760c8d029849e191a`. The review target is context `subsystem:0`, Draft UUID 45, `rtds_sharc_ctl_SWITCH`, stored name AG, parameter Type, INTEGER to REAL.

The in-memory preview changes output IOUT/INTEGER to FOUT/REAL at the same local coordinate and identifies an existing three-member net requiring review. Thus this is not an innocuous string change. The isolated working copy remains byte-identical to the source; no candidate save exists. The trial manifest contains exact local paths and the proposed future operation, and is kept in ignored local validation data.

The same saved RTX contains 20 component records, including tagged/legacy representations with repeated IDs. The parser reports partial and preserves both; it does not declare a live target verified. Stored switch AG has UUID 68, distinct from Draft UUID 45. An eventual live lookup must resolve the actual case/subpage and validate that identity rather than taking a first match.

## Explicitly unexecuted next stages

These rows specify possible future requests; they grant no authority and are not runnable production tools.

| Stage | Exact target and actions to review | Conditions / excluded actions |
|---|---|---|
| App/session observation | The configured launcher and one operator-identified instance; connect, get_version, get_case for the prepared trial's exact working path with open_file=False; read file/modified/run_state | Permission must include the SDK's launcher/connection behavior. Do not open/close another case. No rack query, Compile, Runtime or control write. Exact OS-window capture remains unsupported. |
| Isolated selector round-trip | Explicitly open that trial copy if authorized; verify stopped/unmodified identity; Draft UUID 45/context/type/old Type; set_parameter Type=REAL; requery; save only to the manifest's absent candidate path; close only the owned saved case, reopen candidate; requery/diff/companions/connections | Requires separate authorization for editing and save-as/reopen. Preserve source_snapshot and working source bytes. Existing output connection/data-type impact must be resolved explicitly; no auto rewire. No compile/run. |
| Runtime target identity | On the same confirmed case, Runtime.get_objects using the documented SWITCH type and name AG; compare all returned IDs/subpages, including saved UUID 68 | Reads need connection permission. Duplicate saved representations are not proof of multiple live controls. Do not read/write current value, start Runtime or infer units unless separately scoped. |
| Compile qualification | Exact reviewed candidate hash and dependencies, exact version/API fingerprint, and an explicitly designated authorized rack/action | No rack has been chosen or queried in this task. Compile cannot proceed until those details and external-I/O assessment are supplied. |
| Runtime/control qualification | A separately authorized compiled case/rack plus exact signal/control meanings and restore/stop/cleanup plan | Outside this follow-up's authorization; no scheduler, automatic run or policy expansion was added. |

Record app/case IDs, observed version, saved/modified/run state, source/candidate/definition/companion hashes and every cleanup result locally during a future authorized trial. GUI window/hierarchy/selection evidence must be independently matched; disk files and plots cannot substitute for it.

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) and [VALIDATION.md](VALIDATION.md) for final measured tests and integration boundaries.
