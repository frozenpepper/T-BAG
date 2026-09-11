# T-BAG Operator Command Cookbook

Commands only. Policy: `SKILL.md`; lifecycle: `WORKSPACE.md`; wake behavior: `HARNESS.md` + selected adapter.

**OpenCode parent:** detached core launch → immediate `tbag_follow` with the exact tuple returned by `dsd_attempt.py launch`. Call even if auto-armed; it is idempotent/backward-compatible.

## Parent tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Run on owner turn/resume/wake/heartbeat. The packet owns reconcile, advance, monitoring, updates and end-state routing. After sending `owner_update`, acknowledge its token with `parent_tick.py ack-update`; on `completion-candidate`, replan or `parent_tick.py finish --reason "..."` after confirming plan exhaustion.

## Initialize runtime

```bash
python3 <skill>/scripts/dsd_task.py init-run \
  --project-root /abs/project --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 --max-workers 4 --escalation on
python3 <skill>/scripts/dsd_task.py set-runtime ...
python3 <skill>/scripts/prepare_worker_rules.py \
  --project-root /abs/project --run-root ... --revision 1 [--plan /abs/PLAN.md]
```

Runtime configuration: `CONFIG.md`.

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

FAIL resumes Planner; review again fresh. PASS permits acceptance/rules creation.

## Register an Analyst graph

Analyst preflights before handoff; registration repeats it. For an amendment/replan, **record `analysis-result --outcome replan` first, then register the graph**:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id phase-1 --task-id PLAN-X --outcome replan --report .../report.md
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan  --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
```

`register-plan` returns `ready_registered`.

## Launch / inspect / observe

```bash
python3 <skill>/scripts/dsd_attempt.py launch  --run-root ... --phase-id phase-1 --task-id T01
python3 <skill>/scripts/dsd_attempt.py inspect --run-root ... --phase-id phase-1 --task-id T01
```

`inspect` remains a diagnostic surface. Routine monitoring belongs to `parent_tick.py tick`: final-report/no-terminal attempts are retired after a short grace; silent anomalies use the existing role-history detector plus a confirmation window before retirement. Active logs remain progress-unknown and are not killed merely for being long.

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

Standalone Analyst findings use `accept --report ...`; replans require a graph. `resume` also closes Review follow-up triage when the frozen plan already covers every finding; `replan-resume` remains implementation/verification-only.

## Human escalation

```bash
python3 <skill>/scripts/dsd_task.py escalate --run-root ... --phase-id phase-1 --task-id T01 --report .../report.md
python3 <skill>/scripts/dsd_task.py resolve-escalation --run-root ... --phase-id phase-1 --task-id T01 \
  --decision .../decision.md --route resume|analysis|accept
```

On Human-blocked follow-up triage, `--route accept` cancels its findings and preserves the decision.

## Cleanup / interrupted process

Cleanup is lifecycle-owned; these are diagnostics/recovery only:

```bash
python3 <skill>/scripts/dsd_workspace.py cleanup-phase --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_task.py sweep-stale --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ... --dry-run
```

`cleanup --force --reason "..."` is explicit abandonment; never raw-delete shared cache/runtime paths.

## Same-session continuation

After `sweep-stale`, use `--resume-last` when available; workspace state remains authoritative if host session state is gone. Recovery must hand back with `analysis-result --outcome resume` first.

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role implementer --resume-last
```

## Owner-requested status

Use `dsd_task.py owner-status --run-root ... [--phase-id ...]`; `reconcile-run --details` is internal inventory. For legacy/non-gate reports only:

```bash
python3 <skill>/scripts/report_surface.py --report .../report.md --lines 8 --chars 1600
```

If insufficient, resume/clarify the worker; do not shadow-review.
