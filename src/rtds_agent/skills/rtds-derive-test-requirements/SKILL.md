---
name: rtds-derive-test-requirements
description: Derive reviewable RTDS experiment criteria from supplied requirements or local grid-code documents, with document hashes, exact pages, channels, and event mappings.
---

# Derive test requirements

## Use when

The user wants a test specification grounded in supplied requirements. Interpret a cited clause in its surrounding page context; separate its wording from engineering choices needed to make it measurable.

## Do not use when

The task only needs existing result calculation, or no requirement source or user criterion exists. Do not invent acceptance limits or infer a physical fault target from a diagram label.

## Prerequisites

Document access uses configured local roots. Model reads need an exact project snapshot. Requirement derivation does not grant permission to compile, query a rack, or run Runtime.

## Tool order

1. Use `search_rtds_local(query)` and `get_manual_page(source_path, page)` to read the relevant clause and its context. Retain the source hash/page, units, duration, exceptions and applicable version.
2. Use `inspect_rscad_project(project_path)` and `get_component_parameters(project_path, component_id)` for current model facts. Resolve unfamiliar fields with `get_component_schema(component_type)` or `lookup_rscad_api(symbol)`.
3. Draft the canonical experiment JSON: exact control identities, explicit units, initial conditions, sequential events, measurement channels, criteria and requirement traceability. A fault/trip label is caller-declared meaning, not verified electrical effect. Runtime action times are controller wall-clock times after run confirmation.
4. Use `run_experiment_suite(request)` with mode `plan` to validate mappings and obtain deterministic identities. Distinguish hash/page verification from the correctness of the requirement interpretation.

## Completion

Present a test specification with requirement ID → document/hash/page → event/control → channel → metric/criterion. Mark missing units, ambiguous targets, external I/O effects and unsupported rules unresolved. Plan success is not execution or certification.

## On failure

Read exact source evidence for the unresolved item and revise the draft within the user's intent. Missing electrical meaning or an ambiguous normative clause needs clarification; it must not become a guessed threshold.
