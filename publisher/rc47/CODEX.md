# T-BAG — Codex Parent Adapter

Load only when the premium parent runs in Codex. Worker transport is configured separately through `WORKER-CLI.md`.

Install the project adapter:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness codex --project-root <project>
```

The project hook restores compact/resume orientation. Codex's stock status line currently accepts only Codex-defined status items, not an arbitrary project command, so T-BAG does **not** fork or patch the Codex TUI and does not overwrite `[tui].status_line`.

Instead the installer exposes the same read-only dashboard used by the other harnesses as a terminal companion. One-shot view:

```bash
python3 <project>/TBag/tools/tbag_render.py status --project-root <project>
```

Live view, intended for a second terminal/tmux/zellij pane beside Codex:

```bash
python3 <project>/TBag/tools/tbag_render.py watch --project-root <project>
```

The live display refreshes without model calls and shows registered-plan/phase progress, active Analysts and Grunts, what each worker is doing, model/session/process/observer/deadline state, gates and attention items. Closing the display changes no T-BAG state.

Codex lifecycle hooks remain useful for resume/compaction, but they are not treated as a persistent visualization surface. If Codex later exposes arbitrary command-backed status items or a stable plugin panel in the stock CLI, point that surface at the same `tbag_status.py` snapshot rather than adding another state model.

When workers are live, keep the parent conversation-first. Do not simulate wake-up with a foreground wait/poll loop. Re-enter the canonical parent tick on each owner turn/resume/hook wake and let durable state decide what happens next.
