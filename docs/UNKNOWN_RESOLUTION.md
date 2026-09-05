# Resolving unknown RTDS/RSCAD information

Use the shortest direct route: **Project → Definitions/API → Official local documentation → Optional Vector Store → Unresolved**. The bundled `rtds-read-documentation` skill coordinates existing readers. There is no new server-side question classifier, automatic cloud fallback or parallel search engine.

## Direct paths

| Question | Existing or added path | What the evidence establishes |
|---|---|---|
| Current Kp value | Project snapshot → exact component parameters | Stored value and origin; not a Runtime observation. |
| Kp minimum/type/default | Existing audited `lookup_parameter` | Exact installed definition, hash and catalog generation. Configured version remains distinct from observed version. |
| Does a known API exist? | `lookup_rscad_api(symbol)` | Explicit declaration, source hash/line, signature and available docstring; not safe execution or runtime callability. |
| Which API reads a signal? | `search_rscad_api(query)` → exact symbol lookup with returned snapshot | Candidate declarations; ambiguous names are not silently selected. |
| Component theory or a schematic | Existing local search → exact page/section → actual image when needed | Cited local text and observed figure, subject to version/context and publisher limits. |
| Company supplementary guide | Explicitly configured and authorized Vector Store search | Supplementary content, never proof of an installed API or current model value. |

Existing project snapshots, definitions/catalogs, FTS5 index, manual page/section/image tools and optional cloud client are reused. No duplicate editing, execution, image, topology or storage engine was added. The existing six skills remain available; the seventh handles discovery and routes diagram work to the existing manual tools.

## Installed API contract

`search_rscad_api(query, top_k=10, expected_api_version=None, snapshot_id=None)` requires 1–300 query characters and 1–20 results. All searchable query terms must occur in symbol/module text or the bounded docstring. Symbol matches have higher weight. Results contain relevance, total count and truncation, not a claim of complete semantic search. Search returns `found` or `unresolved`.

`lookup_rscad_api(symbol, expected_api_version=None, snapshot_id=None)` accepts a Python dotted identifier. Exact qualified names are preferred; a suffix is accepted only when one declaration matches. A duplicate name, overload or property getter/setter is `ambiguous`, with bounded candidate source locations. It returns a unique `result` only for `found`. Missing declarations are `unresolved`; unsupported source and missing installation are reported separately through catalog status/coverage. Errors such as changed source, invalid input and bounds violations remain tool errors.

The shared catalog statically parses only Python files under the configured SDK's rtds package. It reuses the Runtime AST inspector's signature/version helpers. No vendor import, property evaluation, function call, process launch, connection or network lookup is used. A direct lookup queries declaration identities without calling full-text search. Each call rebuilds a bounded source snapshot; no persistent cache or installation write is introduced.

Limits: 256 Python files, 4,096 directory entries, 12 directory levels, 2 MiB per source, 32 MiB total and 20,000 declarations. Links/junctions are rejected. Returned docstrings are at most 12,000 characters (search excerpts 1,000); signatures 4,000. Truncation is explicit. Module, class, function, async method and property declarations are supported. Re-exports/import aliases, inherited methods, conditional declarations, dynamic/decorated runtime behavior and compiled extensions are not resolved. An explicit constructor may be looked up as `Class.__init__`; class bases are not an invented constructor signature.

Search and lookup return an inspector/source/path-bound snapshot identifier. Source files are re-enumerated and rehashed before return. Passing the prior snapshot to lookup rejects same-size edits, added files and configuration changes. An unresolved static lookup does not prove the symbol is absent at runtime.

## Provenance and versions

API results use `source_type: installed_api`, `evidence_level: direct` and `verification: static_source_declaration`, with path/hash/line, `api_version`, configured and unobserved RSCAD versions. `expected_api_version` is compared literally with the installed version: `exact`, `mismatch` or `compatible_unknown`. These labels never assert compatibility with another release. SDK source 1.1 is not proof that a running RSCAD process is 2.7.3.

Project readers add `source_type: current_project` with derived static-parse evidence; `parameter_origins` retains stored/default distinctions. Catalog lookups add installed-definition/direct evidence without changing old fields or existing hash/version checks.

Local FTS results retain path/hash/page/text and add filename title, optional Markdown heading, deterministic chunk ID, FTS rank and detected RSCAD version mentions. The FTS database schema is unchanged, so existing indexes remain readable. Search excerpts have `context_verified: false`; exact page reads have `context_verified: true` but still report truncation. Important conclusions require exact context and matching hashes. Multi-page section reads reject mixed source hashes.

Documents under the configured installation DOC directory are classified as `official_local_documentation` **by path**, with `publisher_verified: false`. Other configured roots are `local_documentation`; a filename saying “official” does not authenticate it. Version metadata is detected from text mentions and compared to the configured target, not a verified running version. Multiple releases and missing/partial versions remain uncertain. A missing heading/title/version is not invented. Page-image handling and cache/hash contracts remain unchanged.

Configured Vector Store results retain existing citations and add supplementary source/evidence fields, unknown version matching and `installed_api_verified: false`. No source is uploaded or queried automatically. Tests use a mock cloud client; they do not prove live cloud permissions or retrieval quality.

## Unresolved answers

When no adequate evidence exists, report `status: unresolved`, the reason and only the sources actually searched. Record unavailable or skipped sources separately. Do not manufacture an API, default or parameter meaning, translate a MATLAB/Simulink name into RSCAD, or silently apply another version's documentation. Keep documented facts, derived findings and inferences distinct. An unviewed image cannot become verified figure evidence.

The routing is an instruction-only skill. Synthetic explicit tool recipes test each evidence path and rejection boundary; they are not model-driven demonstrations or a guarantee against every future model hallucination.

## Local qualification

On 2026-09-05 the actual installed SDK's 24 Python source files were read without import/execution. Version 1.1, four “runtime signal” search matches, exact `rtds.rscadfx.RSCADFX.get_case` signature and a deliberately nonexistent symbol's unresolved result were verified. All 70 previously protected hashes matched. Private reports remain in ignored local validation data. No RSCAD app, Compile, Runtime or rack action was performed for this work. Full software/distribution results are maintained in [VALIDATION.md](VALIDATION.md).
