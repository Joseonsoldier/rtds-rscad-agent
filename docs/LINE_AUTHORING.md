# Line and cable authoring scope

WP-N10 implements a read-only parser and source-preserving numeric preview for `tline_rlc_3phase_ohmic_v1`. No public companion writer, constants generator, Draft builder or automatic Compile is added.

```text
rtds-agent lines list
rtds-agent lines inspect ABS_TLI --sha256 SHA
rtds-agent lines preview ABS_REQUEST_JSON
```

The profile requires the exact observed three-block scalar `.tli` structure, `Data Entry Format = 0`, and `Number of Phases = 3`. Eight editable quantities are length in km, frequency in Hz, positive/zero sequence resistance and inductive reactance in ohm/km, and positive/zero sequence **shunt capacitive reactance** in megaohm*km. The saved key says `Series Cap Reactance`; its spelling does not establish series topology. All eight values must be positive in this narrow profile; the six RLC constraints match the inspected editor validators and are not universal physical restrictions.

The request follows [the packaged schema](../src/rtds_agent/schemas/line_authoring_request.schema.json): `schema_version: "1.0"`, `profile_id`, `source: {path, sha256}`, declared `ideally_transposed` and `frequency_independent_bergeron` assumptions, one to eight `changes: [{field, expected, value}]`, and one to eight `provenance: [{source_path, source_sha256, locator}]` references. Provenance must include the exact source path/hash. An example change is `{"field":"line_length_km","expected":100,"value":120}`; the other top-level fields are still required. Exact Decimal comparisons and rejection of lossy JSON literals prevent rounded expectations from matching a different saved value.

Preview changes only the requested numeric token spans in memory, reparses the result and checks every requested and preserved value. Ground resistivity, selectors, whitespace, line endings and all other bytes remain unchanged. The public result contains a numeric diff, source/candidate hashes and byte count without publishing candidate bytes. Frequency changes do not rescale supplied reactances; coherent revised input remains the caller's responsibility. Declared assumptions, physical suitability and publisher identity are not authenticated.

Input is bounded at 64 KiB/1,024 lines, JSON at 400,000 bytes/100,000 characters, each reference at 64 MiB, aggregate sources at 128 MiB and output at 2 MiB. Paths must be absolute and within configured roots; links/linked ancestors and traversal are refused. Source, request, provenance, settings, implementation and schema bytes are rechecked before return. The reference bound accommodates the inspected installation JAR. Catalog metadata identifies discovery sources without claiming they match every installation.

`lines inspect` exits zero for the supported subset and one for unsupported input. `lines preview` exits zero for a completed in-memory preview and one for invalid/stale/unsupported input. Neither means native acceptance. Cable `.cli`, documented imperial `.tlii`, other non-`.tli` files, per-unit, six-phase, geometry, revision-marked and additional-field inputs cannot inherit this profile. Raw C/L, arbitrary unit conversion and voltage-base conversion are not implemented.

## Installed discovery and generation boundary

Manuals distinguish `.tli/.cli` inputs from `.tlo/.clo` outputs consumed during Draft Compile. Current scalar RLC paths call internal Java `TLRLCData.generateTLO` / `CERLCData3or6Phase.generateCLO` and skip the external line solver. An executable or binary usage string therefore does not qualify scalar generation. Inspected external-solver wrappers have file/directory side effects and delegate the command vector to a helper outside this investigation's scope.

No dedicated authoring method was found in the inspected 24 Python SDK modules and API HTML; this is bounded negative evidence, not proof of all API absence. Cable labels identify R/X in ohm/km and capacitive reactance in megaohm*km when its unit selector is metric; the complete CLI unit-selection path and safe generator invocation remain unqualified. A travel-time inequality conflicts with adjacent manual prose, so no normative time-step check was invented.

The remaining workflow is: explicit electrical specification → supported input preview → separately qualified constants generation → fresh output bound to input/generator hashes → exact Draft component/phase/companion binding → isolated save/reopen and Compile → engineering assessment. **Changed input requires new constants output.** Same-basename outputs do not establish consistency or freshness. Existing companion discovery establishes found/hash-preserved files, not electrical validity or generation provenance.

The installed-file trial changed three fields in a private scalar copy, confirmed that undoing those numeric spans reconstructed the original bytes, saved it through a private harness, and re-read it through the public parser. Three actual unsupported inputs were refused. This was file-level roundtrip verification: no RSCAD open/save, constants generation, Compile, GUI, rack, Runtime or LF operation occurred. Public preview wrote zero files. See [implementation status](IMPLEMENTATION_STATUS.md) and [validation evidence](VALIDATION.md).

Existing MCP inputs/counts (50 full / 10 core / 30 engineering), nine skills, Python/dependencies, inactive policy, protection, grants and Runtime restoration/cleanup remain unchanged. Vendor sources, extracted documents, bytecode, candidates and trial evidence stay private and excluded from distribution.
