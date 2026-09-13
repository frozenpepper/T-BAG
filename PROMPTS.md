# T-BAG Operator Command Cookbook

Commands only. Policy: `SKILL.md`; lifecycle: `WORKSPACE.md`; wake behavior: `HARNESS.md` + selected adapter.

**Normal rule:** semantic routing belongs to the worker report. `parent_tick.py tick` records explicit routing tokens automatically. Manual result commands record that same decision; `--outcome ...` is only a compatibility fallback for an older/tokenless report.

**OpenCode parent:** detached core launch → immediate `tbag_follow` with the exact tuple returned by `dsd_attempt.py launch`.

## Parent tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Run on owner turn/resume/wake/heartbeat. After sending `owner_update`, acknowledge its token with `parent_tick.py ack-update`. On `completion-candidate`, replan or `parent_tick.py finish --reason "..."` after confirming plan exhaustion.

## Initialize runtime

```bash
python3 <skill>/scripts/dsd_task.py init-run \
  --project-root /abs/project --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 --max-workers 4 --escalation on
python3 <skill>/scripts/dsd_task.py set-runtime ...
python3 <skill>/scripts/prepare_worker_rules.py \
  --project-root /abs/project --run-root ... --revision 1 [--plan /abs/PLAN.md]
```

## Goal-only bootstrap

Goal Planner → fresh Plan Reviewer:

```bash
python3 <skill>/scripts/dsd_task.py register-direct \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN \
  --brief .../goal-plan.md --kind analysis --role goal-planner --tier analyst --no-integration
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN [--authority-input ...]
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id bootstrap --task-id GOAL-PLAN

python3 <skill>/scripts/dsd_task.py register-direct \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW \
  --brief .../review.md --kind analysis --role plan-reviewer --tier analyst --no-integration \
  --reviews-task GOAL-PLAN
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_task.py plan-review \
  --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW --report .../report.md
```

FAIL returns the Goal Planner for revision; the next proposal gets a fresh review. PASS permits acceptance/rules creation.

## Register an Analyst graph

For amendment/replan, the report starts `REPLAN` or `REPLAN+RESUME`; record that disposition before registering its graph:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id phase-1 --task-id PLAN-X --report .../report.md
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
```

## Launch / inspect

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01
python3 <skill>/scripts/dsd_attempt.py inspect --run-root ... --phase-id phase-1 --task-id T01
```

`inspect` is diagnostic. Tick handles final-report/no-terminal recovery and silent anomalies; long runtime alone is not failure.

## Gate / Review / Fix

```bash
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id phase-1 --task-id T01 [--task-id T02 ...]
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role reviewer
python3 <skill>/scripts/dsd_task.py review --run-root ... --phase-id phase-1 --task-id T01 --report .../reviewer-N/report.md
python3 <skill>/scripts/dsd_workspace.py integrate --run-root ... --phase-id phase-1 --task-id T01 --review-pass-report .../reviewer-N/report.md
```

The Reviewer owns `PASS`/`FAIL`/`ESCALATE`; the parent never re-decides it. `--review-pass-report` validates and records that gated PASS, accepts it and integrates. FAIL opens the Fixer lane; Fixer resumes that Reviewer session, then a **new** Reviewer judges the whole task.

Analyst diagnosis/recovery routing is also report-owned:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result \
  --run-root ... --phase-id phase-1 --task-id T01 --report .../discovery-N/report.md
```

Lifecycle reports use `RESUME`, `REPLAN`, `REPLAN+RESUME`, `ESCALATE`, or `ESCALATE CAPABILITY`. Findings-only Analyst work uses `accept --report ...`. `REPLAN` requires a graph; `REPLAN+RESUME` is implementation/verification-only. Follow-up triage uses `RESUME` only when the frozen plan already covers every finding.

For a legacy report with no routing token, add the matching `--outcome ...` to `review`, `plan-review`, `context-review`, or `analysis-result`; never use it to override a report token.

## Human escalation

```bash
python3 <skill>/scripts/dsd_task.py escalate --run-root ... --phase-id phase-1 --task-id T01 --report .../report.md
python3 <skill>/scripts/dsd_task.py resolve-escalation --run-root ... --phase-id phase-1 --task-id T01 \
  --decision .../decision.md --route resume|analysis|accept
```

On Human-blocked follow-up triage, `--route accept` cancels its findings and preserves the decision.

## Cleanup / interrupted process

```bash
python3 <skill>/scripts/dsd_workspace.py cleanup-phase --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_task.py sweep-stale --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ... --dry-run
```

`cleanup --force --reason "..."` is explicit abandonment; never raw-delete shared cache/runtime paths.

## Same-session continuation

After `sweep-stale`, use `--resume-last` when available. Recovery hands back with a `RESUME` report recorded through `analysis-result --report ...` first.

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role implementer --resume-last
```

## Owner-requested status

Use `dsd_task.py owner-status --run-root ... [--phase-id ...]`; `reconcile-run --details` is internal inventory. For legacy/non-gate reports:

```bash
python3 <skill>/scripts/report_surface.py --report .../report.md --lines 8 --chars 1600
```

If insufficient, resume/clarify the worker; do not shadow-review.
