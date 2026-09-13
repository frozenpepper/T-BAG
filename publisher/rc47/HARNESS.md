# T-BAG — Parent Harness Routing

Parent harness and worker CLI are independent. Load exactly one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`). Worker transport lives in `WORKER-CLI.md`.

## One supervision primitive

Durable task/run state is truth. Every owner turn, resume or wake enters the canonical parent tick: `reconcile-run`/deterministic advance, live-attempt monitoring, owner-update classification and project-end detection.

Harness integrations only decide **when to wake** and **how to present status**. They never gain semantic authority.

- **Claude Code:** per-attempt `follow` runs as native background Bash; completion wakes Claude. A native 5-second status line renders the read-only run dashboard.
- **OpenCode:** detached `launch` → `tbag_follow`, plus the low-frequency heartbeat. Its TUI shows the same snapshot and exposes `/tbag`.
- **Codex:** project hooks preserve resume orientation. Because the stock status line currently accepts only built-in items, use `tbag_render.py status|watch` in a companion pane; T-BAG does not patch the Codex TUI.
- **Kilo:** use only its documented adapter surface; otherwise remain conversation-first.

`inspect`, `follow`, status renderers and host UI plugins are observation/presentation only. They cannot gate, review, accept, integrate, replan or mutate semantic lifecycle state.

There is no second generic scheduler/watcher daemon. Correctness stays in the parent tick.

Install/check the selected adapter before long-running work:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
```

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Harness adapters preserve orientation and presentation. If multiple resumable runs exist, set `TBAG_RUN_ROOT`; a dashboard is never run authority.
