# Execution boundary and recovery

## Operator scope

Run this alpha only on an isolated lab simulator that you are authorized to operate. It is not qualified for controlling power equipment, protection systems or external hardware. The absence of a hardware-I/O tool does not prove that your existing RSCAD case has no physical outputs; the lab operator must check that before enabling it.

Default policy is inactive. Opt-in belongs to each installation's operator, not to the author, an imported repository or an AI reading a document. MCP tools cannot modify policy. Configuring a different installation/data/source/document/store setting invalidates the previous policy binding. The policy file, settings and code reside within the local OS account's trust boundary; use account and filesystem permissions in a shared lab.

Allowed scopes are Compile, offline FSAT, Runtime capture, and optionally bounded Runtime control. No generic script execution, standalone arbitrary write, case save, deployment, rack reconfiguration, hardware I/O or source overwrite tools are exposed.

Runtime binds source/copy/test/companion/compiled-artifact hashes, same compile rack and a fresh consumed approval. Inputs require exact UUID/type/name/group/description, expected initial value, readback and restoration. A failed restore/stop/close/disconnect is not success. Time/sample bounds are enforced by the application but cannot guarantee recovery if the process, OS, network or simulator fails.

## Normal cleanup and failure

The driver attempts restoration, stop, case close and disconnect in its cleanup path and records each result. Do not assume a Python exception or a killed process stopped the simulator. Never use an unverified waveform image as a pass/fail result.

An exclusive local execution lock serializes runs. A process killed unexpectedly can leave `execution.lock` and an `in_progress` attempt file. These files deliberately block reuse. A completed or attempted workflow is not silently retried; prepare a new working copy after reviewing the failure.

## Manual recovery

1. In the RSCAD application, inspect the exact case and rack recorded by the last local workflow. Follow your lab's approved stop/emergency procedure. Do not change unrelated cases.
2. Verify whether the case is running, whether each changed control returned to its original value, and whether any external equipment is affected. Resolve unsafe state with a qualified operator.
3. Preserve workflow/attempt/Runtime/cleanup evidence locally. Do not post unredacted lab paths, keys or project data in public issues.
4. After confirming no agent process is executing and the simulator is safe, the operator may manually remove the stale `execution.lock`. Do not remove it simply to force a retry.
5. Disable policy using the CLI, investigate the cause, then prepare a new workflow. Do not alter consumed grants, hashes or result files to make a failed workflow pass.

`policy disable` prevents subsequent runs; it does not interrupt an active run. Normal CLI policy changes are refused while a run holds the lock.

## Public contribution boundary

Use synthetic fixtures only in public tests. Do not connect GitHub-hosted or untrusted pull-request code to a lab rack. No self-hosted lab runner, OpenAI credentials or proprietary documentation belongs in the public CI environment. Release checksums are not a substitute for code review or an OS security boundary.
