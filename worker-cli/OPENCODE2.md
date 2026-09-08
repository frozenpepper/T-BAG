# T-BAG worker CLI — OpenCode 2 beta

Cold-load only when the configured technical worker uses the OpenCode 2 beta (`opencode2`). Normal task execution goes through `dsd_attempt.py` / `run_worker.py`, not direct shell recipes.

OpenCode 2 is a **worker adapter only** in this release. Its beta plugin/server APIs are intentionally not treated as compatible with the stable OpenCode parent-harness adapter.

## Isolated automation path

T-BAG launches V2 workers through the non-interactive automation surface with a private server:

```text
opencode2 --standalone run --format json ...
```

Every T-BAG task also receives its own external `OPENCODE_DB` path. This is mandatory isolation: V2 normally discovers a shared background service and recent beta builds can otherwise touch the same default SQLite database used by stable OpenCode. Do not remove `--standalone` or the per-task DB override merely to save startup time.

The DB lives outside the project and T-BAG run trees, follows the same task-lifetime cleanup rules as stable OpenCode, and is retained only while same-task continuation/recovery may need it.

## Session continuity and JSON evidence

`--format json` keeps stdout as JSON events. T-BAG captures the exact session ID from those events and records it with the attempt; same-task continuation uses `--session SESSION_ID` in a new T-BAG attempt. Stderr is kept separate so lifecycle identity is never parsed from a merged noisy stream.

Resume only when the same task basis remains valid. A confused/non-converging frame or invalidated authority routes through the normal Recovery/Analyst path rather than being preserved because a session exists.

## Model variants

OpenCode 2 variants are model-specific request overlays, commonly used for reasoning effort or token budgets. T-BAG maps configured runtime `effort` to `--variant`, but does **not** invent names such as `low`, `high`, or `max`; use a variant that actually exists for the selected model/provider.

## Startup collisions

V2 still participates in T-BAG's machine-global worker-start admission gate. Detached monitors may all launch immediately, but their underlying CLI processes begin a few seconds apart; once started they run concurrently. This protects fragile CLI/database bootstrap without reducing `max_workers` or making the conversational parent sleep/poll.
