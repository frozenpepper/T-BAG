# T-BAG Operator Command Cookbook

Commands only. Parent policy is in `SKILL.md`; lifecycle semantics in `WORKSPACE.md`; harness wake behavior in `HARNESS.md` plus the selected adapter.

**OpenCode parent:** run each `dsd_attempt.py launch` normally, then immediately call `tbag_follow` with the exact returned `run_root`, `phase_id`, `task_id`, and `event_dir`. Call it even if auto-armed; the call is idempotent and preserves compatibility with older follow-only adapters.

## Resume / turn boundary

```bash
python3 <skill>/scripts/dsd_task.py reconcile-run --run-root ... [--phase-id ...] [--details]
python3 <skill>/scripts/dsd_task.py idle-check    --run-root ... [--phase-id ...]
```

Process returned actions before cleanup. When `observer_required` is true, attach the selected harness observer; never foreground-wait.

## Initialize runtime

```bash
python3 <skill>/scripts/dsd_task.py init-run \
  --project-root /abs/project --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 --max-workers 4 --escalation on
python3 <skill>/scripts/dsd_task.py set-runtime ...
python3 <skill>/scripts/prepare_worker_rules.py \
  --project-root /abs/project --run-root ... --revision 1 [--plan /abs/PLAN.md]
```

Use `CONFIG.md` for runtime selection/status commands.

## Goal-only bootstrap

Goal Planner → fresh Plan Reviewer:

```bash
python3 <skill>/scripts/dsd_task.py register-direct \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN \
  --brief .../goal-plan.md --kind analysis --role goal-planner --tier analyst --no-integration
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN [--authority-input ...]
python3 <skill>/scripts/dsd_attempt.py gate   --run-root ... --phase-id bootstrap --task-id GOAL-PLAN

python3 <skill>/scripts/dsd_task.py register-direct \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW \
  --brief .../review.md --kind analysis --role plan-reviewer --tier analyst --no-integration \
  --reviews-task GOAL-PLAN
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_attempt.py gate   --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_task.py plan-review \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW \
  --outcome pass|fail|escalate --report .../report.md
```

FAIL resumes the Planner then uses a **new** Plan Reviewer. PASS permits acceptance and worker-rules creation.

## Register an Analyst graph

Analyst preflights before handoff; registration repeats it:

```bash
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan  --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
```

`register-plan` returns `ready_registered`; use `ready` only for an explicit phase-wide inventory.

## Launch / inspect / observe

```bash
python3 <skill>/scripts/dsd_attempt.py launch  --run-root ... --phase-id phase-1 --task-id T01
python3 <skill>/scripts/dsd_attempt.py inspect --run-root ... --phase-id phase-1 --task-id T01
```

`inspect` reports elapsed/report age; running means **progress unknown**. Observation is harness-owned.

Observation is harness-owned: OpenCode follows canonical `OPENCODE.md` (detached core launch → immediate `tbag_follow`; the same `tbag_follow` re-arms live attempts after wake/resume); other adapters use `HARNESS.md`. Core defaults are 2h for Grunts and 6h for Analysts.

## Gate / Review / Fix

```bash
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id phase-1 --task-id T01 [--task-id T02 ...]
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role reviewer
python3 <skill>/scripts/dsd_workspace.py integrate --run-root ... --phase-id phase-1 --task-id T01 --review-pass-report .../reviewer-N/report.md
python3 <skill>/scripts/dsd_task.py review --run-root ... --phase-id phase-1 --task-id T01 --outcome fail|escalate --report .../reviewer-N/report.md
```

`gate` includes bounded `report_surface`. PASS is still the parent's explicit decision; `--review-pass-report` only collapses PASS → accept → integrate. FAIL launches a Fixer, then a **new** Reviewer. Analyst routing:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id phase-1 --task-id T01 \
  --outcome resume|replan|replan-resume|escalate --report .../discovery-N/report.md
```

Standalone Analyst findings use `accept --report ...`; `replan`/`replan-resume` require a graph. `replan-resume` also returns the current implementation/verification task to its prior lane.

## Human escalation

```bash
python3 <skill>/scripts/dsd_task.py escalate --run-root ... --phase-id phase-1 --task-id T01 --report .../report.md
python3 <skill>/scripts/dsd_task.py resolve-escalation --run-root ... --phase-id phase-1 --task-id T01 \
  --decision .../decision.md --route resume|analysis|accept
```

## Cleanup / interrupted process

```bash
python3 <skill>/scripts/dsd_workspace.py cleanup --run-root ... --phase-id phase-1 --task-id T01
```

Cleanup never destroys a live attempt or unresolved superseded carry-forward source, even with `--force`. Interrupted-process hygiene:

```bash
python3 <skill>/scripts/dsd_workspace.py cleanup-phase --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_task.py sweep-stale --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ... --dry-run
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ...
```

`~/.cache/t-bag` is shared. Never raw-delete it or sibling runtimes; use guarded run-scoped `purge-run`.

## Same-session continuation

After `sweep-stale`, use `--resume-last` when available; workspace state remains authoritative if host session state is gone. Recovery must hand back with `analysis-result --outcome resume` first.

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role implementer --resume-last
```

## Owner-requested status

Use `reconcile-run --details` for explicit status. Never `cat`/tail raw artifacts. For legacy/non-gate reports only:

```bash
python3 <skill>/scripts/report_surface.py --report .../report.md --lines 8 --chars 1600
```

If the bounded surface is insufficient, resume/clarify the worker; do not shadow-review the body.
