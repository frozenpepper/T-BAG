# T-BAG — Parent Harness Routing

Parent harness and technical-worker CLI are independent. Load exactly one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`). Worker transport is configured through `WORKER-CLI.md`.

## One supervision primitive

T-BAG launches technical workers detached. `launch` returns the exact `event_dir`. `inspect` is a non-blocking snapshot. `follow` is a blocking **observer for one attempt**: it emits only a bounded start surface plus terminal/dead-unresolved/deadline and never tails worker bodies. It never gates, reviews, accepts, integrates, or mutates task lifecycle.

The parent harness runs `follow` without blocking conversation:

- **Claude Code:** run `follow` as a native background Bash task. That gives the owner a real task chip/display and the task completion wakes Claude.
- **OpenCode:** `OPENCODE.md` owns the exact protocol. It uses the normal detached core `launch` followed immediately by project-local `tbag_follow`; the parent never runs core `follow` directly.
- **Codex/Kilo:** use only a reviewed native non-blocking mechanism if the adapter documents one. Otherwise degrade conversation-first and reconcile on the next owner turn.

There is no generic T-BAG run supervisor, `wait-edge`, watcher daemon or parent polling loop. Attach observers **per attempt** and reconcile durable state on every wake.

Install/check the selected adapter before the first long-running batch:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
```

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Harness adapters preserve only orientation: identify the resumable run and resume with `reconcile-run` first. If multiple resumable runs exist, set `TBAG_RUN_ROOT`; T-BAG never guesses between them.
