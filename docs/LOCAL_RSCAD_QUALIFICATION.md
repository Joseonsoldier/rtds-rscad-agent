# Local RSCAD EXT-01 / EXT-02 qualification

Date: 2026-09-05. This follow-up explicitly authorized local application launch, isolated model open, Draft parameter reads, save-as and reopen. It prohibited rack queries/reservation/connection and Runtime execution. Compile was conditional on evidence of no rack access. This report supersedes only the earlier local-app deferral; it does not qualify general structural editing or Runtime execution.

## Installed evidence and execution boundary

Installed Python API 1.1 source, local API HTML, `case.py`, `draft.py`, `component.py`, `rscadfx.py`, `comms/_comms.py`, `connection_setup.py` and message framing were reviewed before use. Native `get_version()` returned **2.7**, matching the observed process title `RSCAD FX 2.7`; no exact patch was returned. Do not label this an observed 2.7.3 installation.

The SDK launched one local application. Its Python connections were bound to 127.0.0.1. A one-off local runner permitted only version/ping, exact trial path open/lookup, owned case identity/status, Draft object/type/subpage/subtab/parameter reads, exact absent save-as destinations and non-forced owned-case close. Unexpected outgoing SDK commands and non-loopback Python socket calls were refused. No public tool, execution policy, grant, restoration or cleanup implementation was changed. This task authorization does not enable future executions.

The final successful attempt recorded 86 outgoing SDK requests, including four opens, two save-as calls and four successful closes. **No rack, Compile, Runtime object/value/control, run, stop, load-flow, parameter write or structural mutation request was sent.** Python socket/request auditing is not packet capture of the separate Java application; background application traffic was not measured. Stored rack settings were left unchanged and were not treated as authority to use a rack.

## Actual local tests

Two source models were copied with relevant sibling data into separate snapshot, working and saved directories. The one-off copies and vendor evidence remain in ignored local validation data; none are included in the source package.

| Check | Measured result |
|---|---|
| Microgrid1 working open and save-as/reopen | Passed. Working case ID 2 and saved case ID 3; exact absolute case paths matched. Both observed stopped and unmodified. |
| Kp identity/value | Draft UUID 139, rtds_sharc_ctl_SLIDER, SS #1 / Draft. Stored name Kp# resolves to Kp through native enumeration. Init 3.0, Min 0, Max 100, Units pu, unchanged after reopen. |
| Ki identity/value | Draft UUID 142, same type/subpage/subtab. Stored name Ki# resolves to Ki. Init 1.0, Min 0, Max 100, Units pu, unchanged after reopen. |
| script_example working open and save-as/reopen | Passed. Working case ID 4 and saved case ID 5; exact paths, stopped/unmodified state and non-forced close verified. |
| AG selector read | Draft UUID 45, rtds_sharc_ctl_SWITCH, SS #1 / Draft, Name AG, Type INTEGER before and after reopen. No INTEGER-to-REAL change applied. |
| Cleanup | All four final-attempt case closes returned true. SDK disconnect completed with terminate=False. The local app remains open without any case left open by the trial. No stop command was sent because no simulation was started. |
| Protection | 70 protected original/SDK/document/definition/data files retain their pretrial hashes. Both working and snapshot models remain byte-identical to originals. All ten copied sibling data/image files retain their hashes. |

These Kp/Ki values are native Draft slider **initial settings** in this installed example, not live Runtime measurements or a native parameter API with literal parameter keys Kp/Ki. They do not validate gain changes or dynamic performance.

Source/saved SHA-256:

| Model | Original / unchanged working | Native saved |
|---|---|---|
| Microgrid1 | `2c036a3261611311cb82f088a17cdf2984643cbb40724a8e635a9c39e5ff556a` | `2e5cacef829d5a21309d255d55401fac63ae63f56bd7985cd4820b9566c2b4f1` |
| script_example | `87f3068f2db2d09ea4858b74db47ad0df86d24b95f833f5760c8d029849e191a` | `b8edc6cadba5e30626df16ae34b23e95efd7ba678adb7dc9c05647cf5259d7bc` |

## Structural comparison and compatibility

Microgrid1 contains 2,537 COMPONENT_TYPE records. Its complete DFX text from the first SUBSYSTEM-START through the end is identical before/after native save; stored settings are also identical. Thus its saved circuit/hierarchy/parameter/wire text is preserved. The production topology parser still rejects a GROUP without UUID at (112,272), so no complete parsed-net or engineering validation is claimed for it.

script_example retains 76 parsed component records, component identities/locations/orientations and the normalized static topology signature. All existing stored parameter values remain unchanged. Native save adds seven installed-definition defaults across two components: elimCrtDelay=No on UUID 1 and AgRoff/BgRoff/CgRoff/ABRoff/BCRoff/CARoff=1e10 on UUID 11. Full component dictionaries therefore are **not identical**. DRAFT changes from 2.4v to 2.7; other parsed project settings remain unchanged. The earlier duplicate-UUID/parser coverage limitations remain; normalized topology equality is not engineering equivalence.

Both native archives preserve their three member names and empty inf2 member. DFX/RTX bytes and archive hashes change: UTF8 marker, save metadata, canvas dimensions and display/layout serialization differ. Microgrid RTX drops some saved VALUE/display fields and adds text style fields; script RTX changes group/plot/style/slider serialization, and its DFX overlay frame sizes change. These are observed compatibility differences, not a blanket approval to ignore future diffs. Never overwrite the source or transplant historical hash-bound approval to these saved models.

## Earlier GUI failure and subsequent recovery

Subsequent authorized ACL repair succeeded in the same task. Actual foreground RSCAD capture, exact saved script_example GUI open/tab/Draft circuit observation and owned-tab close passed; Untitled and all 70 protected files remained unchanged. See [GUI_TOOL_RECOVERY.md](GUI_TOOL_RECOVERY.md) for current results and capture limitations. The following paragraph preserves the earlier failure.

Computer Use was attempted through the installed skill's @oai/sky entry point. Initialization failed with `windows sandbox failed: helper_unknown_error: setup refresh had errors`. Reset and retry failed identically. No desktop/window screenshot or accessibility state was obtained. Read-only OS process metadata identified the local RSCAD FX 2.7 window title, but **OS-window-to-project binding and visible tab/hierarchy/selection remain unverified**. SDK Case.file/caseid and Draft subpage/subtab were verified; they do not replace a GUI observation. No alternative unsupported screenshot helper or UI input was used.

This is a tool initialization failure, not an automatic approval-review rejection. No extra permission was required for the already authorized local test.

## Compile decision and unexecuted scope

Reviewed `Case.compile()` and local API HTML document a connected compile operation, without a rack-free option. Installed Draft help `Compiling_a_Circuit.htm` describes analyzing a saved circuit and producing Runtime input files; `Circuit_Toolbar.htm` separately describes rack assignment. Neither establishes that the installed FX 2.7 compile path performs no rack access. The help archive `DOC/ON-LINE/Html_JH/Draft_Doc/Draft.jar` SHA-256 is `aaa045ee173be1398bd0efbe9484da00fe762a6c969467df39f6c8b05a58cca2`; only HTML was read, no Java classes executed/decompiled. `DOC/SOFTWARE/Script Manual.pdf` page 26 describes explicit rack rescanning and Runtime-related commands, not a guarantee for rack-free native Compile.

**Compile was not executed.** No rack was queried, selected for execution, reserved or connected by the runner. Runtime lookup/value reads, simulation, rack validation, selector application, insertion/clone/wire edits and general GUI/session discovery remain unexecuted or unverified. EXT-01 now has local unchanged-model round-trip evidence; EXT-02 has SDK case/Draft identity evidence plus earlier offline RTX inventory, plus the subsequent single foreground GUI trial; live Runtime and general GUI qualification remain incomplete.

## Attempts and reproducible evidence

The first attempt launched the app but failed because the one-off request logger initially treated the SDK's separate newline framing as JSON. After source review, the logger accepted only that exact framing newline; the failed attempt was retained. The second attempt opened Microgrid1 but stopped at the strict Kp# versus native Kp name assertion; its owned unmodified case closed successfully. The third attempt passed both full round trips. No failed attempt was relabeled as success.

Ignored `.validation/local-ext-20260905` contains trial-plan.json, protected-before.json, attempt1/attempt2 reports and scripts, local_roundtrip.py, local-roundtrip.json, exact original/working/saved paths, archive and structural comparisons, full member diffs, SDK request/socket audit, GUI failure, compile decision and software test logs. Reports contain local proprietary evidence and are not public release inputs. See [VALIDATION.md](VALIDATION.md) for the separately measured regression results.
