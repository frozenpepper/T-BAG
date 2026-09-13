# T-BAG — Claude Code Parent Adapter

Load only when the premium parent runs in Claude Code. Worker transport is configured separately through `WORKER-CLI.md`.

Install once per project:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness claude-code --project-root <project>
```

The adapter installs two presentation/control surfaces:

- the compact/resume orientation hook;
- a native Claude Code `statusLine` backed by the read-only T-BAG status snapshot.

The status line refreshes every 5 seconds even while the parent is idle. It shows run/phase/progress, Analyst and Grunt counts, warnings, and active worker sessions. Analyst and Grunt rows include the task purpose, role, elapsed time, model, session ID and health. It consumes no model tokens and has no orchestration authority.

If the project already defines a non-T-BAG custom `statusLine`, the installer preserves it and reports a conflict instead of overwriting it. The same T-BAG display remains available manually with:

```bash
python3 <project>/TBag/tools/tbag_render.py status --project-root <project>
```

## Launch + visible background follow

1. Launch normally with `dsd_attempt.py launch` and read the returned `event_dir`.
2. Immediately run this observer through Claude Code's **Bash tool with `run_in_background: true`**:

```bash
python3 <project>/TBag/tools/dsd_attempt.py follow \
  --run-root <run> --phase-id <phase> --task-id <task> --event-dir <event_dir>
```

Do this once for every newly launched live attempt, as its own Bash tool call after `launch` returns. Do not shell-chain it onto `launch` and do not background it with `&`; use Claude's native background Bash facility so Claude owns and displays the task. The owner can still inspect `/tasks`, while the persistent T-BAG status line shows the complete run-wide worker picture.

On wake, enter the canonical parent tick. Default worker deadlines remain 2h for Grunts and 6h for Analysts and are attempt-relative, not observer-arm-relative.

`follow` is observation only. The status line is presentation only. Neither can establish semantic progress or PASS.

If native background Bash is unavailable, keep workers detached and conversation-first. Do not replace it with a foreground wait loop, a second re-wake hook, or an improvised daemon.

## Compaction

The installed `SessionStart` hook injects only the active-run / parent-tick orientation after compact/resume. The status line reconstructs itself from durable state and therefore does not need chat memory.
