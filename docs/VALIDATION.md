# Public alpha validation

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
