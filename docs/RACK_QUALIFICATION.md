# Rack qualification checkpoint — 2026-09-07

The owner authorized available-rack selection and confirmed that the selected rack was isolated from external equipment and physical I/O. A serialized, API-only task used fresh copies of the shipped introductory CH7 `script_example` case. **Compile passed; overall Runtime qualification failed because the compiled artifact changed during execution.** Actual start, array collection, stop and owned-case cleanup were observed separately.

## Observed results

| Check | Actual evidence |
| --- | --- |
| Installation and inventory | API 1.1; application reports exactly `2.7`. Racks 1–4 configured, only rack 1 available. The patch release is unknown. |
| Protected baseline | All 3,160 inherited source/evidence hashes matched before and after the live actions. |
| Stopped-copy discovery | Seven Runtime objects observed on `Tab1`: graph 58, sliders Length/Ron/FLTDUR and switches AG/BG/CG. No control writes. Exact file, saved rack 1, stopped/unmodified state and non-forced close/absence were checked. |
| Public Compile | Two fresh workflows, two successful Compiles. Each produced a 180,159-byte artifact with the same pre-run hash; source and companions stayed unchanged. |
| First Runtime attempt | The task wrapper omitted the documented exact `getSignal` call from its finite allowlist. It refused that lookup before `run()`. Close and disconnect were confirmed. Failure and consumed request retained. |
| Reviewed second protocol | A new workflow, Compile and single-use request added only the three approved signal lookups. One actual `run()`, one `update_plots()`, three array reads and one `stop()`. No fault, control setter, LF, rack-setting or hardware-I/O calls. |
| Samples | N3A/B/C each contain 4,000 finite, strictly ordered samples over 0–0.19995 s, at approximately 50 μs spacing. All 12,000 CSV rows retained. |
| Runtime cleanup | Running and subsequent stopped state observed; owned case 5 closed with `force=False`, returned true, then absent; disconnect completed. Cleanup errors empty. |
| Overall result | `runtime_failed`, `safe_completion=false`: compiled-artifact SHA-256 changed. The original model, isolated `.rtfx` and both line companions were unchanged. |
| Offline assessment | Workflow conversion correctly refused stale execution evidence. The exact recorded CSV was separately converted as supplied data and assessed for descriptive extrema only. Three channels passed data-quality checks; engineering verdict remains `not_evaluated`. |

The first wrapper's `completed` status means its invocation returned; it does **not** override the public Runtime failure. The independent audit reconciles this explicitly. The second wrapper stopped at nested hash revalidation before copying the independently successful production cleanup result. It conservatively left recovery markers in both its private data directory and the operator coordination directory. Those markers remain for operator review; their generic reason is not evidence that the simulator is still running. Both private and actual operator policies are inactive; the actual operator configuration remains absent/unmodified.

## Compiled-artifact mismatch

The file length stayed 180,159 bytes. Only offsets **127064, 127204 and 127344** changed, each ASCII `1` to `2`, in the NovaCor core-1 lower-L2 initialization data. The preserved artifact from the independent first Compile exactly matches the second workflow's recorded pre-run hash and supplies the before-byte reference.

- Before: `0c6192e3940b561dd072d9cb84c9b92bdeafec278a8f8345a22f2101ee2e4137`.
- After: `3c08e5665b61f9da9f9be1edbe3ac47b6056d8d772c67a66b565e7854cf372ef`.
- Raw CSV: `1b02e9b9e5aba24e519460ff5b2ff478d98e9e0505489c309c16445a2846cf14`.

The writer, parameter mapping and engineering meaning of these changes are unresolved. No mutation exemption, replacement hash, automatic retry or fabricated success was introduced. The next live qualification depends on explaining this initialization change and preparing a reviewed execution/artifact contract; it must retain exact before/after evidence and the existing source protections.

Observed phase RMS values are approximately **131.472560 kV** each. These are descriptive calculations from the failed workflow, without an acceptance threshold. Equal amplitudes, finite data or completed cleanup do not establish general electrical correctness, deterministic events, fresh/atomic acquisition or an authoritative simulator clock.

## Remaining qualification

Read-only inspection of all **167 installed `.rtfx` examples** found no saved graph meeting the existing named, unique-container native-acquisition conditions and no model with an accepted nonempty unambiguous saved input inventory. The inspected tutorials contain empty graph names and tagged/plain duplicate IDs. Live `Tab1` observations do not resolve the saved-format ambiguity. The parser and native/control gates remain strict; no Runtime authoring workaround was applied.

Therefore bounded control writes/restoration and the opt-in `native_signal_arrays`/`workflow_native` transaction remain unqualified. The older capture driver did read actual SDK arrays in this trial; that does not qualify the newer transaction. Model-native event scheduling and enabled legacy Runtime load flow remain unsupported before dispatch. GUI automation, rack security/power/configuration changes, hardware I/O and deployment were not attempted. Python RPC journaling recorded 168 calls, including one refused pre-run lookup; Java background traffic was not independently measured.

Private records are retained under ignored `.validation/rack-qualification-20260907`: read-only inventory, preparation, both protocols, raw SDK journals, source/companion/build artifacts, failed receipts, observed-run audit, numeric assessment, test logs and release evidence. Proprietary models, documents, raw samples, active configuration and recovery markers are excluded from Git.
