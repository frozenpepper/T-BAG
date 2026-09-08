# T-BAG worker CLI — OpenCode

Cold-load only when the configured technical worker uses OpenCode. Normal task execution goes through `dsd_attempt.py` / `run_worker.py`, not direct shell recipes.

## Session continuity

A process may exit `0` before a long semantic task is complete. For healthy interrupted same-role work, reuse the recorded session on the next T-BAG attempt. The core operation is `dsd_attempt.py launch --resume-last`; the **parent harness owns how that operation is invoked**. An OpenCode parent invokes the core detached launch normally with `--resume-last`, then immediately arms the returned attempt with `tbag_follow`; other parent adapters apply their own observer contract.

Create a new T-BAG attempt/report while reusing the OpenCode worker session. Resume only when the task basis is still valid and deliverables are accumulating. Semantic non-convergence, invalidated authority, or substantial new diagnosis belongs to Analyst routing rather than reflexive session reuse.

## External task DB

Each active task uses an OpenCode DB outside the project and T-BAG run tree. This preserves resumable worker state without polluting the user's interactive DB or causing project-copy/self-referential SQLite failures.

DBs may become large. Low disk can surface as SQLite errors that resemble provider failure; diagnose storage before retrying `Failed to execute statement` or `No space left on device` failures. Closed tasks release/delete their DB and `-wal` / `-shm` sidecars; never delete a live unfinished task DB.

## Transport classification

Usually retryable in the same healthy session: rate limiting, temporary provider unavailability, 502/503/504, connection reset, transport timeout.

Do not classify these as transient capacity failures:

- disk/SQLite errors;
- authorization/governance refusals;
- credential errors.

A host wait timeout without `terminal.json` is not itself a dead worker. Use `dsd_attempt.py inspect`; process/log activity is only liveness evidence, never semantic progress.

## Report recovery and visibility

A stub report does not prove no useful work occurred. Inspect a bounded `worker.log` tail when recovery needs it:

- stub + no project movement → same-role continuation when coherent;
- stub + project movement → Analyst Recovery over the real worktree before more mutation.

Use only T-BAG's tracked detached launch path. The event directory must remain queryable by `dsd_attempt.py inspect` while the worker runs. Raw `nohup`/background shells are not task execution because they bypass lifecycle supervision.

## Startup admission

Parallel tasks stay parallel, but their OpenCode **process starts** must not collide on shared CLI/bootstrap state. T-BAG therefore admits worker CLI starts through the machine-global launch gate using the run's `launch_start_interval_seconds` (default `3.0`). Detached monitors may be launched together; only the instant of `Popen` is spaced. Once admitted, all workers execute concurrently.
