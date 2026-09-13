# T-BAG with Codex

Use this file when Codex is the T-BAG parent. Worker CLIs are configured separately in `WORKER-CLI.md`.

Install the project adapter once:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness codex --project-root <project>
```

The project hook restores T-BAG orientation after resume/compaction. Codex's stock status line currently exposes Codex-defined fields rather than arbitrary project commands, so T-BAG deliberately does **not** fork the Codex TUI or overwrite `[tui].status_line`.

Instead, use the same read-only T-BAG dashboard in a normal terminal pane.

One snapshot:

```bash
python3 <project>/TBag/tools/tbag_render.py status --project-root <project>
```

A continuously refreshing view:

```bash
python3 <project>/TBag/tools/tbag_render.py watch --project-root <project>
```

The `watch` view works well beside Codex in another terminal, tmux pane or zellij pane. It shows the run/phase, registered-work progress, active Analysts and Grunts, what each worker is doing, model/session/process/observer/deadline state, gates and anything needing attention. Close it whenever you like; it is presentation only and never mutates T-BAG state.

Codex hooks are still useful for session lifecycle and orientation, but they are not treated as a hidden scheduler or supervision daemon. Keep the parent conversation usable while workers run. Do not emulate wake-up by parking Codex in a foreground wait/poll loop.

On each owner turn, resume or supported hook wake, re-enter the canonical parent tick and let durable state decide whether to launch, route, update, intervene or finish.

If Codex later gains a stable arbitrary command-backed status item or plugin panel, the correct integration is simple: render the existing `tbag_status.py` snapshot there. Do not create a second Codex-specific state model.
