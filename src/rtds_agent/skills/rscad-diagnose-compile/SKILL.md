---
name: rscad-diagnose-compile
description: Investigate an RSCAD compile failure from the relevant attempt, raw diagnostics, exact project evidence, and version-matched manuals.
---

# Diagnose an RSCAD compile attempt

## Use when

Explain existing compile failure evidence or determine which component a compiler message may concern.

## Do not use when

There is no compile evidence and the request would require an unapproved new live compile, or when the requested outcome is to repair arbitrary project text automatically.

## Prerequisites

Obtain the workflow path and its intended project identity. Distinguish the newest attempt from earlier successful or failed attempts. Read raw diagnostic evidence and its hashes; never assume a previous success describes the current project.

## Tool order

1. Call `get_workflow_status(workflow_path)` and `revalidate_execution_evidence(workflow_path)` before interpreting results.
2. Call `get_execution_diagnostics(workflow_path, stage, offset, limit)` using `stage` = `"compile"` (or `"runtime"` / `"offline_test"` when relevant). The selected workflow and its attempt journal determine `attempt_id`; there is no arbitrary attempt-selector argument. Check the returned attempt identity, input hashes, source artifact/hash, execution state, and log completeness. Follow `next_offset` while retaining the same workflow/attempt/artifact identity. An earlier success cannot replace a failed or stale current attempt.
3. Only `component_mapping: "exact_context_uuid"` maps to a unique checked component. Preserve `unknown` mapping and original message evidence otherwise. For a supported exact component reference, call `get_component(project_path, component_id, context)`. A label or ambiguous UUID may yield candidates; preserve the uncertainty instead of declaring an exact match.
4. Use `search_rtds_local(query, top_k)` and `get_manual_page(source_path, page)` to check the relevant version and documented diagnostic meaning.
5. Propose only changes supported by the raw message, source, and documentation. Use the numeric editing workflow separately if the user has requested a supported correction.

## Completion

Report the attempt identity, project/hash association, original messages, linked components with mapping confidence, proposed cause, supporting sources, and unresolved findings. Keep a diagnostic hypothesis separate from a verified correction. An empty partial/unsupported log does not establish no errors or execution success; `no_diagnostics_found` requires an observed completed attempt and a complete supported log.

## On failure

A missing or mismatched evidence hash makes the affected conclusion untrusted. Preserve the raw evidence and request a correctly associated attempt or manual. Do not automatically retry an ambiguous failed run, modify policy, or promote an unmatched diagnostic into a model edit.
