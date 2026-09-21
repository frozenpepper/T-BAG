# T-BAG — Parent Harness Routing

The parent harness and the worker CLI are separate choices. Load exactly one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`); worker transport lives in `WORKER-CLI.md`.

## One supervision primitive

Durable T-BAG state is the source of truth. Every owner turn, resume or wake re-enters the parent tick: `reconcile-run`, deterministic advance, live-attempt monitoring, owner-update classification and project-end detection.

Harnesses own wake/presentation, never semantic authority. `owner_question` and bootstrap `blocking_question` always use the native interactive question surface; plain chat is invalid. `wait-owner` suspends completion + health heartbeats until `resume-owner`; detached workers may finish silently and reconcile after resume. If questioning is unavailable, stop as harness-degraded.

- **Claude Code:** one native background `follow` observer per live attempt; a 5-second native status line shows the run-wide read-only dashboard.
- **OpenCode:** observer completion is primary; a 60-second deterministic probe and slower health wake recover misses. Waiting/paused/ended runs are unenrolled. See `OPENCODE.md`.
- **Codex:** hooks restore orientation; `tbag_render.py status|watch` provides the live dashboard in a companion terminal pane.
- **Kilo:** use only its documented adapter surface; if a native wake surface is unavailable, degrade conversation-first rather than inventing a polling daemon.

`inspect`, `follow`, renderers and UI plugins only observe/present state. After the role deadline `follow` is not re-armed; tick owns recovery. No harness adapter contains a second scheduler.

Install/check the selected adapter before a long run:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
# CI/offline/headless maintenance only:
python3 <skill>/scripts/install_harness_adapter.py --headless --project-root <project> --harness <opencode|kilo>
```

Headless/manual mode suppresses impossible restart questions and does not claim autonomous wake transport is live; explicit parent ticks remain authoritative. Do not infer headlessness merely from non-TTY shell execution.

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Harness adapters restore orientation and presentation, not project memory. If multiple runs are resumable, set `TBAG_RUN_ROOT`; the dashboard is never run authority.
