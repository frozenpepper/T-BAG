# T-BAG — Parent Harness Routing

Parent harness and technical-worker CLI are independent. Load exactly one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`). Worker transport is configured through `WORKER-CLI.md`.

## One durable parent loop

Technical workers run outside the parent conversation. Durable task/run state is truth; the canonical parent tick reconciles it, advances deterministic transitions, monitors live attempts, classifies stalls/attention, decides whether an owner update is due, and recognizes project-end candidates.

Harness wake mechanisms only decide **when to run the next tick**. They never gain task/model/semantic authority.

- **Claude Code:** run per-attempt `follow` as a native background Bash task. Its completion wakes Claude. The installed native status line independently renders the run-wide read-only T-BAG dashboard every 5 seconds.
- **OpenCode:** `OPENCODE.md` owns the exact protocol: detached core `launch`, immediate project-local `tbag_follow`, plus the low-frequency parent heartbeat. The companion TUI renders the same read-only status snapshot and exposes `/tbag`.
- **Codex:** project hooks preserve resume orientation. The stock CLI does not yet expose an arbitrary command-backed status item, so T-BAG provides `tbag_render.py status|watch` as a companion terminal surface rather than patching the Codex TUI.
- **Kilo:** use only the documented adapter surface; otherwise remain conversation-first.

`inspect`, `follow`, status renderers and host UI plugins are bounded observation/presentation. None may gate, review, accept, integrate, replan or mutate semantic lifecycle state.

There is no second generic scheduler/watcher daemon. OpenCode's transport heartbeat and Claude's native background task are harness wake mechanisms; correctness remains in the durable parent tick.

Install/check the selected adapter before the first long-running batch:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
```

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Harness adapters preserve only orientation and presentation. Every owner turn/resume/wake re-enters the parent tick. If multiple resumable runs exist, set `TBAG_RUN_ROOT`; T-BAG never treats a visual dashboard as run authority.
