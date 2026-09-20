# T-BAG Operator Command Cookbook

Commands only. Policy: `SKILL.md`; lifecycle: `WORKSPACE.md`; wake behavior: `HARNESS.md` + selected adapter.

Worker reports own semantic routing; `--outcome` is legacy fallback only.

## Parent tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Run on owner turn/resume/wake. For `owner_question_required`: run `actions_before_question`, then `parent_tick.py wait-owner --question-id <id>`, ask through the native UI, and end the turn. After applying the answer, `resume-owner --question-id <id>` then tick. Passive `owner_notice` is bannered and acknowledged. `completion-candidate` means finish or replan.

Do not pipe/filter/summarize stdout from `parent_tick.py tick` or `dsd_attempt.py launch` in the parent shell command. The OpenCode adapter consumes their structured JSON for immediate heartbeat/observer repair. RC64 also self-heals from durable state when that output is mangled, so this is a latency/diagnostic rule rather than a correctness dependency.

## Harness bootstrap

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root /abs/project --harness <parent-harness>
```

`bootstrap_ready=false` → ask its `blocking_question` natively and stop. After the requested restart/action, rerun until `bootstrap_ready=true`; launch nothing before that.

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
OpenCode V1 `tbag_follow` is diagnostics/re-arm only.

## Gate / Review / Fix

```bash
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id phase-1 --task-id T01 [--task-id T02 ...]
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id phase-1 --task-id T01 --role reviewer
python3 <skill>/scripts/dsd_task.py review --run-root ... --phase-id phase-1 --task-id T01 --report .../reviewer-N/report.md
python3 <skill>/scripts/dsd_workspace.py integrate --run-root ... --phase-id phase-1 --task-id T01 --review-pass-report .../reviewer-N/report.md
```

Reviewer owns `PASS`/`FAIL`/`ESCALATE`; `--review-pass-report` records PASS and integrates. FAIL → Fixer resumes that Reviewer → fresh Reviewer.

Analyst diagnosis/recovery routing is also report-owned:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result \
  --run-root ... --phase-id phase-1 --task-id T01 --report .../discovery-N/report.md
```

Lifecycle tokens: `RESUME`, `REPLAN`, `REPLAN+RESUME`, `ESCALATE`, `ESCALATE CAPABILITY`; findings-only uses `accept --report`. `REPLAN` needs a graph; `--outcome` only repairs legacy/tokenless reports.

## Human escalation

```bash
python3 <skill>/scripts/dsd_task.py escalate --run-root ... --phase-id phase-1 --task-id T01 --report .../report.md
python3 <skill>/scripts/dsd_task.py resolve-escalation --run-root ... --phase-id phase-1 --task-id T01 \
  --decision .../decision.md --route resume|analysis|accept
```

Tick supplies `owner_question`; native-ask it, save the answer as the decision file, resolve it, then `resume-owner`. Follow-up triage `--route accept` cancels its findings while preserving the decision.

## Cleanup / interrupted process

```bash
python3 <skill>/scripts/dsd_workspace.py cleanup-phase --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_task.py sweep-stale --run-root ... --phase-id phase-1
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ... --dry-run
```

`cleanup --force --reason "..."` is explicit abandonment; never raw-delete shared cache/runtime.

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
