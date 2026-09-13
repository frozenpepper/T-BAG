# T-BAG with Claude Code

Use this file when Claude Code is the T-BAG parent. Worker CLIs are configured separately in `WORKER-CLI.md`.

Install the project adapter once:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness claude-code --project-root <project>
```

That gives Claude two useful pieces of T-BAG awareness:

- a small resume/compaction hook, so a fresh or compacted session knows which durable run to reconcile;
- a native status line backed by T-BAG's read-only status snapshot.

The status line refreshes every 5 seconds, even while Claude is otherwise idle. It can show the run and phase, registered-work progress, warnings, active Analysts and Grunts, what they are doing, model/session information and basic health. It costs no model tokens and cannot change the run.

If the project already has its own non-T-BAG `statusLine`, the installer leaves it alone. You can still render T-BAG manually:

```bash
python3 <project>/TBag/tools/tbag_render.py status --project-root <project>
```

## Watching workers without blocking the conversation

T-BAG workers themselves are detached. After a launch, Claude should attach one native background observer to that exact attempt:

1. Run `dsd_attempt.py launch` normally and keep the returned `event_dir`.
2. Run the following through Claude's **Bash tool with `run_in_background: true`**:

```bash
python3 <project>/TBag/tools/dsd_attempt.py follow \
  --run-root <run> --phase-id <phase> --task-id <task> --event-dir <event_dir>
```

Make that a separate Bash call. Do not append `&` and do not shell-chain it onto the launch. Claude's own background-task machinery should own the observer, so `/tasks` remains useful and observer completion can wake the parent naturally.

The status line and the background observer do different jobs: the status line gives the human a run-wide picture; `follow` gives Claude a per-attempt wake signal. Neither decides that work passed.

On every wake, owner turn or resume, enter the canonical parent tick. Worker deadlines are attempt-relative (normally 2h for Grunts, 6h for Analysts), so restarting the parent does not reset an old worker's clock.

If native background Bash is unavailable, leave workers detached and keep the conversation usable. Do not replace it with a foreground polling loop or an improvised daemon.

## After compaction or resume

The installed `SessionStart` hook restores only enough orientation to find the active run and re-enter the parent tick. The rest comes back from durable T-BAG state; the chat does not need to remember the project history.
