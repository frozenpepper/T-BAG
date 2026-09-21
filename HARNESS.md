# T-BAG — Parent Harness Routing

Parent harness and worker CLI are separate choices. Load one parent adapter (`CODEX.md`, `CLAUDE.md`, `KILO.md`, or `OPENCODE.md`); worker transport lives in `WORKER-CLI.md`.

## One supervision primitive

Durable T-BAG state is truth. Every owner turn/resume/wake re-enters the parent tick: `reconcile-run`, deterministic advance, monitoring, owner-update classification and end detection.

Harnesses own wake/presentation, never semantic authority. `owner_question` and bootstrap `blocking_question` use the native interactive question surface. `wait-owner` suspends completion + health wakes until `resume-owner`; detached results reconcile afterward. If questioning is unavailable, stop as harness-degraded.

- **Claude Code:** native background `follow` observer per live attempt; read-only status line.
- **OpenCode:** observer completion plus deterministic completion/health recovery wakes; see `OPENCODE.md`.
- **Codex:** hooks restore orientation; `tbag_render.py status|watch` supplies the dashboard.
- **Kilo:** use its documented adapter; without native wake, degrade conversation-first rather than inventing polling.

`inspect`, `follow`, renderers and UI only observe/present. Tick owns deadline recovery; adapters contain no second scheduler.

Install/check before a long run:

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root <project> --harness <codex|claude-code|opencode|kilo>
# deliberate offline/headless maintenance only
python3 <skill>/scripts/install_harness_adapter.py --headless --project-root <project> --harness <opencode|kilo>
```

Headless/manual mode emits no impossible restart question and claims no live wake transport; explicit parent ticks remain authoritative. Never infer headlessness merely from non-TTY execution.

## Compaction / resume

Execution truth remains `run.json` plus task-local state. Adapters restore orientation/presentation, not project memory. If multiple runs are resumable, set `TBAG_RUN_ROOT`; the dashboard is never run authority.
