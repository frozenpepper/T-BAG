# T-BAG — Parent Harness Routing

The parent harness and the worker CLI are separate choices. Load exactly one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`); worker transport lives in `WORKER-CLI.md`.

## One supervision primitive

Durable T-BAG state is the source of truth. Every owner turn, resume or wake re-enters the parent tick: `reconcile-run`, deterministic advance, live-attempt monitoring, owner-update classification and project-end detection.

Harness integrations only answer two practical questions: **when should the parent wake up?** and **how should the human see status?** They never gain semantic authority.

- **Claude Code:** one native background `follow` observer per live attempt; a 5-second native status line shows the run-wide read-only dashboard.
- **OpenCode:** detached `launch` → `tbag_follow`, plus its low-frequency heartbeat; the TUI renders the same snapshot and exposes `/tbag`.
- **Codex:** hooks restore orientation; `tbag_render.py status|watch` provides the live dashboard in a companion terminal pane.
- **Kilo:** use only its documented adapter surface; if a native wake surface is unavailable, degrade conversation-first rather than inventing a polling daemon.

`inspect`, `follow`, renderers and UI plugins observe or present state. They cannot gate, review, accept, integrate, replan or otherwise decide semantic outcomes.

There is no second generic scheduler hidden in a harness adapter. Correctness stays in the durable parent tick.

Install/check the selected adapter before a long run:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
```

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Harness adapters restore orientation and presentation, not project memory. If multiple runs are resumable, set `TBAG_RUN_ROOT`; the dashboard is never run authority.
