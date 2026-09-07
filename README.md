# T-BAG — The Beauty And the Grunt

T-BAG is a plan-driven orchestration skill for long engineering work. Strong **Analyst** roles resolve uncertainty and shape work; cheaper **Grunt** roles implement, review, fix and verify bounded tasks; the parent model routes durable state instead of becoming the engineer itself.

## Core loop

```text
Goal/plan authority
      ↓
Analyst decomposition
      ↓
parallel Grunt tasks
      ↓
Implementer → fresh Reviewer → Fixer/review until PASS
      ↓
reviewed integration
      ↓
next READY work

Grunt ESCALATE → Analyst → Human (when required)
```

Read-only Analysts inspect a shared frozen project view. Mutating tasks use isolated Git worktrees. Ambient untracked checkout debris is not mirrored by default.

## Documentation architecture

T-BAG deliberately uses **one rule, one home**. Do not copy a new lesson into several files.

| Concern | Authority |
|---|---|
| Parent/orchestration behavior | `SKILL.md` |
| Operator commands | `PROMPTS.md` |
| Runtime/worker backend configuration | `CONFIG.md` |
| Task/worktree/lifecycle/integration mechanics | `WORKSPACE.md` |
| Context composition | `CONTEXT.md` |
| Parent harness wake/poke | `HARNESS.md` + one of `OPENCODE.md`, `CLAUDE.md`, `CODEX.md`, `KILO.md` |
| Worker CLI transport/storage | `WORKER-CLI.md` + one file under `worker-cli/` |
| Universal worker boundaries | `worker/COMMON.md` |
| Shared deep technical method | `worker/QUALITY.md` |
| Role-specific mandate | `worker/roles/*/SKILL.md` |
| Optional focused procedure | `worker/skills/*/SKILL.md` |
| Task-plan file schema | `worker/PLAN-AUTHORING.md` |

Worker launch context is intentionally compositional: COMMON + QUALITY when applicable + one role + selected project/worker skills + task brief + typed inputs. It does not load the parent manual.

## Start a run

```bash
python3 scripts/dsd_task.py init-run \
  --project-root /abs/project \
  --run-root /abs/project/TBag/runs/R1 \
  --run-id R1 --max-workers 4 --escalation on

```

Resolve missing Analyst/Grunt runtime choices from owner authority/config; never invent them. Runtime commands and precedence live in `CONFIG.md`. Then create a numbered frozen worker-rules revision:

```bash
python3 scripts/prepare_worker_rules.py \
  --project-root /abs/project \
  --run-root /abs/project/TBag/runs/R1 \
  --revision 1 [--plan /abs/accepted-plan.md]
```

With no accepted plan, normal execution is gated until Goal Planner → fresh Plan Reviewer produces accepted plan authority.

For an existing run, start with:

```bash
python3 scripts/dsd_task.py reconcile-run --run-root ...
```

Exact lifecycle commands are in `PROMPTS.md`.

## Design properties

- **Parent semantic abstention:** routine technical judgment belongs to assigned workers/reviewers, not the orchestrator.
- **Fresh independent Review:** task implementation does not self-approve; Reviewer is a fresh session. A Fixer resumes the Reviewer that found the defects, then a new Reviewer checks the whole task.
- **Typed escalation:** workers emit `ESCALATE`; the control plane routes Grunt → Analyst → Human.
- **Frozen acceptance:** a red required predicate cannot be redefined after observation to preserve PASS.
- **Durable recovery:** attempts, reports, terminal state, checkpoints and lifecycle records survive host wake/poke failures.
- **Parallelism by dependencies:** READY tasks fill worker budget; no artificial waves.
- **Quiet operation:** healthy orchestration is normally silent; owner reports are explicit, concise and backlog-complete.

## Compatibility

The public skill is T-BAG and new runs live under `PROJECT/TBag`. Historical helper/protocol names retain `dsd_*` / `dsd-*` prefixes in v2.2 to avoid needless migration churn; they do not imply a DeepSeek dependency.

## Verification

`tests/` covers deterministic mechanics and document/context composition. `evals/cases.jsonl` contains behavioral scenarios for real parent/worker models. `EVALS.md` explains the release evaluation boundary.
