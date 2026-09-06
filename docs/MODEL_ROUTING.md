## Model routing and multi-agent execution

This repository prefers an **Astra-first development workflow**. Use GPT-6 Astra for all work that involves technical judgment, architecture, RSCAD/RTDS semantics, native API behavior, safety, integration, or engineering interpretation. Use GPT-5.6 Luna only for bounded repetitive work whose intended result is already well specified.

The goal of delegation is to reduce elapsed development time without weakening engineering judgment, provenance, safety boundaries, or validation quality.

### Default model policy

Use the following routing policy unless the user explicitly requests another model or effort level.

| Work type | Preferred model | Reasoning effort |
| --- | --- | --- |
| Root / lead agent | GPT-6 Astra | low |
| Normal feature implementation | GPT-6 Astra | low |
| Independent implementation workstream | GPT-6 Astra | low |
| Architecture or cross-module design | GPT-6 Astra | high |
| Native RSCAD API implementation | GPT-6 Astra | high |
| Runtime, recovery, transaction or safety behavior | GPT-6 Astra | high |
| Difficult parser / GROUP / hierarchy behavior | GPT-6 Astra | high |
| Integration review | GPT-6 Astra | high |
| Ambiguous native mutation or recovery problem | GPT-6 Astra | xhigh |
| Competing architectures / hard unresolved regression | GPT-6 Astra | xhigh |
| Exceptional repository-wide problem after lower efforts fail | GPT-6 Astra | max |
| Mechanical test generation | GPT-5.6 Luna | low or medium |
| Repetitive fixtures / schemas | GPT-5.6 Luna | low or medium |
| Documentation synchronization | GPT-5.6 Luna | low |
| Formatting, typing and repetitive cleanup | GPT-5.6 Luna | low |
| Release/check bookkeeping | GPT-5.6 Luna | low or medium |

Astra `low` is the normal default. Do not select `high`, `xhigh`, or `max` merely because a task is large. Escalate reasoning when the work contains difficult judgment or when evidence shows that the lower effort is insufficient.

If GPT-6 Astra is unavailable in the active environment, use the strongest available general coding/reasoning model and preserve the same routing principles. Do not silently replace Astra with Luna for judgment-heavy work.

### Astra escalation policy

Start ordinary engineering work with Astra `low`.

Escalate to Astra `high` when one or more of the following applies:

- native RSCAD SDK semantics must be interpreted;
- a public API or persistent data contract is being changed;
- safety, execution policy, grants, recovery, restoration or cleanup behavior is involved;
- three or more core modules interact in a non-mechanical way;
- model/parser semantics are ambiguous;
- engineering meaning must be inferred from manuals, definitions or project evidence;
- a lower-effort implementation attempt has failed for a non-obvious reason;
- integration requires choosing between competing implementations.

Escalate to Astra `xhigh` when:

- native mutation may have occurred before an exception;
- owned-case identity or cleanup state is ambiguous;
- GROUP/hierarchy behavior differs across parser, SDK and saved files;
- a cross-cutting regression cannot be localized;
- two materially different architecture choices must be evaluated;
- a high-effort attempt remains unresolved.

Use Astra `max` sparingly. It is reserved for repository-wide architectural problems, extremely difficult integration failures, or cases where lower Astra efforts have already produced concrete but insufficient evidence.

Do not restart the entire investigation after escalation. Hand the stronger agent a compact escalation packet containing:

```text
Problem
Relevant files/modules
Observed evidence
Exact errors or failed tests
What was already attempted
What was ruled out
Current hypotheses
Unresolved decision
Safety/authorization constraints
```

The higher-effort agent should continue from that evidence rather than redoing unrelated repository exploration.

### Luna delegation policy

Use GPT-5.6 Luna only when the target behavior has already been decided and the remaining work is primarily mechanical.

Good Luna tasks include:

- generating repetitive unit-test cases from an established pattern;
- adding equivalent fixtures for multiple component types;
- updating repeated JSON Schema fields after the schema design is fixed;
- updating version/count references across documentation;
- adding type annotations or mechanical validation branches;
- formatting and straightforward lint cleanup;
- generating repetitive manifest entries;
- checking documentation for stale tool/skill counts;
- running focused test commands and summarizing failures;
- creating repetitive synthetic inputs from an explicit specification.

Do **not** delegate the following decisions to Luna:

- selecting an RSCAD component or API based on engineering meaning;
- deciding whether an undocumented SDK behavior is safe;
- designing Model IR, GROUP or hierarchy semantics;
- designing transaction or recovery behavior;
- modifying execution policy, authority or rack controls;
- interpreting Runtime identity;
- deciding whether native cleanup succeeded;
- diagnosing an unfamiliar native Compile failure;
- deciding electrical correctness;
- choosing a repair after an ambiguous failure;
- resolving architecture-level merge conflicts;
- deciding whether evidence is sufficient for `integration_qualified`;
- changing safety boundaries.

If a Luna task encounters ambiguity requiring one of these judgments, it must stop the judgment portion and return evidence to an Astra agent.

### Multi-agent default

For work with at least two genuinely independent workstreams, prefer parallel delegation.

A typical development wave should use:

```text
1 Astra root / lead
+
2–3 Astra Low implementation workers
+
0–1 Luna repetitive-work worker
```

Prefer **three concurrent workers** in addition to the root. Do not normally exceed four workers unless the workstreams are clearly independent.

More agents are not automatically better. Do not spawn an agent merely because capacity is available.

### Recommended wave structure

Use development waves rather than assigning an entire roadmap to one long-running agent.

Example:

```text
Astra Low — Root / Lead
│
├── Astra Low — Native backend
├── Astra Low — GROUP / hierarchy
├── Astra Low — Runtime / capture investigation
└── Luna      — tests / fixtures / documentation
            ↓
      Astra High integration review
            ↓
    single native qualification gate
            ↓
       final release validation
```

The root agent is responsible for:

- decomposing the task;
- identifying dependencies;
- assigning non-overlapping work;
- defining file ownership where useful;
- preventing duplicate implementations;
- collecting worker results;
- resolving cross-workstream decisions;
- selecting when to escalate reasoning;
- deciding when the wave is ready for integration;
- running or delegating final release validation.

### Workstream size

Do not give a subagent an entire multi-phase roadmap.

Prefer workstreams that have one primary deliverable and can be independently reviewed, for example:

```text
Add GROUP-aware parsing and IR support.

Implement the native structural adapter for already-qualified flat Draft operations.

Investigate supported Runtime signal-discovery APIs and return an evidence-backed design.

Generate adversarial tests for the finalized native transaction contract.
```

A workstream should normally be small enough that its success or failure can be evaluated without simultaneously completing unrelated roadmap items.

### Context isolation

Give each subagent only the context required for its workstream.

Always provide:

- exact objective;
- relevant repository paths;
- applicable AGENTS.md / skill rules;
- interfaces it may depend on;
- interfaces it must not change;
- safety/authorization limits;
- expected tests;
- required output or handoff.

Avoid giving every subagent the entire root-agent reasoning history unless it is genuinely necessary.

When practical, reuse the same subagent for follow-up work on the same workstream rather than spawning a replacement that must rediscover the context.

Subagents should not recursively spawn additional agents unless the root agent explicitly delegates that authority for a clearly independent workload.

### Worktree and file ownership

Use isolated Git worktrees or equivalent isolated branches for parallel code-changing agents when the host supports them.

Before parallel implementation, identify likely overlapping files.

Avoid assigning two agents to independently rewrite the same core file.

Prefer ownership such as:

```text
Worker A:
    native adapter modules

Worker B:
    topology parser / Model IR / GROUP tests

Worker C:
    Runtime/capture modules

Worker D (Luna):
    fixtures / repetitive schemas / documentation
```

Files with broad cross-cutting impact should normally be owned by the root/integration agent, including when applicable:

```text
AGENTS.md
mcp_server.py tool registry
release_manifest.json
shared top-level schemas
migration documentation
final implementation-status documentation
```

Workers may propose changes to these files but should avoid competing edits unless the root explicitly assigns ownership.

### Native RSCAD serialization rule

**Never parallelize live RSCAD qualification against the same application/session.**

The following operations must be treated as a serialized qualification lane:

```text
RSCAD connect
new_case / open_case
native structural mutation
save / reopen
Compile
Runtime start/stop
Runtime control writes
signal acquisition
load flow
rack interaction
cleanup verification
```

Only one designated qualification agent may own this lane at a time.

Use **Astra high or higher** for native qualification that can mutate application state.

Luna must never perform native RSCAD mutation, Compile, Runtime, rack interaction or recovery decisions.

Parallel agents may simultaneously perform static code work, source inspection, tests and documentation, but they must not manipulate the same live RSCAD application state.

### Native qualification gate

Parallel implementation must converge before live qualification.

Use this sequence:

```text
parallel implementation
        ↓
focused tests
        ↓
integration review
        ↓
merged candidate
        ↓
static full regression gate
        ↓
single Astra native qualification agent
        ↓
native evidence
        ↓
final documentation / release gate
```

Do not allow each worker to independently connect to RSCAD simply to validate its own branch.

### Testing policy for parallel work

Subagents should run the **focused tests relevant to their workstream**.

Examples:

```text
tests/test_engineering_editor.py
tests/test_experiment_suites.py
tests/test_runtime_*.py
specific schema tests
specific parser tests
```

They should report:

```text
tests run
tests passed
tests failed
new tests added
known untested integration boundaries
```

Do not make every parallel worker repeatedly run the complete release pipeline.

A workstream inside a multi-agent wave is **not** a delivery boundary.

The integration/root agent runs the full validation once after the wave has been integrated, including the applicable:

```text
full unittest suite
MCP smoke tests
tool-profile tests
skill validation
release manifest check/update
source scan
distribution scan
build
Twine check
fresh external-venv wheel check
```

If integration changes code after those checks, rerun the affected gates as required by `docs/VALIDATION.md`.

This batching rule is intended to reduce duplicated validation time. It does not weaken the final release requirements.

### Documentation policy

Do not have every implementation worker independently rewrite README, implementation status, migration notes and release documentation.

Workers should record concise handoff notes containing:

```text
what changed
public behavior changed
new limitations
tests performed
native qualification status
documentation that needs updating
```

A Luna documentation worker or the root agent may synchronize repetitive documentation after interfaces are stable.

Architecture-sensitive statements, safety claims, qualification claims and engineering limitations must receive Astra review before publication.

### Integration review

After parallel workers finish, an Astra `high` integration agent should review:

- interface compatibility;
- duplicated implementations;
- shared-schema consistency;
- safety boundaries;
- transaction semantics;
- error propagation;
- recovery behavior;
- provenance/hash bindings;
- test coverage;
- backward compatibility;
- qualification claims.

Do not merge two implementations merely because both pass their own tests.

Where implementations disagree, resolve the underlying architecture first.

### Failure and retry policy

Do not repeatedly spawn new agents for the same unexplained failure.

For a failed workstream:

1. retain the failing evidence;
2. identify whether the failure is mechanical or judgment-heavy;
3. use Luna only for clearly mechanical corrections;
4. escalate judgment-heavy failures to a stronger Astra effort;
5. provide the escalation packet rather than restarting from scratch.

Two failed implementation attempts at the same conceptual issue should normally trigger Astra `high` or `xhigh` review.

Native mutation or incomplete cleanup must never trigger automatic retry.

### Cost and speed principle

Prefer model quality for decisions and cheaper throughput for repetition.

The intended pattern is approximately:

```text
Astra Low:
    most implementation and planning work

Astra High / xHigh / max:
    difficult judgment, integration and native qualification

Luna:
    repetitive and mechanically specified work
```

Do not optimize cost by delegating high-consequence engineering decisions to Luna.

Do not optimize intelligence by using Astra `max` for routine edits that Astra `low` or Luna can complete reliably.

### Completion responsibility

Subagents do not independently declare the whole task complete.

Each subagent returns a handoff containing:

```text
Status
Files changed
Behavior implemented
Tests run/results
Known limitations
Native/live operations performed, if any
Evidence paths/hashes, if applicable
Open integration issues
Recommended next action
```

The root Astra agent decides whether the requested task is complete and whether the repository is ready for final validation and delivery.

### Delivery boundary

For multi-agent work, a **completed integrated wave** is the normal delivery boundary, not each individual subagent workstream.

After the integrated wave passes the repository's required validation gates, follow the existing delivery preference for commit and normal fast-forward push to `origin/main`.

Do not force-push, bypass protections, weaken tests, regenerate integrity hashes to hide a failure, or treat parallel-agent output as inherently trusted.