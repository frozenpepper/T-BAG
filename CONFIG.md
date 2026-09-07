# T-BAG v2.2 Runtime Configuration

Worker runtime selection is a **user/project choice**, not a hidden skill default.
There is no hidden model/provider default.

At run startup the parent resolves Analyst/Grunt runtime choices from, in order:

1. the current explicit user request;
2. supplied handover/configuration files;
3. an existing active `run.json` when resuming;
4. project-level runtime policy, if one exists;
5. otherwise, ask the user once for only the missing consequential choices.

Do not ask for a choice already supplied. If sources conflict materially, ask rather than silently choosing.

## Initialize without inventing models

```bash
python3 scripts/dsd_task.py init-run \
  --project-root /abs/project \
  --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 \
  --escalation on
```

The response includes `missing_runtime_config`. A new run with no supplied runtime normally reports both `analyst` and `grunt` missing.

`--escalation on` is the default. When enabled, T-BAG centrally routes `Grunt → Analyst → Human`. Turn it off when the owner wants no automatic escalation routing:

```bash
python3 scripts/dsd_task.py set-escalation --run-root /abs/project/TBag/runs/R1 --mode off
```

Workers still report when they cannot responsibly continue; with routing disabled, the orchestrator must not silently replace the missing escalation with its own technical reasoning.

Check explicitly:

```bash
python3 scripts/dsd_task.py runtime-status --run-root /abs/project/TBag/runs/R1
```

## Record the user's choices

```bash
python3 scripts/dsd_task.py set-runtime \
  --run-root /abs/project/TBag/runs/R1 \
  --tier analyst \
  --driver opencode \
  --model commandcode/MiniMaxAI/MiniMax-M3

python3 scripts/dsd_task.py set-runtime \
  --run-root /abs/project/TBag/runs/R1 \
  --tier grunt \
  --driver opencode \
  --model opencode-go/hy3
```

The exact model string is driver/provider-specific. Resolve mechanical details with the selected cold CLI reference rather than asking the user to know implementation trivia.

A configured `run.json` is shaped like:

```json
{
  "format": "dsd-run-v2.2",
  "run_id": "R1",
  "project_root": "/abs/project",
  "runtime_root": "/external/cache/t-bag/.../R1",
  "max_workers": 4,
  "escalation_enabled": true,
  "worker_runtimes": {
    "analyst": {
      "driver": "opencode",
      "model": "commandcode/MiniMaxAI/MiniMax-M3",
      "options": {}
    },
    "grunt": {
      "driver": "opencode",
      "model": "opencode-go/hy3",
      "options": {}
    }
  }
}
```

Run terminal state is explicit durable orchestration state, not inferred from one blocked task:

```bash
python3 scripts/dsd_task.py set-run-status \
  --run-root /abs/project/TBag/runs/R1 \
  --status human-blocked \
  --reason "all remaining authorized work awaits owner authority"
```

Valid states are `active`, `completed`, `human-blocked`, `paused-by-user`, and `abandoned`. A task waiting on the Human does not require `human-blocked` while independent useful work can still advance.

`max_workers=4` is an operational default, not a model/provider decision. The user may override it when cost, machine capacity, or project policy makes it consequential.

## Support boundary

The task control plane stores driver separately from model. In v2.2 the wired technical-worker drivers are **OpenCode** and **Codex**. Other CLIs are unsupported task backends until they implement the same lifecycle adapter.

All wired drivers must enter through the core `dsd_attempt.py launch` lifecycle; parent-harness wake adapters observe that recorded attempt but must not bypass launch authority. Bypassing the core forfeits budget reservation, checkpoint/scope evidence and terminal/session bookkeeping. A missing tier runtime fails with `MISSING_RUNTIME_CONFIG`; an unwired driver fails loudly instead of falling back.
