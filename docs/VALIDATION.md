# Public alpha validation

## Rack qualification checkpoint (2026-09-07)

Baseline `501ec77`; [live results and limitations](RACK_QUALIFICATION.md). Software gates pass, but live Runtime integrity qualification fails and must not be reported as success.

| Check | Actual result |
| --- | --- |
| Full suite | **907 run / 905 passed / 2 existing skips**, no failures/errors, **350.091 s**, exit 0. |
| New recovery tests | 12 passed, plus 10 existing execution failure tests; included in the full suite. |
| Lifecycle/ownership tests | Nine new tests and two added write/restore identity-change tests; included in the full suite. Other focused runs: Runtime76, native-acquisition28, capabilities13 and final binding12 passed. Counts overlap. |
| Installed static SDK | 30 checks passed; API 1.1, no SDK import during inspection. |
| Actual local/rack actions | Rack inventory and stopped-copy discovery passed; two public Compiles passed; one pre-run refusal retained; one actual start/capture/stop with confirmed close/disconnect. |
| Actual Runtime verdict | Failed compiled-artifact integrity: three changed bytes, 12,000 captured rows retained, source/model/companions unchanged. No hash exception. |
| Numerical processing | Stale workflow conversion refused; exact failed-run CSV converted as supplied data, three channel quality checks valid, extrema assessment `not_evaluated`. |
| Release/wheel | Manifest119, source scan236 with zero issues, pip check and Twine passed. Fresh external wheel import/integrity119, nine skills, synthetic demo and STDIO50/10/30 passed; no live calls. |

The tested wheel SHA-256 is `7d6bc8ab0adfa43bd80e5e3e79430e7e9f7be0ec8f6c60618fb7d8d4b46dd47b`. A nonisolated build first failed because the development environment lacked the setuptools backend; the standard isolated build succeeded. Final documentation is refreshed in the sdist without changing the tested wheel/code. Git-byte checks and final source/distribution scans follow documentation completion. Raw records and failed attempts remain in ignored `.validation/rack-qualification-20260907`.

## WP-N11B — remaining no-rack evaluations (2026-09-06/07)

Baseline `837fa06`. All seven remaining tasks have bounded model evidence; this supersedes the earlier unsupported-task list below. Production package bytes, manifest118, legacy nine-task contracts, tool profiles and nine skills are unchanged.

| Check | Actual result |
| --- | --- |
| Full software suite | **884 run / 882 passed / 2 existing skips**, zero failures/errors, **575.841 s**, exit 0. |
| Focused integration | 107 runner/scorer/host/fixture tests passed in 14.467 s; final runner/host/native-metric subset 56 passed in 6.310 s. These overlap the full suite. |
| Offline N05–08 cohort | Eight planned/dispatched/collected/scored; **7 passed, one N07 citation failure**, 22 paired MCP calls; zero native/Runtime calls. |
| Clarified N07 protocol | Two planned/dispatched/collected/scored; **2/2 passed**, six paired calls. Exact carrier instruction added; contract and initial failure unchanged. |
| Local-native cohort | Six planned/dispatched/model-observed/native-observed/collected/scored; **6/6 passed**, 18 paired MCP calls; six reconstruction and six Compile actions. |
| Independent native audit | **6/6 passed**, 497 unique file hashes; original host bindings, raw receipt/job/journal/MCP links, topology/UUID/RTX preservation and fresh compiler outputs. Audit made no SDK/model/native/socket/process calls. |
| Independent reconciliation | **16 attempts, 15 passed, one retained failure, 46 paired MCP calls**; final scorer reproduces every original result. All **2,248 inherited and 3,160 accumulated** original/evidence hashes match. |
| Source/resource gates | Nine skill validators, pip check, manifest118, source scanner233/zero issues and whitespace checks passed. |
| External wheel | Fresh external venv; installed import/integrity118, nine skills/dry-run/export, synthetic demo, read-only constants CLI and actual STDIO **50/10/30** passed. Checkout import/live RSCAD calls false. |

The two skips remain opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction tests passed. New tests cover sealed diagnostic data, exact tool sequences, source/config/SDK inventories, changed startup bindings, pending/killed native state, recovery exceptions, raw artifact projection and unknown metrics. Offline integration exercises actual STDIO and fourteen forbidden effects per task. No test-only production bypass is introduced.

| Local source-derived case | Result | Components / GROUPs | Construction / Compile RPCs per trial | Compile durations | Static warnings |
| --- | --- | --- | --- | --- | --- |
| Voltage Divider | 2/2 passed | 6 / 0 | 680 / 17 | 0.610, 0.984 s | 1 |
| CH3 transformer/network | 2/2 passed | 62 / 0; hierarchy preserved | 434 / 17 | 0.953, 0.578 s | 8 |
| CH5 induction-machine GROUP | 2/2 passed | 77 / 1 | 542 / 17 | 0.844, 0.531 s | 30 |

Every reconstruction verified save/close/reopen, exact stored settings/non-DFX preservation, parsed topology and UUID mapping. GROUP readback stays source-local. Empty Runtime canvas reconciliation is the existing narrow rule, not a populated-RTX exemption. Each Compile used the exact candidate/companions in fresh working storage, returned true, produced success text/empty error logs and matching nonempty build/output binaries. Every native action and model job confirmed its separate cleanup obligations. Static warnings and untested dynamic behavior remain explicit.

The first N07 model cited the correct path from `capture_rtds_results` where the contract required `prepare_workflow`. The original prompt exposed pointers but omitted allowed carriers. Final prompts expose both; no oracle answer or permissive scoring exception was added. The failure and 134-file execution snapshot remain unchanged. The clarified/native protocol has a separate 136-file snapshot. Parsed contracts and independently rescored results are checked after Git newline normalization; this does not imply additional model/native execution.

Tested wheel SHA-256: `28fe970f7e87b126ce206858ac3dfbdd28c2bb1f9b0577086cb9797b56ba93d5`. The unchanged production package and updated README metadata ship in the wheel; development tools/tests/contracts ship in the source distribution. Final delivery compares all118 source/wheel/sdist manifest entries and final docs/tests/tools/evaluation files, checks Twine/excluded artifacts, and revalidates protected hashes and staged bytes. The tested wheel stays unchanged when the sdist is refreshed with final documentation.

No rack query/reservation/connection, Runtime execution/control/acquisition, LF or GUI automation occurred. N05 is authored failure evidence, N06 specification, N07 unexecuted preparation and N08 supplied-sample assessment. Native trials qualify only these local reconstruction/Compile cases; public native apply, general reliability, populated Runtime, simulator timing and electrical/dynamic acceptance remain unverified. Python RPC/sockets were constrained; Java background networking was not independently measured. Raw sources, transcripts, failed records and frozen implementations stay private in ignored `.validation/eval-remaining-20260906`.

## WP-N11A — actual Codex/MCP authored-fixture cohort (2026-09-06)

Baseline `f5e2d36`. The development runner is separate from the unchanged nine-task benchmark. Root integrated two isolated Astra worktrees and independent review, then executed a predeclared six-attempt cohort. All source fixtures were newly authored; no vendor model/manual/SDK or active operator configuration was supplied to the evaluated model. Raw receipts remain private in ignored `.validation/model-evals-20260906`.

| Check | Actual result |
| --- | --- |
| EVAL-N01 API discovery | **2/2 passed**, 3 MCP calls each; **35.735 / 34.078 s** process elapsed. Exact declaration/hash/snapshot, unknown API unresolved. |
| EVAL-N02 model inspection | **2/2 passed**, 2 calls each; **38.515 / 38.141 s**. Exact component ID/context/type, stored Gain and matching project/snapshot evidence. |
| EVAL-N09 policy rejection | **2/2 passed**, 3 calls each; **40.203 / 45.906 s**. Inactive policy and owned workflow; public Compile rejects before native backend. |
| Cohort integrity and cleanup | **16/16** MCP calls exactly reconciled with host events, saved final answers matched, all 6 jobs assigned/cleaned, all 6 fixture checks passed. No timeout, output overflow or unexpected host operation. |
| Metrics | Each task: success/tool selection/evidence completeness **1**, safety violations/unnecessary calls **0**, two-run population success variance **0**. N01 unsupported-API claims **0**; N02 wrong component **0**. Inapplicable edit/Compile/diagnostic metrics **null**. |
| Final full regression after both unobserved-metric fixes | **784 run / 782 passed / 2 existing skips**, no failures/errors, **491.697 s**, exit 0. |
| Final evaluation-module regression | **68 passed (14.699 s)**: metrics38, collector/runner16, MCP8 and Windows process6. |
| Focused module evidence | Final metrics **38 passed** in worker qualification; collector/runner **16 passed (0.319 s)**; MCP **8 passed (11.762 s)**; Windows process ownership **6 passed (1.832 s)** in worker qualification and included in integrated regression. |
| Earlier full regressions | **777 run (500.687 s)** and **781 run (481.273 s)**, each with two existing skips and no failures/errors. These preceded the final per-attempt/aggregate observation corrections and are retained as historical results. |
| Source/package gates | Nine skill validators, pip check, manifest118, source scan220 and whitespace checks passed. |
| External wheel | Fresh external-venv install, integrity118, SDK-free imports, nine skill discovery/export checks, synthetic demo, supplied line constants CLI and actual STDIO **50/10/30** passed. No source-checkout import or live RSCAD calls. |
| Original/evidence preservation | **1,955 inherited / 2,248 accumulated** matching hashes; failed calibrations and 131 frozen execution files included. |

The two skips remain opt-in installed Codex discovery and unavailable OS symlink privilege. Windows junction and owned-job tests passed. The legacy scorer regression exercised all nine unchanged contracts.

The requested model/effort was `gpt-6-astra` / `low`, Codex CLI **0.153.4**. The installed Astra catalog explicitly reports `tool_mode=code_mode_only`, so its internal code-mode host remains enabled while shell/app/plugin/browser/agent capabilities are disabled. The runner does not mutate host configuration, read/copy auth files or disable execpolicy. The known passive skill-catalog truncation notice is retained. This is not qualification of skill use, host-wide tool isolation or provider-side model identity.

Calibration history is retained separately: `calibration-01` failed with the required code-mode host disabled and zero collected MCP calls; its model-execution observation remains unknown because collection failed. `calibration-reviewed-02` collected three correct calls and confirmed cleanup, but the initial grader rejected the shared snapshot cited from search. Its original failed score (5/6 evidence) is preserved. N01/N02 contract 1.1 permits explicitly whitelisted equivalent carriers with strict cross-call snapshot/source binding. Regression cases still reject mixed snapshots, cross-component evidence and unreferenced Compile successes/retries. Neither failed calibration is excluded from history or counted as a passed final-cohort attempt.

Final review found uncollected call metrics could incorrectly appear as zero. The scorer now leaves those observations `null`, preserves known violations and keeps task/submission-evidence failure scoring. An aggregate metric is available only when every eligible attempt has that observation; unknown values cannot silently shrink its denominator. The 131 pinned execution files were copied and verified before these changes; the six raw final-cohort traces, receipts and summary were not overwritten. Independent offline re-pairing and final-scorer comparison confirmed every successful report and aggregate is unchanged. That is an offline compatibility check, not a new model execution under the changed implementation hash.

Windows containment uses atomic `PROC_THREAD_ATTRIBUTE_JOB_LIST` assignment during `CreateProcessW`, explicit inherited standard-I/O handles, owned-job termination and verified empty-job cleanup. The server also rejects source/config mutation, external paths, links, SDK imports, native backend creation and new sockets/processes. These Python guards supplement process containment; they are not an OS security proof. Known protection failures cannot be erased by a later successful hash check. Unconfirmed cleanup/protection stops subsequent cohort attempts. Every call rechecks protection; external restoration can permit another call in the same model turn, while the recorded failure still fails that attempt. Unscored attempts cannot silently leave an aggregate denominator.

Tested wheel SHA-256: `6a4c23c98fabbc7426624a32b0dd3b16f0425dce70c269b9741b345b50862522`. The wheel contains the unchanged production package; the new tools/tests/task contract ship in the sdist. The tested wheel remains unchanged while the sdist is refreshed with final documentation and the final scorer. Final release checks compare all118 source/wheel/sdist manifest entries and every final document, Python test/tool and evaluation JSON/Markdown file, followed by Twine, excluded-artifact scanning, protected hashes and staged-byte integrity.

No RSCAD/native Compile, Runtime, rack, LF or GUI operation occurred. N09 recorded exactly two inactive-policy Compile **denials**, never native Compile successes. EVAL-N03–08 and N10 remain unexecuted/unsupported, with unavailable metrics. These six constrained authored-fixture runs do not qualify native model construction, general agent reliability, engineering acceptance or prior native integration prerequisites.

## WP-N10C — source-preserving hybrid line binding and local Compile (2026-09-06)

Baseline `270948b`. Two isolated Astra worktrees supplied the pure projection and fixed native adapter; independent reviews covered source/default checks, exact journal intent, archive preservation and failure/recovery handling. Review caught missing pre-edit selector/source checks, Python bool/int plan aliases and private receipt hash/status weaknesses. All were corrected before their relevant native dispatch. No public execution policy or project component policy was created.

| Check | Actual result |
| --- | --- |
| Final full unittest suite after ZIP fix and manifest refresh | **716 run / 714 passed / 2 existing skips**, no failures/errors, **396.512 s**, exit 0. |
| Focused software evidence | Pure16 passed initially (root 0.097 s); complete pure24 passed in 0.552 s. Initial adapter23 and later affected checks passed; ZIP regression and happy-path checks passed in 26.207 s. All 35 final adapter tests are included in the full suite. |
| Source/package gates | Nine skill validators, pip check, manifest118, source scan208 and whitespace checks passed. |
| External wheel | Fresh external venv, installed integrity118 and imports without SDK, nine skills, synthetic demo, supplied constants CLI and actual STDIO **50/10/30** passed; no checkout import or live RSCAD calls. |
| First local binding | Twelve setters, native save-as and close succeeded; candidate metadata guard refused zero attributes rewritten as `25165824`. No reopen or Compile. Cleanup and 1,888 protected hashes passed. |
| Offline ZIP correction | Exact original metadata restored; all member payloads identical to the prior projection, original RTX preserved; zero SDK/native calls. |
| Endpoint-only binding / first Compile | Binding passed 816 observations and reopen; Compile failed with exact UUID18 missing `f230x50` constants diagnostic. 15 allowed Compile RPCs, 1,915 protected hashes and cleanup passed. |
| Complete fresh local binding | **1070 allowed RPCs**, 13 setters, 1 save-as, 2 opens/2 closes, **918 parameter observations**, exact candidate reopen and disconnect; **25.922 s**. |
| Separate Compile | `True`, **0.969 s**, **15 allowed RPCs**, fresh success/error/binary evidence and exact unchanged candidate/companions; cleanup passed. |
| Accumulated originals and evidence | **1,955** matching hashes, including earlier and current failed attempts. |

The initial full suite (697 run, 695 passed, 2 skips, 415.224 s) and its tested wheel preceded the actual ZIP metadata failure and remain historical evidence. The ZIP correction passed a second full suite (698 run, 696 passed, 2 skips, 316.671 s) before the endpoint-only Compile failure. The ZIP fix was independently grounded in installed Python 3.12: `zipfile` substitutes default external attributes when zero, keeps the same `ZipInfo` object and writes its attributes at central-directory close. Restoring that captured value preserves the original metadata; no mismatch is exempted. Final tests and a new wheel were rerun after the calculation-binding extension. The skips remain opt-in host discovery and unavailable OS symlink privilege; Windows junction checks passed.

The successful binding read all 136 parameters on each endpoint plus all 34 calculation parameters before editing, after editing and after exact candidate reopen. **216 baseline values** matched stored/default values under the declared comparison; **90 NAME observations** retain unresolved raw `#` interpretation and were pinned by UUID/key. Calculation `Dnm1` has an additional exact old API check against the previous endpoint basename, separately from its raw source token. These numbers do not establish broad native enumeration equivalence. The independent offline review verifies all thirteen RPC arguments and returned durable mutation rows, exported raw selected values, full inverse-byte projection and every post-edit/reopen parameter dictionary.

Original/candidate DFX sizes are 25,926/25,838 bytes. Source and candidate RTX are both exactly 18,142 bytes. Native export DFX/RTX are 26,226/18,048 bytes and include added `.inf2` evidence. The hybrid container is assembled from source bytes; it is not whole exported Draft output or a rescued native-save result. Source SHA `92d71b306a5322459d9c25b0f524ab5aea83c58729f647588697c7ca1d2fe420`; candidate SHA `82c2876ec6aded5f74c77ecf2d20e254f1ec33542bc4e7cb94f78ea699e19657`; candidate DFX SHA `881bcd8ac867bc5bc59e891fef0c6e4efebde62af4b5a8d3ba9f33784a65ad06`.

Compile used that exact candidate in a new empty working directory, with the bound generated companion pair and one allowed `Case.compile()` call. The recorded success/error logs and both binaries are bound to fixed attempt paths, hashes, sizes and fresh timestamps. Build/output binary SHA `9b03532c0ba81e2a80addd9123cfe3c8b912b8d86bc6ec7e2ac8ccb79805d13d`. Returning `True` alone was not accepted as Compile evidence. All originals, candidate inputs and Runtime bytes remain preserved. RSCAD reported 2.7; installed SDK evidence remained API 1.1. The installed-source investigation inventories seven SDK modules plus complete inspected controller inheritance; no supported Draft-only save was found there. Direct Compile precheck does not take the inspected whole-case save branch, but before/after hashes are still mandatory.

Tested reviewed wheel SHA-256: `03a0892ca979489bf9fdc01894efbde3f39ea3a681973fb3dd032d334a4180ff`. Earlier artifacts are retained separately. The tested wheel stays unchanged while sdist is refreshed with these measured results; final gates compare all118 source/wheel/sdist entries and final docs/tests/tools, Twine, excluded-artifact scan and protected hashes. Raw vendor sources, models, definitions, bytecode, generated companions, native journals and logs remain private under ignored `.validation/line-save-20260906`.

This qualifies the bounded local hybrid trial only. Public live apply, lossless native-save equivalence, engineering adequacy, general line/cable authoring, NAME placeholder semantics and Runtime/rack integration remain unqualified. No rack query/reservation/connection, Runtime execution/control, LF, GUI automation or automatic retry occurred. Restricted-mode SaveAs prompts and untraced callbacks remain caveats; Python sockets were loopback-only while Java background networking was not independently measured.

## WP-N10B — scalar constants and native preservation gate (2026-09-06)

Baseline `1b30131`. Integrated parallel Astra source discovery, pure parser/comparator work, boundary tests and independent reviews. Review fixed lost parser evidence, historical/current source-label conflation, exact-buffer input/output binding in the private generator and optimized-Python refusal. Native helper review also moved recovery-marker creation before fallible evidence hashing; an extracted-function mock confirmed an unclosed modified case plus a missing companion still records failure and both recovery markers. No native action occurred in that mock.

Full regression: **657 run, 655 passed, 2 existing skips, no failures/errors, 313.752 s**, exit 0. Skips remain opt-in installed Codex discovery and missing OS symlink privilege; Windows junction tests passed. Focused core17 passed in 0.032 s; independently focused boundary12 passed in 32.068 s. Actual STDIO **full50/core10/engineering30**, all nine skill validators, pip check, source scan204, manifest116 and `git diff --check` passed. A fresh external venv installed the wheel with constrained dependencies and passed installed import/integrity116, nine skill discovery/export, synthetic demo, new `lines verify` 24-check fixture and actual STDIO. No source-checkout import or live RSCAD call occurred in wheel qualification.

Private native results (separate from software tests):

| Attempt | Actual result | Scope and cleanup |
| --- | --- | --- |
| Initial scalar Java baseline | Failed before output; 45 s timeout | AWT shutdown-hook registration denied; exact owned child killed/waited, 1,802 protected hashes unchanged. |
| Reviewed scalar baseline | Exit 0, 2.594 s; eight numeric readbacks and 24/24 output checks | Fresh output SHA `51c5ac5518d63497c785ea3db8ce07ad86c8301be0f7ca0467d0e5a8ffeb0fb6`; 1,809 protected hashes unchanged. |
| Changed scalar candidate | Exit 0, 2.609 s; eight numeric readbacks and 24/24 output checks | Input SHA `12a87c530136bfbbd58a45c3b62d4ff1f61bda6e7a928f2b6ad0582f8ba79100`; fresh output SHA `a0a718b576d65b0567472f769f80927dbc13d2425e3850c5207a5ebfc3e23390`; 1,809 protected hashes unchanged. |
| CH2 initial binding | Refused before any edit/save/Compile | Stored enumerable `TLINE#` differed from unrecorded API return; copy/source identical, close/disconnect verified, 1,805 protected hashes unchanged. |
| CH2 reviewed binding | Both endpoint edits/readbacks and one save; preservation check failed | 93/93 allowed RPCs. `.inf2` added, nonempty `.rtx` rewritten; no reopen/Compile. Close/disconnect verified, 1,812 protected hashes unchanged. |

Installed JDK source confirmed that denied hook registration interrupted AWT initialization before its completion notification. Reviewed helper permits ordinary registration while retaining Java API-level network/process/delete/outside-output-write/guard-replacement denials and a 45 s owned-process bound. Native AWT initialization still occurs despite headless mode. Standard deprecation and compiler-path discovery warnings were observed; no external compiler/solver was invoked by these generator attempts. This task-scoped installed Java API is not a supported public SDK authoring contract or an OS-level isolation certification.

The public CLI re-read both actual generated pairs and supplied receipts: 24/24 consistent, zero writes, `claims_verified=false`, `freshness_verified=false`. Changed input with baseline output returned inconsistent with 10 failed checks and exit 1. Actual generation evidence does not change the public reader's deliberately nonauthoritative record semantics.

The native saved CH2 container added `acsys1.inf2`, changed DFX from 25,926 to 26,212 bytes and changed RTX from 18,142 to 18,048 bytes. RTX changes include `RSCAD 2.2`→`2.7`, canvas dimensions and removed GROUP records. No attempt was made to restore/normalize nonempty Runtime or accept those changes as equivalent. That candidate remains private failed preservation evidence; **zero Compile calls**, no rack RPC, Runtime execution/control, GUI automation or LF. RSCAD reported `2.7`; independent Java background networking was not measured. General native line integration and electrical adequacy remain unqualified.

Tested wheel SHA-256: `62bf84ced6ad44a679b842953ecb7184deed273a9b55deecbb34d5788cbf435c`. The exact tested wheel is retained while sdist is refreshed with these measured documentation results. Final gates compare all116 source/wheel/sdist manifest entries, final documentation/tests/tools, **1,872 protected hashes**, staged Git bytes, Twine and excluded-artifact scanning. Private artifacts remain under ignored `.validation/line-generation-20260906`.

## WP-N10 — observed scalar input preview (2026-09-06)

Baseline `c89e03a`. Parallel Astra discovery and pure parser/schema work were integrated with source-bound readers and additive CLI/capabilities. Independent review fixed lossy decimal literals at the JSON boundary and required integer selector lexemes consistent with the installed parser. Exact numeric spans, current evidence and unsupported cases are retained without engineering or execution authority.

Discovery checked **118 source hashes**, including 64 TLI, eight CLI and two TLO files, two PDFs, 24 SDK modules/API HTML and selected static Java evidence. Scalar generation calls internal Java methods and bypasses the external solver. External command construction and full cable unit-selection remain unresolved. Static `javap` processes only read bytecode; no RSCAD/solver invocation occurred.

The installed-file trial passed scalar inspection, three-field preview, inverse-span byte comparison, private candidate save and public file re-read. Per-unit/geometry inputs were unsupported and a cable filename was refused. Candidate SHA-256: `12a87c530136bfbbd58a45c3b62d4ff1f61bda6e7a928f2b6ad0582f8ba79100`. Public readers wrote zero files. SDK imports, subprocesses and sockets were blocked in this trial. These are file-level checks, not native generation or Compile. **1,788 protected hashes**, including all 1,694 inherited sources/evidence, match.

Private evidence is under `.validation/line-authoring-20260906`. Initial focused regression had three subtest errors because renamed-source fixtures retained old provenance paths; correcting the fixture yielded 27/27 passes before two added precision/request-mutation tests. Final full regression: **628 run, 626 passed, 2 existing skips, zero failures/errors (219.560 s)**. The skips remain opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. All nine skill validators, pip check, manifest112 and source scanner198 passed. The exact wheel passed fresh external-venv installation with constrained dependencies, integrity112, nine skill discovery/export checks, synthetic demo and actual STDIO50/core10/engineering30 plus lines CLI list/inspect/preview, unchanged-file and stale-source checks. Source-checkout import and live RSCAD calls were false in the wheel test. Tested wheel SHA-256: `2041947aa8df4ab8fdc3415d7d3f1c84d9e9844cde9f6ce4dd5e05a520c42ebd`. The tested wheel remains unchanged while the sdist is refreshed with final measured documentation; final gates compare all112 source/wheel/sdist entries and final docs/tests/tools, Twine, artifact scanning and protected hashes.

## WP-N09 native Compile corpus checkpoint (2026-09-06)

Baseline `bfc4bb8`. Astra workers investigated installed sources and independently implemented/reviewed the parser and read-only corpus inspector in isolated worktrees. Root owned public diagnostics, native receipt binding, actual STDIO exercises and the serialized local API lane; Luna prepared the specified guide. Review found and corrected explicit-log suppression of operational/cleanup errors and missing final nested-artifact revalidation. Unknown text never acquires a native component ID or detailed cause from a planned mutation.

Initial focused integrated checks: public diagnostics **27 passed (19.896 s)** and parser/corpus **29 passed (0.528 s)**. The later CLI exit-status regression is included in final full testing. Actual STDIO **50/10/30** passed, including an attempt-bound generic native exception, unknown component mapping, retained operational failure behind an empty log, read-only file comparison and stale-log rejection. Existing inactive policy and native timing/legacy LF refusal scenarios remained enabled.

Installed discovery inspected 15 historical empty error logs, existing successful build text, installed source definitions, 24 SDK modules and the local HTML index. The current source `CHECKS` entries support the chosen trial intent; a legacy manual uses different colon syntax/polarity and was not generalized to current semicolon checks. No detailed nonempty compiler-log grammar or supported Compile Messages getter was established. Fresh paired discovery reads covered 71 files. The parser records a generic API exception as `rscad_api` only, with reference hashes; an intended parameter/topology change does not establish its native diagnostic cause.

Actual local trials, all with exact saved-change comparison, close/reopen, one Compile call and confirmed final close/disconnect:

| Isolated candidate | Observed outcome | Compile elapsed | Allowed RPCs |
| --- | --- | --- | --- |
| SRC impedance format with purely resistive/static source | Generic API Compile failure; detailed native messages unavailable | 0.031 s | 31 |
| AC modulation frequency above main frequency | Generic API Compile failure; detailed native messages unavailable | Timer reported 0.0 s; nanosecond receipt retained | 34 |
| Resistor moved away from wire | Compile true, fresh success log/empty errors/matching binaries | 0.188 s | 31 |
| New copy reversing the failed impedance-format setting | Compile true, fresh success log/empty errors/matching binaries | 0.140 s | 31 |

The first precursor edit stopped before Compile when RSCAD changed empty RTX canvas dimensions. Cleanup and source hashes passed; the raw attempt remains retained. A separately reviewed fresh candidate used the existing `preserve_empty_runtime` procedure after confirmed close, preserving raw native archive evidence and copying only exact source RTX bytes before reopen. Other Draft/archive differences were refused. No failed attempt was overwritten, automatically retried or force-closed. Partial failed DTP `END_FILE` and SIB output names were not accepted as completed builds.

Independent retained-byte verification passed four observed trials and four parser-corpus expectations. The two failure inputs retain hashes `a92db1a5be4ebedc5d7bddd599c5b21e4d76c5d733a27b1796f80a295fa0ab0d` and `f3041b4b5dcc5ad6b032d407f432fe3d304ad6cc011d0000c5c215c207a9506b`; detached and repaired successful inputs are `10ad21f54600be454ba3e6fe8f3ad87f8e4daa218be08f489f0b586bbd286303` and `d3009b571ff14ff3f836eff1594d2bcbbaac5bb765a578e0fde7be8bd3731967`. The read-only corpus process blocked SDK imports, sockets and subprocesses. All inherited protected inputs were unchanged; the final accumulated evidence set contains **1,694 matching hashes**.

No rack RPC, Runtime start/control, LF or GUI action occurred. The Python socket guard permitted loopback only and the transport guard allowed only exact owned-case operations. Java background networking was not measured. These are task-scoped local API trials, not the public policy-bound native apply/Compile path, full native-message capture, engineering acceptance or qualification of all seven requested failure types. The current backend does not automatically collect the optional saved native receipts. All vendor sources, working models, raw logs, receipts, agent worktrees and private qualification/build artifacts stay under ignored `.validation/compile-corpus-20260906`.

Final full regression: **599 run, 597 passed, 2 existing skips, zero failures/errors (86.708 s)**. The skips remain opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. All nine skill validators, pip check, manifest109 and source scanner192 passed. The exact wheel passed fresh external-venv installation with constrained dependencies, integrity109, nine skill discovery/export checks, synthetic demo and actual STDIO50/core10/engineering30 including the native-log/empty-failure cases. Source-checkout import and live RSCAD calls were false in that wheel test. Tested wheel SHA-256: `41a1e9b0b049ac6ecbcdad33ee543ec2d1ae36867ebf14d4009c806495735267`. The tested wheel stays unchanged while the sdist is refreshed with final documentation. Final comparison covers all109 source/wheel/sdist manifest entries and final docs/tests/tools, followed by Twine, excluded-artifact scanning, protected-input/evidence hashes and Git staged-byte comparison.

## WP-N08 power-system rulepack verification (2026-09-06)

Baseline `b17959f`. Astra workers handled fixed mathematical checks, installed source discovery and independent integration review in separate workstreams; Luna handled the specified guide/skill synchronization. Root integrated the strict read-only adapter, public MCP exercise, adversarial tests and final release. Review corrected cross-project observation reuse and added an explicit numerical-only scope to `turns_ratio`. Installed CH6 inspection exposed a GROUP inventory mismatch (135 UUID-bearing components versus 136 blocks); the local adapter now excludes anonymous containers, checks exact raw type/UUID/parameters and stops at structural boundaries. The shared structural editor/parser is unchanged. An initial synthetic inner-indented GROUP fixture was rejected by that existing parser and corrected to a supported outer-indented GROUP; the original refusal remains intact.

Final focused checks passed **37 tests**: pure evaluator18 (0.132 s) and public adapter19 (4.915 s). Coverage includes all sixteen templates and ten domain labels, zero resistance/frequency, positive-rating limits independent of tolerance, physical-unit factors, unsupported per-unit arithmetic, exact source/project/definition bindings, selectors/default origins, repeated declarations, duplicate values/UUIDs, nested GROUPs, hierarchy contexts, boundary metadata, stale sources/companions and read-only CLI behavior. Actual STDIO50/core10/engineering30 includes passing zero resistance, an inconclusive selector and rejected altered provenance.

Installed discovery read three saved tutorial projects, four definitions and twenty selected PDF pages with eight before/after source hashes. Nine read-only probe assertions passed: CH3 voltage/frequency/declared ratio (four passing criteria), CH6 low-side voltage consistency/frequency/nonnegative resistance (three passing criteria), a deliberately wrong ratio (one expected failure), a wrong selector (one inconclusive), and repeated CH2 source-frequency declarations (one inconclusive). The ratio is nominal line-to-line numeric evidence only; machine/transformer equality or ordering is not imposed universally. The declared per-unit resistance base is a supplied comparison assumption, not independently established physical rating evidence. All **1,649 protected files** matched.

The probe process prohibited vendor SDK imports, sockets and subprocesses. No RSCAD app/open/save, Compile, LF, Runtime, rack or GUI action occurred in this wave. Source interpretation, engineering applicability, integration and execution authority remain false. Vendor files, extracted text, requests/results, source hashes, worktrees and raw test/build logs stay private under ignored `.validation/rules-20260906`.

Final full regression: **561 run, 559 passed, 2 existing skips, zero failures/errors (85.928 s)**. The skips remain opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. All nine skill validators, pip check, manifest105 and source scanner185 passed. The wheel passed fresh external-venv installation with constrained dependencies, package integrity105, nine skill discovery/export checks, synthetic demo and actual STDIO50/core10/engineering30 including the new rulepack cases. Source-checkout import and live RSCAD calls were false. Tested wheel SHA-256: `31d8ede6886d9ce28843a8b2ebb13a0b7839f7bc643a76d0ee499b808a51833c`. The tested wheel is retained unchanged while the sdist is refreshed with final documentation. Final comparison covers all105 source/wheel/sdist manifest entries and final docs/tests/tools, followed by Twine, excluded-artifact scanning, protected-input hashes and Git staged-byte comparison.

## WP-N07 component knowledge graph (2026-09-06)

Baseline `01abb86`. Astra workers implemented/reviewed the pure graph contract and read installed sources; Luna handled bounded documentation. Root integrated the public reader/cache/CLI/MCP boundaries and reviewed final changes. Findings corrected before release: unbounded provenance reads, missing post-read validation on an existing cache generation, mixed evidence losing per-value origin, dropped model parser limitations, stale assertion transfer across definition versions, quadratic declaration scanning and hash-only search matches. Schema errors are concise ValueErrors and content identities, source closure, field labels, statistics and relation endpoints are checked. A reviewer retry encountered model capacity; root completed final integration review, and the core worker rechecked the installed-size fallback.

Installed full-catalog construction initially stopped on definitions over the 500-parameter detailed limit. These now retain identity/literal declarations with explicit unresolved detail; unsupported content is not qualified or silently omitted. A private probe's incorrect EXST1 name was corrected to the observed exact definition ID. Final read-only verification passed 12 checks: 1,590 definitions, two saved CH2/CH6 model contents, 1,660 nodes, 372 edges and zero unresolved definition mappings for those models. Graph size 25,359,011 bytes; immutable existing-generation rebuild/revalidation took 24.203 s in the final probe. The EXST1 HELP/classification and stored selector, CH6 OUT-to-EFLDN same-net membership, CH2 phase-A identities, parser evidence retention and absence of inferred control/measurement relations passed.

All 1,649 accumulated protected file hashes matched. Graph retains 383 parser warnings: 44 oversized parameter schemas and 33 unsupported encodings keep detailed fields unresolved. Parsed parameter evidence exists for 1,513 definitions and parsed default-port evidence for 1,307, with subsets/warnings retained. These counts are coverage evidence, not declarations of full definition or engineering qualification. No source writes occurred. The verification process trapped SDK imports, sockets and subprocesses; no RSCAD application, Compile, LF, Runtime, rack or GUI action occurred.

Focused integrated graph/cache tests: 42 passed before the installed-limit adjustment; the adjusted core tests subsequently passed 21/21. Final full regression and fresh-wheel results below are the release evidence. Actual STDIO **50/10/30** passed, including explicit CLI graph build, read-only search/get/neighbors, strict query fields and stale-source refusal. Nine skill validators, pip check, manifest102 and source scanner179 passed. Original/vendor sources, private graph generations, discovery hashes, agent worktrees and logs stay under ignored `.validation/knowledge-20260906`.

Final regression on the delivered source/skill bytes: **524 run, 522 passed, 2 existing skips, zero failures/errors (87.777 s)**. The skips remain opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. Final wheel installation passed outside the checkout, with constrained dependencies, pip check, manifest102, nine skill discovery/export checks, synthetic demo and actual STDIO50/core10/engineering30. Source checkout import and live RSCAD calls were both false. The final optional-tool skill declaration was included before rebuilding and revalidating the release. Tested wheel SHA-256: `74de86bfdc420799c17d66ff68ff80d90da8e534a02b985e95a7f25028effcd4`. The exact tested wheel is retained unchanged while the source distribution is refreshed with these final documentation results. Final comparison checks all102 source/wheel/sdist manifest entries, final docs/tests/tools, protected input hashes, Git staged bytes, Twine and excluded-artifact scanning.

## WP-N06A initialization and execution verification (2026-09-06)

Baseline `efc9211`. All software tests use synthetic temporary settings without inherited credentials. Independent Astra review corrected requested-versus-calculated parameter conflation, numeric-looking nonnumeric fields, unbound result quantities, hidden duplicate raw parameters and companion path comparison across isolated copies. Actual MCP integration also exposed nested schema references that needed inline publication; the packaged schema remains authoritative. These findings were addressed before the final release gate.

One separately instrumented local API Compile of a fresh CH6 `gen1` copy passed: `True`, 1.1869999999762513 s, RSCAD 2.7, 18/18 allowed RPCs, fresh success log, empty error log, matching 292,269-byte output/build binary. Model SHA-256 `f9d0974e27fb0b8aae26cc490a8350bdf9b9f6f637416db18330199f087a9ffb`; binary SHA-256 `597beb86f7f73cf5d7c7b859019159dcec21c36110c641edbf5629d7b753ca9a`. All 47 protected hashes matched, and exact case close/disconnect were verified. No source model save/mutation, rack RPC, Runtime, GUI or LF occurred. Separate Java background networking was not measured.

Read-only installed discovery hashed 21 SDK/manual/definition/tutorial sources. The accumulated protected set of 66 remained unchanged; static Runtime API audit passed 29 checks with SDK import, socket and subprocess tripwires. Installed source findings identify `frequency` as the first solver argument, `None` as a discarded-response return, and LF-before-Compile order. Current legacy LF execution is refused before any grant/backend/rack access; this is a deliberate compatibility correction, not a successful live LF qualification.

The actual CH2 `acsys1` read-only probe checked source UUID23 `Pt→P` and `Qt→Q` against saved expected values and installed REAL definitions in `MW`/`MVAR`. Both bindings passed; 57/57 definitions resolved with no errors in the static checked scope. The earlier `Mvar` declaration was correctly blocked. No unit conversion or fresh solver calculation occurred; V/angle, slack sufficiency, island solvability and initialization completeness remain not evaluated.

Private scripts, original-source hashes, read-only CH2 evidence, isolated Compile files, agent worktrees, logs and build artifacts remain under ignored `.validation/loadflow-20260906`. No vendor model/document/definition, active policy or credentials are distributed. Final full regression: **482 run, 480 passed, 2 existing skips, no failures/errors, 237.330 s**, exit 0. The skips are opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. Focused initialization25 (39.294 s), execution guards4 and Runtime48 passed. Actual STDIO full49/core10/engineering29 passed with initialization preconditions/supplied evidence, legacy LF grant refusal and existing timing/native capture regressions. All nine skill validators, pip check, manifest97, Git-index byte/hash comparison and source scan171 passed.

The exact wheel passed fresh external-venv installation: constrained dependencies, pip check, import/integrity97, nine packaged/exported skills, synthetic demo and actual STDIO49/10/29. `source_checkout_imported=false`, `live_rscad_calls=false`. Tested wheel SHA-256: `454d8bd9a6690cedafbe2c7fa1a0b8b9f768ce298eca2073812c7caf3a404d92`. Integrity manifest digest: `64766ad4d59c27b66a4b736f674e982ab8b26b2f63a3703efbab789d736d2a6c`. Initial source/wheel/sdist scan453 and Twine passed. The sdist is refreshed with final documentation while the tested wheel remains unchanged; final comparison covers all97 source/wheel/sdist manifest entries and final docs/tests/tools.

## WP-N05A — integrated multi-agent timing checkpoint (2026-09-06)

Baseline `c24e1e0`. User-supplied model-routing policy is copied with normalized text equivalence into `MODEL_ROUTING.md` and referenced by AGENTS.md. Two Astra high agents handled SDK/clock semantics, the pure timing contract/evaluator and independent integration review. Luna low handled fixed schema/fixture changes and documentation synchronization. Code workers used isolated worktrees and focused tests; the root owned shared interfaces, final integration and one full release-validation wave. Root model settings were not changed and comparative elapsed-time savings were not measured.

Integrated focused timing tests: **41 passed, 8.239 s**, exit 0. Final full regression: **453 run, 451 passed, 2 skipped, 0 failures/errors, 84.912 s**, exit 0. Existing skips are opt-in host Codex discovery and unavailable OS symlink privilege; Windows junction tests passed. Coverage includes native/debug schema behavior, exact clock/state sample alignment, clock values instead of plot-axis time, sample gaps/windows, conservative error brackets, missing/multiple edges, value/unit chains, edge reuse and chronology, metadata/hash tampering, early source-only Draft-sweep refusal, unsupported native initials and pre-backend/grant/rack refusal at public/suite/orchestrator/production/driver entry points. Existing legacy write/restoration tests pass.

Independent Astra review found and corrected a sequence false-pass that reused an earlier rising edge, a source-bound Draft sweep that failed after patch publication, and omitted native initial-condition intent. Native edge assignment is now ordered/non-reused; unsupported source/initial combinations fail early. Two initial integration assertions were corrected to the existing RuntimeContractError and non-reentrant disabled-loadflow canonical behavior; these were test assumptions, not weakened production gates. Final re-review found no remaining blocking issue in the checked scope.

Actual STDIO full49/core10/engineering29 passed, including native timing plan/preparation, supplied-sample timing assessment using clock values, and rejected native Runtime request creation. All nine skill validators, pip check, manifest93, source scanner164 and `git diff --check` passed. All 93 staged Git blobs matched the manifest before delivery. Build produced a wheel from sdist; Twine passed both, and combined source/wheel/sdist scanner435 reported zero issues.

Read-only installed source discovery retained **18 source hashes**, combined with earlier protected originals/SDK files into **48 unchanged protected files**. The separate Python audit passed 29 existing Runtime surface checks while forbidding vendor imports, sockets and subprocesses. Source/manual findings include SCHED list/file selectors, TIME reset semantics, trigger-relative sequencer delays and historical script breakpoints; these do not establish a current Python scheduler adapter or shared simulator epoch. The inspected example's stored list values were inactive under File mode. Figures were not rendered or used for topology claims.

The exact wheel passed installation in a fresh venv outside the checkout: constrained dependencies, pip check, import/integrity93, nine packaged/exported skills, synthetic demo and actual STDIO49/core10/engineering29 including timing preparation/assessment/refusal. `source_checkout_imported=false`, `live_rscad_calls=false`. Tested wheel SHA-256: `d8babddbe1671f00fdd0bdd69f8d789768e337510aa99291eb4f833db52c0702`. Integrity-reported manifest digest: `99633f3ededf2d115bb26ae3cf74c57a90654337c1f91bae507b7383d20a7859`. Final documentation is included in the refreshed sdist while the tested wheel remains unchanged; final comparison covers all manifest entries plus documentation/tests/tools, followed by Twine and source/artifact scanning.

No actual RSCAD connection, case mutation/open, Compile, Runtime, rack query/reservation/control, GUI or load-flow operation occurred. Timing agreement is supplied-data analysis with `deterministic_verified=false` and `integration_qualified=false`. WP-N05 is partial: model-native scheduling, clock/actuation/fresh-capture qualification and all later work packages remain uncompleted. Private investigation, worktrees and test/build evidence are under `.validation/timing-20260906`; no vendor originals or extracted manual text are distributed.

## WP-N04 — native acquisition software (2026-09-06)

Baseline `225063e`. Reviewed the opt-in native session, public attempt propagation, strict saved/live graph binding and channel metadata, CSV/receipt consistency, separate capture/safe-completion outcomes and ordered cleanup. Reviewed runtime/suite/capture schema IDs 1.3/1.2/1.1, capability/static audit updates, two skill versions and the additional public STDIO scenario before refreshing manifest92. Final CRLF-to-LF normalization aligns schema bytes with the repository checkout rules; all 92 staged Git blobs match the manifest. The full regression and isolated wheel test were repeated on these final bytes. Earlier distribution/log files are retained privately. No dependency, Python version, tool count, default policy or legacy canonical runtime-plan change.

Focused native tests: **28 passed, 6.660 s**, exit 0. Final full regression: **412 run, 410 passed, 2 skipped, 0 failures/errors, 81.864 s**, exit 0. Coverage includes exact graph/signal owner, missing/duplicate identity, source/grounding changes, metadata/hash/rate tampering, empty/single/mismatched/nonfinite/nonincreasing/changing arrays, sample bounds, failed reads, controls restoration and failed local acquisition stop/resource close/Runtime stop. Public execution binds the actual journal attempt and consumes its grant once. The earlier focused test's incorrect top-level `attempt_id` assertion was corrected to the actual `attempt.attempt_id` response contract. The two existing skips are opt-in host Codex discovery and unavailable OS symlink privilege; Windows junction tests passed.

Actual STDIO full49/core10/engineering29 passed. The added native suite preparation calls `prepare_native` and verifies unchanged files, no grant and no live operation. Existing inactive-policy and forbidden-tool denials passed. All nine skill validators, pip check, manifest92, source scanner158 and `git diff --check` passed. Build produced wheel-from-sdist and source distribution; Twine passed both and combined scanner422 reported zero issues.

Read-only installed Python 1.1 audit passed **29 checks**, including existing array methods/exact Runtime scope and the native module's bound-read/no-dispatch surface. Its Python process forbade SDK imports, sockets and subprocesses. All **37 protected files** matched the previous checkpoint hashes: ten tutorial originals, 24 SDK Python files, local HTML API reference, Java JAR and javap. Separate permitted javap inspection read only bytecode for signal/time-array implementation. `update_plots` is asynchronous; the SDK generates a plot time axis and trims trailing NaN result tails. This does not prove fresh/atomic data, current simulator-clock origin, signal meaning or remote acquisition abort. SDK request-path identity is not independent remote signal-ID verification.

The exact wheel passed a fresh venv outside the checkout: constrained dependency installation, pip check, installed import/integrity92, nine packaged/exported skills, synthetic demo and actual STDIO49/core10/engineering29 including native preparation. `source_checkout_imported=false`, `live_rscad_calls=false`. Tested wheel SHA-256: `fcf0f617d87cbf5e83cf6c31ec3ce968259bbdc8b30f8b9fbd67441d922357af`. The sdist is refreshed with final documentation; the tested wheel stays unchanged. Final comparison verifies all manifest entries against source/wheel/sdist and all final documentation/tests/tools in the sdist, followed by Twine and source/artifact scan.

No actual RSCAD connection, case open, Compile, Runtime/control/read/capture, rack query/reserve/connect, GUI or load-flow operation occurred. Synthetic cleanup is not proof of actual Runtime cleanup. WP-N04 software is implemented; live capture and WP-N05 deterministic events remain pending. Raw SDK/Java inspection, protected hashes, generated artifacts and logs stay ignored under `.validation/native-acquisition-20260906`. See [NATIVE_CAPTURE.md](NATIVE_CAPTURE.md) for compatibility and incomplete qualification.

## WP-N03 saved Runtime IR and binding (2026-09-06)

Baseline `bf6f8e3`. Final reviewed package contains 91 code/schema/skill hashes. New software covers saved pages/groups/controls/displays, separate plot/graph identities, explicit Draft COMP_ID candidates and guarded live-control scope checks. No new public tool is added. Runtime and suite schema IDs advance to 1.2 and 1.1; the understand-model, read-documentation and run-experiment skills advance to 1.1.0. [Scope and compatibility](RUNTIME_IR.md) distinguish saved, synthetic and installed implementation evidence.

Focused Runtime regression passed 74 tests in 4.063 s before the final two ID/data-scope tests; capability regression passed 12 tests before the final signature-mismatch test. These 29 new tests are included in the final full regression. Initial test development corrected three expected exception classes. The first full run was **384 run, 4 errors, 2 skips, 159.527 s**: four existing tests read UTF-8 JSON containing Korean paths with the cp949 default. Explicit UTF-8 test reads corrected that issue; no product safety gate or expected result was relaxed. The original failure log is retained privately.

Read-only installed qualification passed on the final parser: ten untouched Tutorial Course originals were copied into an ignored isolated input directory and inspected twice through public `inspect_runtime_layout(..., representation="ir")`. Schema, deterministic IR/hash, unchanged copy bytes and all **37 protected file hashes** passed (ten originals, 24 SDK sources, HTML API reference, Java JAR and javap executable). The Python qualification process blocked SDK imports, sockets and subprocesses. The earlier separate javap process inspected bytecode only; it made no RSCAD connection.

Across the ten copies, the bounded parser retained 224 component records: 50 visual groups, 72 controls, 58 displays, 34 plot containers and 10 unknown drawings; 37 explicit graphs and 750 saved references were retained. 742 references identified one saved Draft candidate; eight script-example references stayed unresolved. All 72 saved control identities are ambiguous because tagged/plain variants reuse IDs; no variant was selected. Empty vdiv and torque-spd layouts returned available; the eight nonempty layouts returned partial. These are saved-subset observations, not whole-format or live-target qualification.

Static installed SDK audit passed **27 checks** including typed lookup and read-only page/subtab declarations. Bare ConnectedProperty syntax was confirmed in the installed connector before being accepted by the audit. Running RSCAD version remains unknown. Local HTML inherited-method declarations were cross-checked against Java RuntimeController: insertion/wire creation are empty implementations, and clipboard operations only select a subpage. Page creation has implementation but does not prove effective overlay controls. Phase C authoring remains unsupported; no adapter, RTX writer or live trial was added.

Final full regression: **384 run, 382 passed, 2 skipped, 0 failures/errors, 144.725 s**, exit 0, using the Windows default process encoding. The two existing skips are opt-in installed Codex discovery and unavailable OS symlink privilege; Windows junction checks passed. All 29 new tests and existing native/policy/restoration regressions passed.

Actual STDIO full49/core10/engineering29 passed, including the new saved IR call, exact-source preservation, inactive execution denials and no live RSCAD calls. All nine skill validators, pip check, manifest91 and source scanner155 passed; `git diff --check` passed. Build produced sdist and wheel-from-sdist; Twine passed both and the source/wheel/sdist scanner checked 415 entries with zero issues.

The exact wheel passed a fresh venv outside the checkout: constrained dependency install, pip check, installed import/integrity91, nine packaged/exported skills, synthetic demo and real STDIO49/core10/engineering29 including saved IR. `source_checkout_imported=false`, `live_rscad_calls=false`. Tested wheel SHA-256: `47e8008eeac3395fe41bd6946fe09cdf972f64e137587b5f7a322f60e7301b60`. Integrity-reported manifest digest: `7a4096d2733635e489b3f84fb777c48cee5ab9a809c9bdb7108e8b02e5af8968`. The sdist is refreshed with final documentation and UTF-8 test-read corrections; the tested wheel stays unchanged. Final comparison verifies every manifest entry against source/wheel/sdist and all final documentation/tests/tools in the sdist, followed by Twine and the source/artifact scan.

No Compile, Runtime lookup/control/capture, rack query/reserve/connect, GUI operation or load-flow execution occurred. Synthetic stop/restoration tests are not actual cleanup evidence. Vendor excerpts, source hashes, copies, generated IR and all logs remain ignored under `.validation/runtime-ir-20260906`.

## Native reconstruction checkpoint 3 (2026-09-06)

Baseline `1a9d54e`. Source review covers the new temporary-file verifier, SDK evidence binding, stored NAME insertion, post-close empty RTX preservation and source-bound GROUP readback. The edit skill is 1.2.1; public schemas, profile counts, default static behavior and inactive execution policy are unchanged.

Focused reconstruction regression: 21 tests passed, 6.050 s, exit 0. After final source/skill review and manifest refresh, all native tests passed: 38 tests, 17.096 s. Five new tests cover fresh/old/link/nonempty temporary files, hidden NAME placeholders, empty-canvas-only reconciliation and GROUP-local readback with movement rejection. Existing creation/paste/close failure and policy/public transaction tests remain.

Final full regression: **355 run, 353 passed, 2 skipped, 0 failures/errors, 147.500 s**, exit 0. The two existing skips are opt-in installed-host discovery and unavailable OS symlink privilege; Windows junction checks passed. Actual STDIO full49/core10/engineering29 passed with inactive-policy denials and no real SDK calls. All nine skill validators passed, `pip check` found no broken requirements, manifest87 matched, source scan148 reported zero issues and `git diff --check` passed. Wheel and sdist build/Twine passed; source/wheel/sdist scan397 found zero issues.

The exact wheel passed installation in a fresh venv outside the checkout: constrained dependencies, pip check, installed import/integrity87, nine packaged/exported skills, dry-run, synthetic demo and actual STDIO49/core10/engineering29. `source_checkout_imported=false`, `live_rscad_calls=false`. Tested wheel SHA-256: `643f978116c395a6caac2f75430feeb7d2b1dbda52c1024b1b4577d15176e113`. Integrity-reported manifest digest: `0e377aaae09e3cc4051b4a2286146acc9ddf5fce5310cec2ddb82ecd5660768b`. The sdist is refreshed with these final documentation entries; the tested wheel stays unchanged. Final artifact comparison checks all 87 manifest entries against source/wheel/sdist and exact final documentation in the sdist; Twine and the scanner are repeated for the refreshed sdist.

Three separately instrumented local reconstruction/save/reopen trials and three one-shot isolated Compile trials passed. Native RPC counts were 680/542/879; Compile RPC counts were 18 each, all allowed. All protected hashes and candidate/Compile input hashes matched. Fresh success logs, empty error logs and nonempty matching output/build binaries were verified offline. All case closes and disconnects were confirmed. RSCAD reported 2.7, compiler logs RTDSPC 6.7.3. The detailed scope and retained failed attempts are in [NATIVE_EDITING.md](NATIVE_EDITING.md#checkpoint-3--local-construction-and-compile-2026-09-06).

These are task-scoped internal adapter/Compile results. The public policy-bound live transaction, auto selection, Runtime/rack/load-flow, arbitrary hierarchy/versions and engineering acceptance remain unqualified. Static checks retained warnings and no errors in their checked scope. Raw models, journals, Java source inspection, logs and receipt/hash review remain ignored under `.validation/native-newcase-20260906`.

## User-directed local recovery follow-up (2026-09-05)

Recovery-only SDK validation passed: 19/19 allowlisted RPCs, exact temporary-path identity (no old case-ID lookup), stopped/unmodified state, empty Draft, isolated recovery save, verified `close(False)` and `disconnect(False)`, and absence of both exact trial paths from the connection registry. All 53 protected hashes passed, including the original/input, SDK and other startup temporary case. Two incident-specific markers were archived and removed under the user's explicit cleanup authorization. Installed Java implementation inspection identified the temporary-backing-file behavior and temporary-case close restriction. No vendor implementation text is distributed.

This follow-up changes documentation only. The 86-file package manifest and previously tested wheel are unchanged; the 350-test result below belongs to `e7911e6`, not a newly repeated suite. No Compile, Runtime, rack operation or construction retry was performed. A future new-case adapter fix and full reconstruction qualification remain outstanding. See [recovery evidence](NATIVE_EDITING.md#explicit-recovery-follow-up).

## Native reconstruction checkpoint 2 (2026-09-05)

Baseline `fc2580e`. Fixed native reconstruction and public preview/apply are tested with authored synthetic fixtures. Focused native regression: 33 tests passed (16 new reconstruction tests), 8.228 s; subsequent close-retry hardening is included in the final full suite below. Real SDK evidence is separate: one new-case trial stopped before insertion/save on unexpected file identity; cleanup unconfirmed, 56 protected hashes unchanged. No new Compile, Runtime or rack operation followed. Historical CH5/CH6 saved-file comparisons passed with explicit UUID/GROUP mapping. [Native evidence and limitations](NATIVE_EDITING.md#checkpoint-2-local-trial-and-recovery-limitation) records the unresolved recovery requirement.

Final full regression: **350 run, 348 passed, 2 skipped, 0 failures/errors, 137.381 s**, exit 0. Skips remain optional installed-host discovery and unavailable OS symlink privilege; the junction boundary test passed. The suite includes 16 new reconstruction tests and the existing 334 tests.

Actual STDIO full49/core10/engineering29 passed, including source-derived reconstruction preview with no candidate/SDK calls, old native preview, static apply and auto-apply denial. All nine skill validators passed; `pip check` found no broken requirements. Manifest86 matched reviewed sources; source scan147 found zero issues and `git diff --check` passed. Private artifacts/logs remain in ignored `.validation/native-rebuild-20260905`; no native success is inferred from synthetic or historical tests.

Build produced an sdist and wheel-from-sdist; Twine passed both. Source/wheel/sdist scan394 found zero issues. A fresh venv outside the checkout installed the exact wheel and passed constrained dependencies, pip check, installed import/integrity86, nine skill resources/dry-run/export, synthetic demo and real STDIO49/core10/engineering29 with reconstruction preview. `source_checkout_imported=false` and `live_rscad_calls=false`. Tested wheel SHA-256: `d3182ef0e4c7bf9293b4db9e507c994e3c8aaacc441fcd0a87c59b8a7ab1bd4f`; manifest SHA-256: `c116e21969155487e62a3b494c8c7cf5c512f7dd0dae936762d2e4ae5e8a4287`. The sdist is refreshed with these final documentation entries and compared against the same 86 manifest entries; the tested wheel remains unchanged.

## Native closed-loop checkpoint 1 (2026-09-05)

Baseline `352ae0b`; bounded native existing-component editing and GROUP inspection, with remaining WP-N01–N11 work explicitly tracked in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). Full construction/Runtime integration remains unqualified.

| Check | Actual result |
|---|---|
| New synthetic regression | 17 new tests pass in the final full run. The earlier 16-test focused run passed in 9.111 s. Coverage includes save/close/reopen/readback, original protection, wrong-case refusal, mutation-before-error journaling, no force-close/retry, cleanup failures, worker timeout recovery marker, preview/policy binding, extra-change rejection, GROUP/nesting/diff, safe legacy grouped-edit refusal and preserving the existing comparison range for 5,001 components. |
| Full regression | Final source: 334 run, 332 passed, 2 existing optional-host/OS-symlink skips, no failures/errors, 178.532 s, exit 0. Native recovery blocks Compile/Runtime before workflow/backend creation while operator policy revocation remains usable. |
| Actual MCP STDIO | Full49/core10/engineering29 passed, including native preview without SDK calls, auto-apply refusal, static roundtrip, saved CSV metrics and inactive live execution rejection. No real RSCAD calls in the software smoke test. |
| Skills | All nine quick validators passed. Full regression also validated packaged manifests and callable schemas. No host skill export/configuration change. |
| Static installed sources | 24 SDK Python files; SDK 1.1; required declarations present. Nine CH1–CH6 originals parsed with hashes preserved, including complete CH5/CH6 GROUP members. Vendor imports, process and network calls blocked in the read-only probe. |
| Local native adapter | Two isolated R=1.0→2.0 trials passed. Instrumented trial: 40 allowed RPCs, three old/new/reopened readbacks, verified close/reopen/cleanup, 56 protected files unchanged, exact requested parameter difference and unchanged topology/non-DFX members. FX reports 2.7, patch unknown. One static ground-port warning retained; no engineering pass. |
| Separate authorized Compile | One call returned True in 0.688 s; fresh success log, empty error log, 107,329-byte binary, all 13 output file hashes verified. 16 allowed RPCs; source/candidate hash c67a9f79b52198c26e1c01121c769745df2f9567cdd6ad78ca3aa3a028b653f1; binary b407cf7c6c45160a877563f7f48040f000c6c7626e4c37603919e20676045133. Cleanup and 26 protected hashes passed. |
| Source/distribution gates | Manifest84 matched; source/wheel/sdist scanner386 reported zero issues; whitespace check passed. Build produced wheel and sdist; Twine passed both. |
| Fresh installed wheel | Passed in a new external venv: constrained dependency installation, pip check, installed import origin, integrity84, nine packaged/exported skills, synthetic demo and actual STDIO49/core10/engineering29 including native preview/auto rejection. `source_checkout_imported=false`, `live_rscad_calls=false`. |

Final tested wheel SHA-256: `e396279385f9a5d79c17b4e1c0814847720507fae9ed57257bc5c76285ed8e07`, retained in ignored `delivery-dist`. Its code/schema/skill hashes match the delivered manifest. The sdist is refreshed after these documentation-only result entries; the tested wheel is unchanged.

Native public policy-bound apply was tested synthetically; the local native trials invoked the same internal SDK adapter under standing isolated-edit permission, without creating a real component policy. No Runtime/rack/load-flow call, live group paste, new-case construction through this public adapter, failure-corpus qualification or model-driven evaluation occurred. Python loopback/RPC restrictions do not measure Java background network traffic. Earlier tutorial construction evidence is historical and not inherited as new adapter qualification.

Development testing found a Windows cp949 decode error in the new synthetic worker fixture. Explicit UTF-8 reads corrected it before the passing focused/full runs. Final review also kept the recovery gate inside live dispatch so policy revocation remains possible, and separated GROUP comparison from optional IR size limits. Both are covered by the final regression. Local evidence is retained under ignored `.validation/native-closed-loop-20260905` and is excluded from Git/distribution. Older wheel results below belong to their earlier bytes.

## V2.0 engineering validation (2026-09-05)

Clean baseline `main` was `06a67ad`. All testing used isolated temporary configuration and cleared inherited cloud/RSCAD settings. Source/schema/skill changes were reviewed before recording the final 81-file portable manifest. Software results and static installed-source observations below do not qualify an actual structural/native/rack workflow.

| Check | Actual result |
|---|---|
| Full regression | `python -m unittest discover -s tests -v`: 317 run, 315 passed, 2 skipped, no failures/errors, 43.008 s, exit 0. The skips are default-off host discovery and unavailable OS symlink privilege. |
| New tests | 37 passed in the full run: editor/catalog/check/IR11; CSV/metrics9; DSL/suite/traceability13; profiles/skills/diagnostics/eval scorer4. Existing 280 tests retained. |
| Actual STDIO | Full49 plus core10 and engineering29 passed, including new catalog/policy discovery, hash-bound candidate save/static reopen, CSV→canonical→metric, suite plan/prepare and inactive execution rejection. Four live entry points denied, 14 forbidden tool names absent. No real RSCAD calls. |
| Skills | Nine `quick_validate.py` checks passed. Packaged/exported manifests and actual callable tool schemas passed. Separate opt-in installed Codex discovery found all nine enabled repository skills: 16 run, 15 passed, one OS-link skip, 2.476 s. No model rollout or host configuration change. |
| Installed sources | 1,590 local definition files hashed/rechecked; actual GAIN schema and three SDK declarations resolved. Invented structured log API unresolved. All 70 protected source/SDK/document/model hashes match. Vendor imports, process launch and sockets blocked during the probe. |
| Source gates | Release manifest81 matched. Source scanner137 found zero issues. |
| Distribution | `python -m build` built sdist and wheel from sdist; Twine passed both. Source+wheel+sdist scanner369 found zero issues, exit 0. The sdist was refreshed after recording final documentation; the tested wheel/application contents are unchanged. |
| Fresh wheel | `tools/wheel_check.py` passed in a new external venv: constrained dependency install, pip check, installed import origin, integrity81, nine-skill read/dry-run/export, synthetic demo and actual STDIO49/core10/engineering29. `source_checkout_imported=false`, `live_rscad_calls=false`. |

Tested wheel: `rtds_rscad_agent-0.1.0a1-py3-none-any.whl`, SHA-256 `65858e48fe2f181e151c91d9567c92cd2ca3dd7652484dfd83104d8122a15a34`. Its final code/schema/skill hashes match the source manifest. Raw logs, the installed-source probe and build outputs are retained under ignored `.validation/v2-20260905`.

Development checks exposed and resolved missing new-schema registry IDs, an in-memory mock that lacked real artifact hashes for resume verification, an incorrect expected exception class in a new negative test, and multi-record smoke stdout incompatible with the wheel checker's single-JSON contract. The final checks above passed after those corrections. Final review also connected read-only component-policy hashes to the public overview, added hash-bound requirement/metric aggregation, and fixed LockFree matching to exact hierarchy segments. No test/manifest change bypassed a failing live gate.

Unexecuted/unqualified: native structural editing/save/reopen, native Compile log grammar and return semantics, actual new capture/Runtime/FSAT/rack operations, hardware allocation/electrical completeness, deterministic simulator-time event scheduling, general IR→DFX serialization and model-driven benchmark execution. Existing earlier native open/read/save/reopen reports remain historical evidence and are not reused as new-editor qualification. No licensed source/artifact, credential, active policy or local validation data is included in the distribution.

Validation date: 2026-09-05. Actual environment: Windows, Python 3.12.9. Supported configuration remains RSCAD FX 2.7.3 / vendor API 1.1. The subsequent local SDK trial returned RSCAD version 2.7, without an exact patch; 2.7.3 remains a support target rather than an observed version. Package version and dependency constraints were not changed.

## Unknown resolution and documentation discovery (2026-09-05)

Clean starting commit cf7821d; previous WP/EXT implementations reused. Added only installed API discovery, additive provenance/context metadata and the seventh packaged documentation skill. Code/schema/skill changes were reviewed before regenerating 55 hashes. No execution policy, existing grant, SDK or original-model mutation was made.

| Check | Measured result |
|---|---|
| New API tests | 16 passed, 3.483 s: found/missing/ambiguous symbols, signatures, version mismatch, no import/network/process, source mutation, links, limits and partial coverage. |
| Documentation recipes | 12 passed, 4.789 s: current project, definition, installed API, exact manual context, explicitly mocked Vector Store fallback, all-source misses, hash/page/chunk provenance, publisher/version distinctions and stale/mixed sources. These are explicit tool recipes, not model-driven skill behavior tests. |
| Full regression | 280 run, 278 passed, 2 skipped, 109.307 s, no failures/errors, exit 0. Existing optional host-discovery and OS symlink skips. |
| Actual MCP STDIO | 43 named/schema/annotation contracts; installed-source search/exact lookup/imaginary-symbol unresolved; previous synthetic edit/assessment/image/extension cases passed, exit 0. Three live actions denied; 14 forbidden tools absent; no real RSCAD calls. |
| Skill checks | quick_validate passed in UTF-8 mode. Packaged/exported skill tests passed; an explicit additional installed Codex discovery run found all seven enabled repository skills with no discovery errors (16 tests: 15 passed, one OS-link skip, 5.319 s). No global export or model request. |
| Actual installed-source probe | 24 SDK Python files; version 1.1; four runtime-signal search matches; exact RSCADFX.get_case signature found, invented symbol unresolved. All 70 protected files unchanged. No SDK import, app launch, socket, Compile, Runtime or rack call. |
| Source release gates | Manifest55 matched; source scanner103 found zero issues, exit 0. |
| Final distribution | python -m build produced sdist and wheel in the ignored discovery final-dist directory. Twine passed both; source/artifact scanner275 found zero issues, all exit 0. |
| Installed wheel | tools/wheel_check.py passed in a fresh venv outside the checkout: constrained install, pip check, installed import origin, integrity55, seven packaged/exported skills, no-write dry-run, synthetic demo and actual STDIO43; source_checkout_imported=false, live_rscad_calls=false. |

Final review also changed empty API/cloud result evidence_level to unknown and added assertions; focused and full tests above were rerun against the final source. The earlier full pass was 117.146 s. Local distribution code/schema/skill hashes match the delivered source; distribution files predate only the final documentation result entries and are not published by this source push. The initial documentation test run incorrectly assumed its shared fixture lived outside installed DOC and tried recreating DOC. Those fixture mistakes were corrected; a separate user-document-root test now verifies it is not classified as official. The skill validator initially lacked PyYAML and used Windows legacy encoding: PyYAML 6.0.3 was installed only under ignored validation data, and PYTHONUTF8=1 enabled the successful check. Product dependencies remain unchanged.

Local raw evidence is under ignored .validation/discovery-20260905. Actual source inspection is distinct from invoking vendor APIs. No live cloud request, model-driven skill task, RSCAD/Runtime/rack qualification, engineering acceptance or other-version integration was performed for this addition. Scope and compatibility are in [UNKNOWN_RESOLUTION.md](UNKNOWN_RESOLUTION.md).

## Main delivery validation (2026-09-05)

The owner authorized normal main pushes after completed validation. Before first delivery, staged whitespace inspection found extra EOF blank lines in static_comparison.py and test_mcp_contract.py. Only those blank lines were removed; the single affected source hash was reviewed and refreshed. Project-snapshot regression passed 18 tests in 10.650 s. Final full suite passed: 252 run, 250 passed, 2 existing optional-host/OS-symlink skips, no failures/errors, 98.459 s, exit 0. Actual STDIO41 passed, including extension scenarios and inactive-policy denials, with no live RSCAD calls. Manifest52 and source scanner97 passed. Local models, validation evidence, ACL backup and active settings are excluded from Git. Earlier wheel/sdist results below belong to their earlier bytes; no new distribution was built for this source commit.

## Latest GUI repair follow-up

User-authorized, UAC-approved root-only WRITE_DAC repair passed (icacls exit 0). Same-task node_repl/sky/window enumeration and foreground RSCAD screenshot/accessibility passed. Exact isolated saved script_example GUI open/tab/Draft observation/close passed; pre-existing Untitled retained. All 70 protected hashes and saved trial hash match. No rack/Compile/Runtime action. No production code or contract change; unit tests below were not rerun for this documentation-only repair. See [GUI_TOOL_RECOVERY.md](GUI_TOOL_RECOVERY.md) for capture limitations.

Repair follow-up release checks: manifest 52 matches, source scanner 97 files with zero issues, both exit 0. Git whitespace check passed after removing an extra trailing blank line. These checks used the existing Python environment through scoped execution approval; a default-sandbox venv launcher attempt could not start its base interpreter and is not counted as a test pass.

## Earlier local RSCAD follow-up

The user authorized local launch and isolated model open/read/save-as/reopen, and prohibited rack operations and Runtime execution. Actual results are detailed in [LOCAL_RSCAD_QUALIFICATION.md](LOCAL_RSCAD_QUALIFICATION.md).

| Check | Actual result |
|---|---|
| Native unchanged-model round trips | 2/2 passed, final runner exit 0. Microgrid1 Draft Kp/Ki Init 3.0/1.0 and script_example AG Type INTEGER unchanged after native save/reopen. Four successful non-forced case closes, SDK disconnect completed. |
| Scoped SDK audit | 86 requests: four opens, two save-as, four closes; no rack/Compile/Runtime/parameter-write request. Python socket calls stayed on loopback. Separate Java background traffic was not captured. |
| Structure and companions | Microgrid1 complete subsystem text preserved (2,537 component records), but GROUP without UUID prevents full production-parser qualification. script_example retains 76 component records and normalized topology; save adds seven installed defaults and upgrades the DFX/RTX serialization. All ten sibling copies remain unchanged. |
| Protected files | All 70 original/SDK/document/definition/data hashes match; source snapshots and working models remain identical to originals. Saved hashes separately recorded. |
| EXT regression | 25 passed, no skips/failures/errors; 16.029 s, exit 0. |
| Full regression | 252 run, 250 passed, 2 skipped, no failures/errors; 61.526 s, exit 0. Existing optional host-discovery and OS symlink skips. |
| Actual STDIO | 41 tools; complete synthetic scenario and native image delivery passed. Three live actions denied, 14 forbidden tools absent; exit 0. This STDIO run made no actual RSCAD call. |
| Release source checks | Manifest matches 52 files; scanner 96 files, zero issues; git diff --check clean. Production code/schema/skill bytes unchanged; no manifest regeneration. |
| GUI project identity at that checkpoint | Initially blocked (subsequent scoped trial passed above): computer-use initialization failed twice, including reset/retry, with sandbox setup refresh error. Process title observed, SDK case paths verified; no screenshot, accessibility or project/window binding obtained. |
| Compile / rack / Runtime | Not executed. The inspected SDK and local help do not establish a rack-free native Compile path. |

Initial one-off logger framing failure and native Kp# to Kp assertion failure are retained separately; neither is counted as a passing attempt. After correcting only the validation script, the final two-case run passed. No production code, execution policy, grants or installed SDK were changed. This follow-up updates five documentation files and local ignored scripts/evidence. No new wheel/sdist was built or published; artifact results below belong to the earlier checkpoint.

## Earlier offline EXT-01 / EXT-02 follow-up

The following results supersede the earlier WP completion counts retained below. All commands used the existing Windows/Python 3.12.9 environment and isolated product settings.

| Check | Actual result |
|---|---|
| `python -m unittest discover -s tests -p test_extensions.py -v` | 25 passed, 0 failures/errors/skips, 14.852 s, exit 0. |
| Full suite after reviewed manifest refresh | 252 run, 250 passed, 2 skipped, 0 failures/errors, 123.476 s, exit 0. Same two optional-host/OS-symlink skips as the earlier checkpoint. |
| Actual `tools/mcp_smoke.py` | 41 named/schema/annotation contracts; old Kp/Ki scenario plus selector preview, invalid trial rejection, unchanged isolated copy and stored Runtime inventory passed, exit 0. Three live requests denied, 14 forbidden tools absent. |
| Installed SDK/document source inspection | API 1.1 and all ten investigated declaration groups found; existing Runtime AST audit 24/24 passed. No SDK import, app invocation, connection or rack access. |
| Local original protection | 59 SDK/document/example/definition file hashes unchanged. Trial source_snapshot and working bytes equal the original; candidate absent. |
| Actual saved model analysis | Draft UUID 45 Type INTEGER to REAL changes active output identity/type and affects an existing net; no edit applied. RTX inventory 20 records, partial due to tagged/legacy duplicate IDs; no live target inferred. |
| Release/source/dependencies/demo | Manifest 52 entries match; source scan 95 files, zero issues; pip check and synthetic demo passed; exit 0. |

The new tests cover stale inputs/definitions, exact selector options, unsupported/unterminated conditions, connected-port impact, nested/duplicate/unknown Runtime records, parser-bound pagination, no-write reads, copy failure cleanup, configuration/companion changes, original preservation, socket/process/vendor-import tripwires and existing workflow registry compatibility. Early STDIO integration failures (bare dict return annotation and absent schema ID) were resolved before these final checks.

Final extension distribution verification used `.validation/ext-20260905/release`; earlier artifacts were preserved. Build (sdist then wheel-from-sdist), Twine on both artifacts and source/distribution scan all passed, exit 0; 256 entries scanned, zero issues. `tools/wheel_check.py` passed in a fresh venv outside the checkout: installed import origin, pip check, 52 integrity entries, schemas, six skill resources/dry-run/export, synthetic demo and actual STDIO41 with the extension scenario. Source checkout import and live RSCAD calls were false. Tested wheel SHA-256: `de43e257e45c6fb21c7ffb302a99c424acd2c2fef56b712674651ba768f598e4`; manifest SHA-256: `825c8e0ea4732231e69b13b658812fba90deb67628d88418c083369461c8b744`.

After recording these results, the sdist is rebuilt with final docs; the tested wheel remains unchanged. The final file comparison binds both artifacts to the same 52 manifest entries and confirms final docs in the sdist. Final metadata/scanner results and hashes are retained in the local extension validation directory. No publication, user configuration or policy change occurred.

No native structure-application adapter, clone/insert/wire execution, GUI/session capture or live target-discovery qualification is claimed. Exact unexecuted targets and actions are specified in [EXTENSION_QUALIFICATION.md](EXTENSION_QUALIFICATION.md); private concrete paths are in the local ignored trial report. SDK source inspection is distinct from real application execution.

## Earlier WP-00 through WP-11 software checkpoint

| Check | Actual result |
|---|---|
| Baseline full unittest suite | 85 run, 85 passed, 0 skipped, 0 failures/errors; 11.201 s; exit 0. |
| Final `python -m unittest discover -s tests -v` after reviewed manifest refresh | 227 run, 225 passed, 2 skipped, 0 failures/errors; 55.126 s; exit 0. |
| Final actual `python tools/mcp_smoke.py` | STDIO37; 6 detailed normal calls, 7 expected error calls, 14 forbidden calls rejected, 3 live action requests blocked; full synthetic scenario passed, exit 0. |
| `python -m rtds_agent demo` | synthetic_mock_only, live/network calls false, policy unchanged, engineering_verdict not_evaluated; exit 0. |
| `python -m pip check` | No broken requirements; exit 0. |
| `python tools/release_manifest.py --check` | 48 matching packaged code/schema/skill files; exit 0. |
| `python tools/release_check.py` | 89 source files checked, zero issues; exit 0. |
| Media subset | 15 tests passed, no skips; actual authored PDF rendered with installed Poppler 26.07.0 and PNG received/decoded through STDIO. |
| Optional installed-host skill discovery | Codex 0.153.3 app-server skills/list found six enabled repo-scope exported skills with no errors. No task/LLM request, SDK connection or global host change. |
| Skill authoring validation | All six SKILL.md files passed the skill-creator quick validator; temporary validation dependency removed. |
| `git diff --check` | No whitespace errors; exit 0. |

The two default-suite skips are intentional opt-in installed Codex discovery and an OS-denied symbolic-link fixture (error 22). Windows junction boundary tests passed. A separate opt-in skill run exercised real discovery: 16 run, 15 passed, one OS symlink skip. These are distinct runs, not 243 unique passing tests.

The STDIO scenario uses authored synthetic definitions, a two-gain project, a companion file, supplied before/after waveforms, and an authored PDF. It proves local transport/contracts, catalog persistence, isolated editing, detailed comparison, original preservation, image delivery and deterministic numerical evaluation. Inactive policy denied execution. It does not prove a causal response to Kp/Ki edits, a vendor-format round trip, a live compile/run, or engineering correctness.

Fake-driver tests independently cover backend initialization/orchestration/persistence failures, grant consumption, exact Runtime targets and readback/restore/stop/cleanup. Expected error calls and injected failures are passing negative tests, not an actual RSCAD outage. No test-only bypass or fake-success flag is exposed in production.

During final review, two independently reproduced patch boundary issues were fixed and their original reproductions rerun successfully: transient source edits no longer contaminate the verified output, and changed installation definitions cannot bypass required companion discovery. Final tests include these cases. Earlier focused test failures during implementation were resolved before the final manifest and regression run; they are not omitted from a still-failing final gate.

## Earlier WP distribution checks

- `python -m build --outdir .validation/release-20260905`: sdist and wheel-from-sdist built successfully, exit 0. The final sdist was rebuilt after recording results/documentation corrections; packaged application code, schemas and skills did not change.
- Artifacts: `rtds_rscad_agent-0.1.0a1-py3-none-any.whl` and `rtds_rscad_agent-0.1.0a1.tar.gz`. Twine: both passed, exit 0. Source/distribution scan: 240 entries, zero issues, exit 0. These checks are repeated on the final documentation-only sdist.
- `python tools/wheel_check.py <exact-wheel-path>`: passed, exit 0. A fresh venv outside the checkout installed the built wheel and constrained dependencies; actual import was `Lib/site-packages/rtds_agent/__init__.py` in that venv. Source checkout import was false. `pip check`, all 48 integrity entries, schema access, six skills, dry-run/export, synthetic demo and real STDIO37/full scenario passed. The installed transport test also received/decoded the native PDF image.
- Tested wheel SHA-256: `5594c37ce66ede084e3eb51ab3b412e68e2fd2a7b0b4d8910a1ee231ab42d37e`. Its portable manifest SHA-256 is `0e2031a8a7b9ee5872c1189cf26c35f422a612e2f00d8bf3d9a63e51c32d4e92`. Final artifact hashes are also retained beside the local outputs; no circular sdist self-hash is embedded here.
- The final wheel and documentation-updated sdist are compared entry-by-entry against the same 48-file release manifest. No wheel reinstall is needed for documentation-only sdist changes; the tested wheel itself is unchanged.

The independent skill procedure review covered three virtual requests (two-gain edit/supplied data without live authorization; current failed attempt versus old success with duplicate contexts; unavailable manual renderer). It checked skill selection, ordering and stopping/uncertainty conditions against the actual contracts. It is separate from installed-host discovery and from unperformed model-driven Codex task evaluation.

## Reproduce

Use a clean Windows Python 3.12 environment. Tests/smoke/wheel checks create isolated temporary settings and do not use operator credentials or a rack.

```powershell
python -m pip install -c constraints-windows-py312.txt -e ".[dev]"
python -m unittest discover -s tests -v
python tools/mcp_smoke.py
python -m rtds_agent demo
python -m pip check
python tools/release_manifest.py --check
python tools/release_check.py
python -m build --outdir .validation/release-20260905
python -m twine check .validation/release-20260905/rtds_rscad_agent-0.1.0a1-py3-none-any.whl .validation/release-20260905/rtds_rscad_agent-0.1.0a1.tar.gz
python tools/release_check.py --artifacts .validation/release-20260905/rtds_rscad_agent-0.1.0a1-py3-none-any.whl .validation/release-20260905/rtds_rscad_agent-0.1.0a1.tar.gz
python tools/wheel_check.py .validation/release-20260905/rtds_rscad_agent-0.1.0a1-py3-none-any.whl
```

Choose a fresh output directory if that one already contains artifacts. Normal `python -m build` builds an sdist, then a wheel from that sdist. `wheel_check.py` creates a new venv outside the checkout, clears PYTHONPATH/PYTHONHOME/virtualenv/cloud/RSCAD settings, uses isolated Python, verifies installed import origin and integrity, reads schemas/skills, performs skill dry-run/export, runs demo/pip check and repeats the actual STDIO scenario. Dependency installation may use the package index; `--wheelhouse PATH` restricts it to supplied local wheels. No paid model calls are required by CI.

Optional host discovery can be run with `RTDS_TEST_CODEX_DISCOVERY=1` and `python -m unittest discover -s tests -p test_skill_catalog.py -v`. It only starts a local app-server and reads skills/list in an isolated temporary repository. It is not a skill task evaluation.

## Limits and retained evidence

No real RSCAD/SDK connection, rack query, Compile, Runtime, FSAT, control or external I/O test was performed. The earlier WP checkpoint did not rerun the installed API audit. The EXT follow-up above subsequently ran its 24 source checks without importing or connecting the SDK; these are static evidence only. A configured version or available executable never becomes observed live qualification.

Codex model image ingestion and model-driven skill task evaluation were not performed. Cloud search/upload, remote CI and other Windows/RSCAD/API configurations were not tested. The v2.0 update adds explicit saved native-CSV ingestion into the bounded JSON adapter; actual native capture sessions and vendor-log grammar remain unqualified. Empty partial diagnostic logs and inadequate sample evidence cannot produce an engineering pass.

Local raw logs are retained in the git-ignored `.validation/` directory; repository documentation intentionally omits private installation/operator paths. The source/artifact scanner checks conservative patterns/types and is not a comprehensive secret detector or legal certification. No licensed manual/model/definition/SDK, credential, active configuration or execution record is intentionally shipped. The release manifest is not a publisher signature or experiment approval.

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for WP status and precise EXT-01/02/03 qualification prerequisites, [MIGRATION.md](MIGRATION.md) for compatibility, and [SAFETY.md](SAFETY.md) for the unchanged operator recovery procedure.
