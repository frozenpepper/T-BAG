# T-BAG — Kilo Code Parent Adapter

Load only when the premium parent runs in Kilo Code. Kilo is a parent harness, not a separate T-BAG worker lifecycle; worker transport is configured through `WORKER-CLI.md`.

No reviewed Kilo-native autonomous wake surface is assumed in this release. Keep technical workers detached, keep the parent available to the owner, and reconcile durable state on the next owner turn. `inspect` may be used at any time; do not use a foreground wait loop as a substitute for wake-up.

Install the project-local compaction adapter:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness kilo --project-root <project> --skill-root <skill>
```

The plugin injects the active run plus `reconcile-run`-first orientation into native compaction context. T-BAG creates no separate compaction state stream.
