---
name: t-bag
version: 2.2.0
description: "Analysts resolve uncertainty; Grunts implement, review and fix bounded work in parallel."
license: MIT
compatibility: codex, claude-code, opencode, kilo
metadata:
  workspace-root: TBag
---

# T-BAG — The Beauty And the Grunt

> **Analysts think; Grunts execute/review; the parent routes.** The parent is normally a quiet control plane, not a repository engineer or shadow reviewer.

Run until `COMPLETED`, `HUMAN-BLOCKED`, `PAUSED-BY-USER`, or `ABANDONED`. Runs are re-entrant.

## Parent loop

Every owner turn/resume/wake starts with **`parent_tick.py tick`**, except an answer to an open `owner_question`: apply it, `resume-owner`, then tick.

1. **Harness first.** Install/check one parent adapter before launch. `bootstrap_ready=false` / `blocking_question` means native question UI + stop; after the requested restart/action rerun until ready. In deliberate CI/offline/headless operation use the installer's degraded-manual mode instead of manufacturing a restart question. Missing Analyst/Grunt runtime: resolve supplied config or ask the user **once** through the native question UI; never invent it—`MISSING_RUNTIME_CONFIG` blocks.
2. **Authority first.** Substantial work needs an accepted plan. Goal-only: Goal Planner → fresh Plan Reviewer until PASS. Parent never authors or repairs technical plans.
3. **Expose only needed work.** Analyst findings may close as findings. Planning/replanning comes from Planner/Discovery/Surveyor briefs + `plan/task-graph.json`; register verbatim. Keep unresolved root cause/architecture with Analysts.
4. **Schedule safely.** Launch dependency-ready work to budget. Mutations use isolated worktrees; standalone read-only roles use a shared frozen project view. State-changing dependencies integrate first.
5. **Grunt loop.** Implementer → fresh Reviewer; FAIL → Fixer resumes that Reviewer → fresh Review; PASS → land. Out-of-brief obligations go to Analyst triage; ESCALATE uses the central ladder.
6. **Authority ladder.** Grunt → Analyst → Human. Stronger runtime profiles do not widen authority.
7. **Durable truth.** Evidence gating is not semantic PASS. Tick monitoring distinguishes active work, silence and final-report/no-terminal hangs; retirement preserves recovery state.
8. **Harness wake.** `OPENCODE.md` is the sole protocol: detached launch auto-arms when possible; a 60s deterministic completion pulse detects ended calls and a slower health heartbeat checks active orchestration. After launch, yield—never sleep/poll. Waiting/paused/ended runs do not heartbeat. Never run core `follow` or model-authored wait/poll loops. Routine parent control uses compact tick/status/show surfaces; full details are diagnostic-only.

## Non-negotiable boundaries

- **Authority/acceptance:** brief + typed authority define scope; evidence never widens it. Red predicates stay red; contract correction needs Analyst/Human authority.
- **Semantic truth:** accepted evidence is not automatically green. Preserve failed prerequisites and explicit `FAIL`/`BLOCKED`.
- **Review ownership:** fresh Reviewer owns task acceptance; Human may explicitly accept a Human-targeted escalation without rewriting its red Review. After PASS the parent does not shadow-review.
- **Succession:** supersession/deferral never erases obligations; closure needs a successor or Human cancellation.
- **Context:** workers get frozen rules, one role, selected skills, brief and typed inputs—not rich parent history or raw logs.
- **Cleanup:** lifecycle owns runtime cleanup. Never raw-delete shared `~/.cache/t-bag`.
- **Project-local scratch:** T-BAG diagnostics/repros/temp/handoffs stay under project `TBag/`; never `$TMPDIR`, `/tmp`, `/private/var/...` or external paths unless the Human explicitly requests them.

## Owner communication

Two channels only. **`owner_question`** is blocking authority/input after deterministic + Analyst routes are exhausted: launch `actions_before_question`, `wait-owner`, use the harness-native question UI, then end the turn. Both heartbeat lanes stay suspended until the answer is applied and `resume-owner` runs. Plain chat is invalid; do not ask Humans for choices precedent/Analyst authority can resolve.

**`owner_notice`** is passive progress: render `━━ T-BAG UPDATE ━━`, send the bounded digest, then ack. Never bury questions or sell task counts as progress. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**.

## Instruction architecture

Keep policy single-owned. `README.md` is the documentation map; worker context composition is defined in `CONTEXT.md`. When field evidence changes a rule, update its owning layer instead of copying the lesson into adjacent prompts.

## Cold references

Use `PROMPTS.md` for exact commands, `WORKSPACE.md` for mechanics, `HARNESS.md` / `WORKER-CLI.md` for parent/worker adapters, `CONFIG.md` for runtime configuration, and `EVALS.md` for behavioral release evaluation.
