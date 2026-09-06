# Engineering agent benchmark contracts

This file describes the unchanged nine-task legacy contract. The separate [WP-N11 model evaluation runner](../docs/MODEL_EVALUATION.md) uses `native_tasks.json`; its model evidence and unsupported cases are reported separately. Supplied legacy traces are never relabelled as model executions.

`tasks.json` defines nine user tasks, required/forbidden tools, evidence fields and expected final states. Fixtures are authored Python test data, not licensed RSCAD examples. No model rollout or rack operation has been executed by this benchmark.

The scorer accepts a bounded JSON trace with exactly `calls` (objects containing `tool`, boolean `is_error` and `arguments`), `final_state`, and `evidence`. Suite modes are checked so a high-level facade cannot conceal an executed action in a plan-only benchmark. Run `python tools/run_evals.py --case EVAL-01 --trace path/to/trace.json`. It checks the recorded contract only. Required evidence presence does not authenticate a source, establish whether a tool actually ran or prove the engineering interpretation. A controlled model evaluation must capture authentic host tool traces and independently review the outcome.

Synthetic tests exercise accepted/rejected traces and forbidden calls for all nine cases. Existing direct and STDIO tests exercise the underlying software. Neither evidence class is an LLM task success rate.
