# Voltage Divider: native API construction

Date: 2026-09-05. The user requested tutorial reproduction, starting with Voltage Divider, then explicitly required API operation instead of GUI automation. This checkpoint completes native Draft construction and saved-model verification. **Compile remains unexecuted**, so the broader tutorial-to-Compile objective is incomplete.

## Actual construction

A fresh case was created with installed SDK 1.1 `remote_connection.new_case()`. `Draft.get_subpage(index=0)` returns a `DraftSubpage` inheriting `ComponentCompatible`: its documented `insert_component()` and `create_wire()` methods provide native insertion and wiring. `Draft._add_component()` alone is merely handle bookkeeping; it is not the insertion API. Discovery must follow inheritance rather than inspect only `Draft` methods.

Four library components were inserted, without copying the vendor case or editing DFX text: `lf_rtds_sharc_sld_SRC`, `lf_rtds_sharc_sld_SHUNTRES`, `rtds_sharc_sld_BUSLABEL`, and `ground`. Two `create_wire(3, coordinates)` calls generated two BUS records. Ground orientation was set to 180 degrees. The native API set and immediately read back 37 parameters.

The circuit follows installed *Introductory Tutorial*, chapter 1, PDF pages 9–14, including visual inspection of Figures 1.9–1.12 on PDF pages 12–13. It has a 230 kV, 60 Hz AC source, R impedance with 1 ohm series resistance, 0.05 s source time constant, 1 ohm Y-connected shunt load, grounded source neutral, and bus/node names BUS/NA/NB/NC. The saved time step is 50 microseconds. The source control setting `RunTime` is a Draft parameter; setting it did not execute Runtime.

The resulting local file is `AgentModels/VoltageDivider/voltage_divider_api.rtfx` under the installation workspace, outside this repository. The previously created GUI trial remains separate and is not the deliverable. Vendor cases and generated native files are not committed.

## Verified evidence

- 254 outgoing SDK requests; all passed the one-off exact mutation/path guard. Four component inserts, two three-phase wire operations, 37 parameter writes, and one orientation write were performed.
- Native save-as to an absent destination, non-forced close, reopen, exact file/stopped/unmodified checks, all four component identities/types/locations/orientations and 37 parameter readbacks passed. Both owned cases were closed. The SDK disconnected with `terminate=False`; unrelated application cases were left alone.
- Saved-file parser: six components, all six definitions resolved, twelve ports, five static nets, zero parser warnings. Each phase has one net joining source, resistor and bus label through two bus segments. Source neutral meets the ground component; the load neutral is an internal GROUND port, not a missing external wire.
- A UUID-independent comparison of all port roles/coordinates and undirected segment endpoints matched the installed tutorial's electrical topology. The comparison removes generated identities, not electrical members. It does not claim general topology or electrical acceptance beyond the parsed scope.
- All 72 protected source/document/SDK/definition/trial file hashes remained unchanged. Output SHA-256: `9e3aff04d8bfc0edcd6c834b5ae23a5f7ed3b38c49359c21f3b7025a62eabe98`.
- RSCAD returned version `2.7`; exact patch was not returned. Initial SDK setup emitted transient connection-refused messages before the single connection attempt completed successfully. No model mutation was retried.

Private reproduction/evidence files are retained in `.validation/voltage-divider-20260905/`: `native_build.py`, `native-build.json`, `verify.py`, `verification.json`, `topology.json`, and `protected-api-before.json`. The runner refuses existing output, audits local Python sockets, and permits only exact intended mutations on its owned new case. It is an installation-specific qualification runner, not a new public tool or reusable execution authorization.

## Differences and limits

The reference has six additional annotation/dashed-line records and a Runtime layout; neither was reproduced in this Draft-only checkpoint. Native IDs differ. One vertical BUS stores the opposite orientation with identical segment endpoints. The reference DFX format is 2.3p and the created file is native 2.7.

There are 17 stored parameter differences: explicit source/bus/node names versus the reference's auto-naming markers (5); six unused resistor current-monitor names; source load-flow-associated `P`, `Q`, and `LFIdent` (3); two empty note serialization values; and the new installed source default `elimCrtDelay=No`, absent in the old file. They are recorded individually in `verification.json`. The source remains specified by magnitude/phase behind impedance; no load-flow calculation was performed. This is a matching tutorial circuit, not a byte-identical or all-parameters-identical copy of the distributed completed case.

`Case.compile()` is documented, but its installed wrapper provides no rack-free option or network-behavior guarantee. Tutorial PDF page 14 requires selecting a target rack before compilation. The installed legacy Draft help (`Draft.jar`, `Compiling_a_Circuit.htm`) describes generation of simulation output files but does not establish absence of rack traffic. Accordingly no Compile RPC was sent. A future Compile attempt must target this exact saved model and an explicitly reviewed hardware configuration; existing rack restrictions and execution policy still apply.

No rack lookup/reservation/connection RPC, Compile, load-flow, Runtime control, run, stop, signal capture or external I/O operation was performed. Python loopback auditing does not measure background traffic in the separate Java application. Native success here does not qualify arbitrary component insertion, removal, hierarchy editing, Runtime layout generation, or a production MCP structural adapter.

No public API, dependencies, configuration, execution policy, grants, source protection, or Runtime restoration/cleanup behavior changed. Public changes for this checkpoint are documentation only. Full regression: `python -m unittest discover -s tests -v`, 317 run in 126.812 seconds, 315 passed and 2 skipped, exit 0. The unchanged default-off host-discovery and unavailable OS symlink-privilege checks account for the skips. Source release scan: 138 files, zero issues. `git diff --check` passed. No new wheel was built for this documentation-only change.
