# OS1 cluster activity monitor design

## Objective and acceptance checks

Add one Activity Monitor-style view to the existing EXO dashboard. The same
view must work when opened from either Mac and show both EXO nodes, measured
CPU, memory, GPU, power/energy, disk, and network activity, plus OS1 Fleet work
placement. It must not claim that macOS transparently pools arbitrary process
memory or GPU resources.

Acceptance checks:

1. EXO continues to report the same two-node topology and run inference.
2. No second `macmon` process is introduced; EXO's existing GPU/power sampler
   remains authoritative.
3. A read-only `/activity/local` endpoint reports bounded, non-secret local
   counters and sanitized OS1 Fleet metadata.
4. The dashboard polls each node over its existing cluster address and renders
   current values, freshness, history, and recent placement metadata.
5. The displayed convergence value is deterministic and documented: it is a
   balance score derived from the spread in observed normalized load. It is not
   a correctness probability or an optimality guarantee.
6. Type checks, dashboard checks/build, targeted backend tests, installed-node
   API checks, visual QA, two-node checks, and a stability window pass.

## Failure boundary and invariants

EXO already distributes CPU/GPU/memory/power samples in cluster state, but the
dashboard has no consolidated Activity Monitor view and does not expose disk or
network throughput. OS1 Fleet placement is available through a local CLI and
result receipts but is not surfaced in EXO.

Preserve the current EXO peer identity, follower/master behavior, event log,
models, ZeroTier configuration, OS1 credentials, and user files. Do not modify
the signed `/Applications/EXO.app` bundle. Do not return prompts, model output,
tokens, credentials, or authentication caches from the monitoring endpoint.

## Architecture

- Extend the existing EXO API process with `/activity/local`.
- Use `psutil` counters already bundled with EXO for CPU, memory, disk, and
  network rates. Reuse the existing cluster `nodeSystem` values for GPU,
  temperature, and power; never launch another `macmon` sampler.
- Cache the global OS1 Fleet snapshot and expose only node readiness/resource
  fields. Read recent local receipts and expose metadata only.
- Add `/activity` to the Svelte dashboard. It reads cluster state once per
  second, discovers the two node API addresses from EXO network interfaces,
  polls each local endpoint, and merges results by EXO node ID.
- Compute normalized observed load per node as
  `0.35 CPU + 0.35 memory + 0.20 GPU + 0.10 queue pressure`. The convergence
  score is `100 - (max load - min load) * 100`, clamped to 0..100. A stale or
  missing node makes the status unavailable instead of fabricating a score.

## Alternatives and rollback

A separate monitor app or sidecar would duplicate lifecycle and sharing logic,
so it is rejected. Starting a second `macmon` sampler is rejected because it
can contend with Metal inference. Browser-only metrics cannot access system
counters or OS1 receipts.

Installation uses a new custom EXO runtime directory and an atomic LaunchAgent
path switch. Rollback restores the prior ProgramArguments/environment and
restarts only the exact EXO service.
