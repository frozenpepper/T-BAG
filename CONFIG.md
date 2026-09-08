# T-BAG v2.2 Runtime Configuration

Worker runtime selection is a **user/project choice**, not a hidden skill default. There is no hidden model/provider default.

T-BAG keeps **authority** separate from **model strength**. Grunt and Analyst are semantic lanes with different escalation responsibilities; the default runtime merely says which CLI/model normally serves each lane. A stronger model does not receive wider authority.

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
  --driver claude \
  --model claude-opus-5 \
  --effort medium

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
  "launch_start_interval_seconds": 3.0,
  "escalation_enabled": true,
  "worker_runtimes": {
    "analyst": {
      "driver": "claude",
      "model": "claude-opus-5",
      "options": {"effort": "medium"}
    },
    "grunt": {
      "driver": "opencode",
      "model": "opencode-go/hy3",
      "options": {}
    }
  }
}
```


## Optional capability ladders

Ordinary runs need only the two defaults above. Extra profiles are cold configuration and do not appear in task plans or routine launch decisions. Add them only when the owner wants a stronger same-authority option:

```bash
python3 scripts/dsd_task.py set-runtime-profile \
  --run-root /abs/project/TBag/runs/R1 \
  --tier analyst --name deep \
  --driver claude --model claude-opus-5 --effort medium

python3 scripts/dsd_task.py set-runtime-profile \
  --run-root /abs/project/TBag/runs/R1 \
  --tier analyst --name frontier \
  --driver codex --model astra-high --effort high --max-uses 1
```

Profiles are ordered in the order they are registered: `default → deep → frontier`. A worker may request exact `ESCALATE CAPABILITY` only when its task and authority remain correct but the current runtime cannot responsibly finish. T-BAG can then route the next configured profile in the **same** authority lane. `--max-uses` is optional owner spend authority; a launch attempt consumes one authorized use. If no stronger profile exists, normal Grunt → Analyst → Human authority escalation remains the fallback.

A parent may also select a named configured profile explicitly for a particular launch with `dsd_attempt.py launch --runtime-profile NAME`. Do not make the parent compare profiles on every task; the default should remain invisible unless owner authority or a capability escalation makes the choice relevant.

`--effort` is optional durable runtime intent. Claude maps it to native `--effort`; Codex maps it to `model_reasoning_effort`; OpenCode 2 maps it to the selected model's `--variant`. V2 variant names are model-specific, so T-BAG preserves the owner's configured name rather than guessing one. Stable OpenCode has no provider-independent effort flag, so encode that choice in its selected model/endpoint/profile instead.

Run terminal state is explicit durable orchestration state, not inferred from one blocked task:

```bash
python3 scripts/dsd_task.py set-run-status \
  --run-root /abs/project/TBag/runs/R1 \
  --status human-blocked \
  --reason "all remaining authorized work awaits owner authority"
```

Valid states are `active`, `completed`, `human-blocked`, `paused-by-user`, and `abandoned`. A task waiting on the Human does not require `human-blocked` while independent useful work can still advance.

`max_workers=4` is an operational default, not a model/provider decision. The user may override it when cost, machine capacity, or project policy makes it consequential.

`launch_start_interval_seconds=3.0` is a separate cold operational default. It does **not** reduce `max_workers`: detached attempt monitors may be created immediately, while a machine-global admission gate spaces only the instant at which their underlying worker CLI processes start. This protects CLI/database bootstrap collisions across different T-BAG runs and projects. A run can override the interval at `init-run` with `--launch-start-interval-seconds`; existing v2.2 runs that predate the field inherit the safe 3-second default when launched.

## Adapter boundary

The task control plane stores driver separately from model. First-class technical-worker adapters in this release are **OpenCode, OpenCode 2, Codex and Claude Code**. They exist because common mechanics should be precomputed once rather than repeatedly reconstructed by the parent. OpenCode 2 is worker-only for now: its beta plugin/server APIs are breaking changes, so parent-harness support is not claimed by copying the stable OpenCode adapter.

That list is not the semantic capability boundary of the skill. If the owner asks for an unusual available CLI/tool and a capable parent can preserve T-BAG's task/report/scope/session contract, the semantic instruction remains meaningful. Repeated paths should be promoted into a first-class adapter after field evidence rather than forcing every future parent to rediscover them. The built-in `dsd_attempt.py launch` path accepts only wired adapters because it promises specific lifecycle evidence; a missing adapter must never silently bypass those invariants.

All first-class drivers enter through core launch. Parent-harness wake adapters observe the recorded attempt but do not replace launch authority. A missing default lane runtime fails with `MISSING_RUNTIME_CONFIG`.
