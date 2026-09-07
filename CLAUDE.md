# T-BAG — Claude Code Parent Adapter

Load only when the premium parent runs in Claude Code. Worker transport is configured separately through `WORKER-CLI.md`.

Install once per project:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness claude-code --project-root <project>
```

The adapter installs only the compact/resume orientation hook. It deliberately does **not** install another worker re-wake hook.

## Launch + visible background follow

1. Launch normally with `dsd_attempt.py launch` and read the returned `event_dir`.
2. Immediately run this observer through Claude Code's **Bash tool with `run_in_background: true`**:

```bash
python3 <project>/TBag/tools/dsd_attempt.py follow \
  --run-root <run> --phase-id <phase> --task-id <task> --event-dir <event_dir>
```

Do this once for every newly launched live attempt, as its own Bash tool call after `launch` returns. Do not shell-chain it onto `launch` and do not background it with `&`; use Claude's native background Bash facility so Claude owns and displays the task. The owner can see/open the background task (`/tasks`), continue talking to the parent, and the task's completion becomes the wake signal.

On wake: `reconcile-run` first, then gate/route/refill from durable state. The default observer deadline is 2h for Grunts and 6h for Analysts; if it expires while still live, inspect/reconcile and re-arm only if useful.

`follow` is observation only. It cannot establish semantic progress or PASS.

If native background Bash is unavailable, keep workers detached and conversation-first. Do not replace it with a foreground wait loop, a second hook, or an improvised daemon.

## Compaction

The installed `SessionStart` hook injects only the active-run / `reconcile-run`-first orientation after compact/resume.
