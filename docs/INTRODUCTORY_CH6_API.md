# Introductory Course through CH6: API reconstruction and Compile

Date: 2026-09-05. The user explicitly requested creation and compilation through CH6, retaining the API-only preference and prohibition on rack queries/reservation and Runtime execution. CH1's previously completed native construction/Compile was retained. This follow-up created and compiled all eight installed CH2–CH6 case variants below.

## Delivered cases

| Chapter | Case | Draft records excluding GROUP containers | Fresh Compile | Binary bytes |
|---|---|---:|---|---:|
| CH2 AC Power System | acsys1 | 57 | Passed | 160739 |
| CH3 Transformer | trans_ex | 62 | Passed | 146789 |
| CH3 Transformer | trans_ex_embBRK | 57 | Passed | 217289 |
| CH4 Instrument Transformers | ct_example | 52 | Passed | 133329 |
| CH4 Instrument Transformers | cvt_example | 43 | Passed | 134619 |
| CH5 Induction Machine | indmac | 77 + one GROUP | Passed | 283499 |
| CH5 Induction Machine | torque-spd | 40 | Passed | 145749 |
| CH6 Generator | gen1 | 135 + one GROUP | Passed | 292269 |

Models are retained locally under `AgentModels/IntroductoryCourse`, outside this repository. A local `README.md` links the exact final models, including the successful `indmac/area_attempt_03/working` and `gen1/area_attempt_02/working` candidates. Earlier failed indmac candidates are not deliverables. Vendor/native model files, transmission-line data, logs and binaries are not committed.

## Construction and comparison

This is **native template-based Draft reconstruction**, not independent component-by-component synthesis. Each vendor source was hashed and copied to an isolated snapshot alongside its local transmission-line companion files. The SDK opened that snapshot, created a new case with `new_case()`, copied the Draft through `ComponentCompatible.copy()`/native paste, and set/read back case timestep, title and real-time mode. Hierarchy contents and annotations were included. No GUI actions or direct DFX writes were used.

Both the reference snapshot and new candidate were saved through native save-as to absent paths, then closed. The reference's native save provides a version-normalized comparison; it does not modify the installed source. For all eight cases, the candidate's complete parsed Draft component type/parameter/orientation/mirror multiset matched the normalized reference. Relative component coordinates matched within each hierarchy context, preserving wire endpoint geometry. Generated UUIDs and uniform canvas translation are intentionally excluded from equality. This does not assert byte identity, absolute screen-position identity, equality of every case setting, or Runtime layout identity.

The current public parser rejects UUID-less GROUP containers in indmac/gen1. The private read-only verifier separately counts the containers and removes only their headers from the in-memory text before parsing absolute-coordinate child records. No model file is rewritten or parser behavior weakened. Group counts, child records and relative geometry matched in the final candidates. Full GROUP-aware public parser/editor support remains future work.

Each candidate was reopened by exact saved path, checked stopped/unmodified, and compiled once. All eight native calls returned `True`, and all eight fresh logs ended with `Compile completed successfully.` Error logs were empty and nonempty `_r1` binaries were created. RSCAD reported 2.7; compiler logs reported RTDSPC 6.7.3 with the pre-existing compile target configuration 1. The calls did not reserve or execute a rack.

Final verification rehashed 180 files across successful snapshot/reference/working directories, checked source and companion hashes, all 523 Draft records and relative geometry, and successful-attempt cleanup. All checks passed. The eight successful attempts recorded 2,154 allowed outgoing SDK requests. Each successful source/candidate/reopened case was closed without force and each SDK connection disconnected with `terminate=False`.

## GROUP and recovery findings

The first indmac attempt used the SDK's top-level component iterator. It returned 74 records and omitted the three children inside a GROUP. Exact record/group comparison detected the loss and blocked Compile. That failed saved candidate remains as evidence.

The next candidate used the documented `select_area()` followed by `copy()` to include the group. Native paste returned a `-1` group sentinel, and the public Python `paste()` wrapper attempted `get_object(-1)`, raising **after** native mutation. Paste was not replayed in that case. Recovery tried to identify the previously owned case; the SDK lookup returned no handle, and a subsequent exact old-handle read reported the processing object unavailable. The runner did not force-close or modify an unidentified tab. Cleanup of that intermediate unsaved candidate could not be independently confirmed across connections; do not equate an unavailable old handle with proven closure. No Compile or Runtime ran in any failed candidate/recovery attempt.

After reviewing that concrete wrapper failure, a fresh indmac candidate used the installed, source-inspected `_paste()` wire wrapper used by the public method. The local caller records the returned sentinel without trying to resolve it as a component and verifies the saved group/child records before Compile. This final candidate retained 77 records and one group and compiled successfully. The same approach retained the generator's 135 records and one group. The vendor SDK itself was not patched. This narrowly qualified workaround is not exposed as a public arbitrary operation.

## Scope and retained evidence

- No rack-query/reservation, Runtime run/stop/control/capture, load-flow invocation, or external I/O RPC was sent. Python loopback auditing does not measure background network traffic in the separate Java application.
- Transmission-line data came from the installed tutorial companions; no new TLine editor calculation was performed. Existing tutorial load-flow initializations were retained through component parameters, not recomputed.
- Draft Runtime overlays were not copied: normalized references contain 8–38 overlay records per case; candidates contain zero. Plots, sliders and meters on those overlays, simulation traces and electrical/dynamic acceptance remain unverified. Compile success alone does not establish them.
- CH1 remains the earlier independently inserted Voltage Divider case. CH2–CH6 are native template reconstructions. CH7 is outside this request.
- Private reproduction and evidence: `.validation/intro-ch6/inventory.py`, `inventory.json`, `build_case.py`, per-attempt JSON/console logs, reference/candidate record files, `verify_all.py`, and `verified-summary.json`. Failed journals remain separate from the successful summary. The local index points only to successful files.

Public changes are documentation only. No package API, dependency, default-inactive policy, grant mechanism, source protection, or Runtime restoration/cleanup implementation changed. The previously completed 317-test suite applies to unchanged application code; it was not rerun for this documentation-only checkpoint. Native reconstruction/Compile and artifact assertions were executed here. Source release scan, 81-file release integrity and whitespace checks were repeated before delivery.
