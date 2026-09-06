# Compile diagnostics and parser corpus

The read-only Compile diagnostics surfaces inspect supplied evidence and parser regression behavior. They do not establish Compile success, native origin or qualification.

## CLI

List the bounded parser catalog and its declared formats and taxonomy:

```text
rtds-agent diagnostics list
```

Inspect a source-bound parser corpus manifest without writing files or invoking RSCAD:

```text
rtds-agent diagnostics corpus ABS_MANIFEST
```

The [corpus schema](../src/rtds_agent/schemas/compile_failure_corpus.schema.json) is version `1.0`. A passed corpus means that supplied parser expectations matched deterministic parsing. It does not mean Compile passed. The inspector verifies the manifest, implementation and schema source hashes, configured-root paths, fixture hashes, provenance references, settings and sources again before returning. The manifest is limited to 100,000 JSON characters and 400,000 bytes, individual raw fixtures to 1 MiB, other sources to 256 MiB each, aggregate sources to 512 MiB and the response to 2 MiB. Up to 128 corpus cases are supported with 4 MiB of raw fixtures in aggregate. Linked paths and duplicate corpus identities are refused.

A manifest requires `schema_version`, `corpus_id`, `description` and `cases`. Each case declares `case_id`, `evidence_kind`, `format_id`, `raw_ref` (absolute path, SHA-256, bytes and encoding), `expectations`, `provenance`, `sanitization` and `limitations`. Expectations contain the ordered `categories` and `component_mappings` arrays plus `parser_coverage`. Provenance must pin the exact raw fixture and may cite additional permitted files. Evidence kinds are `synthetic_authored`, `native_observed_private` and `sanitized_native_derivative`; a sanitized derivative requires distinct original/derivative hash lineage. These labels and lineage descriptions remain declarations. The CLI returns 0 when all parser expectations match and 1 on a mismatch; it never creates or repairs fixtures.

## Parser formats and taxonomy

`rscad_compile_errs_v1` retains decoded lines as records. Empty logs have `parser_coverage: "empty"`; all nonblank lines in this format remain unknown. `rscad_compile_api_exception_v1` recognizes only the exact observed generic API exception text and classifies it as category `rscad_api` with the generic failure explanation. It represents an SDK-returned exception string extracted to UTF-8, not a capture of the full Compile Messages tab. The nine organizational categories are `model_structure`, `parameter`, `connection`, `component_definition`, `companion_file`, `compile_resource`, `rscad_api`, `runtime`, and `unknown`. The other categories have no qualified native signatures.

Records preserve exact source path/hash, line and byte locations, raw line hashes, reported identifiers, parser rule and provenance. Classification maps a component only when context and UUID identify exactly one component; labels and partial identifiers do not establish identity. Operational and cleanup errors remain retained evidence. Automatic retry and repair are false, and a suggested fix requires a fresh source-bound preview/candidate through the existing edit contract.

The production backend does not automatically produce or collect a native log receipt, and there is no automatic collector or messages getter. The optional native receipt path accepts a schema-bound object with `schema_version`, `workflow_id`, `attempt_id`, `action: "compile"`, `source_sha256`, `working_sha256`, and one to 16 `logs`. Each log contains `path`, `sha256`, `bytes`, `encoding`, `format_id`, and `collection_status` (`complete` or `partial`). Receipt inspection keeps the existing `get_execution_diagnostics` signature and returns `native_compile_analysis` through the established diagnostics path.

The receipt belongs in `native_compile_logs` of an already hash-bound saved Compile result. All explicit identities must match the current workflow and attempt. Logs must remain inside that workflow directory, with at most 1 MiB per file and 4 MiB aggregate. Supported encodings are exact UTF-8, UTF-8-SIG and ASCII. Parsing is limited to 20,000 lines per file and 10,000 findings; native results follow the requested offset/limit and retain their own count and next offset. A changed log invalidates the result after grounding as well as before parsing. Existing standalone text `result_ref` remains unsupported.

Collection-complete is a declared collection state, not proof of fresh or full coverage. An empty log never proves success. Native origin is not verified by source hashes. Results retain `native_outcome: "not_evaluated"`, `integration_qualified: false`, `execution_authorized: false`, and `live_calls_made: false` where those flags apply.

## Observed task-scoped evidence

The fixed evidence set contains four API Compile calls: two source-setting combinations failed with generic `RSCADError`; a detached-resistor case succeeded; and an Imp reversal case succeeded with a new candidate. Cleanup was verified for these observations. No public live policy apply, rack RPC, Runtime, load-flow, or GUI operation was performed. One earlier trial stopped after an empty RTX metadata change; a later existing path preserved exact source RTX bytes after close. These observations do not qualify the public Compile path or any of the seven native failure types as qualified.

Do not include vendor raw logs, vendor models, or private filesystem paths in a published corpus. Keep corpus fixtures and provenance source-bound, sanitized where necessary, and explicit about unsupported parser coverage and unresolved native interpretation.
