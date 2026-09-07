# T-BAG — Codex Parent Adapter

Load only when the premium parent runs in Codex. Worker transport is configured separately through `WORKER-CLI.md`.

No reviewed Codex-native autonomous wake surface is assumed in this release. Technical workers remain detached and inspectable through `dsd_attempt.py inspect`.

When workers are live, use **conversation-first degraded mode**: keep the parent available to the owner and reconcile durable state on the next owner turn. Do not simulate wake-up with foreground `wait`/poll loops that make the parent unavailable.

Install the project adapter for compact/resume orientation:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness codex --project-root <project>
```

Its `SessionStart` hook injects the active run plus the instruction to begin with `reconcile-run`; execution truth remains task-local.
