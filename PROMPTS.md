# T-BAG Operator Command Cookbook

Commands only. Policy: `SKILL.md`; lifecycle: `WORKSPACE.md`; wake behavior: `HARNESS.md` + the selected adapter. Worker reports own semantic routing; `--outcome` is legacy fallback only.

## Parent tick

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Run on owner turn/resume/wake. Default output is compact; `state_changed=false` means routing state is materially unchanged. Use `tick --details` only for bounded control/transport diagnosis.

For `owner_question_required`: execute `actions_before_question`, then:

```bash
python3 <skill>/scripts/parent_tick.py wait-owner --run-root ... --question-id ...
# ask with the harness-native question UI and end the turn
python3 <skill>/scripts/parent_tick.py resume-owner --run-root ... --question-id ...
```

Render/ack `owner_notice`. `completion-candidate` means finish or replan. Do not pipe/filter tick or launch stdout when the adapter needs structured output.

## Harness bootstrap

```bash
python3 <skill>/scripts/install_harness_adapter.py --project-root /abs/project --harness <harness>
```

`bootstrap_ready=false` → use its native `blocking_question`, then rerun after the requested host action. For deliberate offline/headless operation only, add `--headless` or set `TBAG_HEADLESS=1`; this selects manual parent ticks instead of an impossible restart gate.

## Initialize

```bash
python3 <skill>/scripts/dsd_task.py init-run \
  --project-root /abs/project --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 --max-workers 4 --escalation on
python3 <skill>/scripts/dsd_task.py set-runtime ...
python3 <skill>/scripts/prepare_worker_rules.py \
  --project-root /abs/project --run-root ... --revision 1 [--plan /abs/PLAN.md]
```

## Goal-only bootstrap

Register/launch/gate the Goal Planner, then one reusable fresh-session Plan Reviewer:

```bash
python3 <skill>/scripts/dsd_task.py register-direct --run-root ... --phase-id bootstrap \
  --task-id GOAL-PLAN --brief .../goal-plan.md --kind analysis --role goal-planner --tier analyst --no-integration
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id bootstrap --task-id GOAL-PLAN

python3 <skill>/scripts/dsd_task.py register-direct --run-root ... --phase-id bootstrap \
  --task-id GOAL-PLAN-REVIEW --brief .../review.md --kind analysis --role plan-reviewer --tier analyst \
  --no-integration --reviews-task GOAL-PLAN
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id bootstrap --task-id GOAL-PLAN-REVIEW
python3 <skill>/scripts/dsd_task.py plan-review --run-root ... --phase-id bootstrap \
  --task-id GOAL-PLAN-REVIEW --report .../report.md
```

FAIL returns the Goal Planner for revision; the next proposal receives a fresh review. PASS permits acceptance/rules creation.

## Analyst graph

For `REPLAN` / `REPLAN+RESUME`, record the report-owned disposition, preflight, then register verbatim:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id P --task-id PLAN-X --report .../report.md
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id P --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan --run-root ... --phase-id P --plan .../plan/task-graph.json
```

## Launch / inspect

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id P --task-id T01
python3 <skill>/scripts/dsd_attempt.py inspect --summary --run-root ... --phase-id P --task-id T01
```

Launch → yield. Do not sleep/poll. Observer/heartbeat wake returns control. `inspect --summary` is diagnostic; `inspect --details` is cold forensics.

## Gate / Review / Fix / land

```bash
python3 <skill>/scripts/dsd_attempt.py gate --run-root ... --phase-id P --task-id T01
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id P --task-id T01 --role reviewer
python3 <skill>/scripts/dsd_task.py review --run-root ... --phase-id P --task-id T01 --report .../reviewer-N/report.md
python3 <skill>/scripts/dsd_workspace.py integrate --run-root ... --phase-id P --task-id T01 --review-pass-report .../reviewer-N/report.md
```

Reviewer: `PASS|FAIL|ESCALATE|ESCALATE CAPABILITY`. FAIL → Fixer resumes that Reviewer → fresh Reviewer. Analyst lifecycle reports use `RESUME|REPLAN|REPLAN+RESUME|ESCALATE|ESCALATE CAPABILITY`:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id P --task-id T01 --report .../report.md
```

Use `--outcome` only for already-generated legacy/tokenless reports.

## Human escalation

```bash
python3 <skill>/scripts/dsd_task.py escalate --run-root ... --phase-id P --task-id T01 --report .../report.md
python3 <skill>/scripts/dsd_task.py resolve-escalation --run-root ... --phase-id P --task-id T01 \
  --decision .../decision.md --route resume|analysis|accept
```

`resume` returns the existing lane; `analysis` opens bounded Analyst authority; `accept` records explicit Human acceptance/cancellation at that boundary.

## Interrupted work / cleanup

```bash
python3 <skill>/scripts/dsd_task.py sweep-stale --run-root ... --phase-id P
python3 <skill>/scripts/dsd_workspace.py cleanup-phase --run-root ... --phase-id P
python3 <skill>/scripts/dsd_workspace.py purge-run --run-root ... --dry-run
```

After `sweep-stale`, use `--resume-last` when continuity is valid:

```bash
python3 <skill>/scripts/dsd_attempt.py launch --run-root ... --phase-id P --task-id T01 --role implementer --resume-last
```

## Status / diagnostics

Compact is the default; `--summary` makes intent explicit:

```bash
python3 <skill>/scripts/dsd_task.py owner-status --summary --run-root ... [--phase-id P]
python3 <skill>/scripts/dsd_task.py show --summary --run-root ... --phase-id P --task-id T01
python3 <skill>/scripts/dsd_task.py reconcile-run --run-root ... [--phase-id P]
python3 <skill>/scripts/report_surface.py --report .../report.md --lines 8 --chars 1600
```

Use `--details` only when the compact surface cannot answer a concrete diagnostic question. Do not shadow-review worker semantics.
