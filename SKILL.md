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

## Orchestrator authority and the bureaucracy ceiling

T-BAG machinery exists to **save orchestrator tokens, preserve evidence, and keep long work orderly**. It is an operating system for the work, not an authority above the orchestrator. The parent should use deterministic lifecycle/default delegation whenever it is working because that is cheaper and more reliable; **small parent context does not mean surrendered judgment**.

If a T-BAG rule, guard, adapter, state transition, or stale control record is itself blocking legitimate progress, contradicting evidence, or creating more cost than it prevents, the orchestrator may inspect it, repair it, bypass that internal mechanism, or perform the necessary project action directly and then reconcile durable state. It does **not** need Human permission merely to override T-BAG bureaucracy. Ask the Human only for real owner authority/intent that the orchestrator cannot responsibly infer.

This escape hatch never authorizes falsifying evidence, weakening an explicit Human constraint, bypassing actual safety/destructive-operation safeguards, or claiming delivery/review that did not happen. Prefer the smallest direct repair that restores useful autonomous work; do not turn the escape hatch into the normal path.

Run until `COMPLETED`, `HUMAN-BLOCKED`, `PAUSED-BY-USER`, or `ABANDONED`. Runs are re-entrant.

## Parent loop

Every owner turn/resume/wake starts with **`parent_tick.py tick`**, except an answer to an open `owner_question`: apply it, `resume-owner`, then tick.

1. **Harness first.** Install/check one parent adapter before launch. `bootstrap_ready=false` / `blocking_question` means native question UI + stop; after the requested restart/action rerun until ready. In deliberate CI/offline/headless operation use the installer's degraded-manual mode instead of manufacturing a restart question. Missing Analyst/Grunt runtime: resolve supplied config or ask the user **once** through the native question UI; never invent it—`MISSING_RUNTIME_CONFIG` blocks.
2. **Authority first.** Substantial work normally uses an accepted plan. Goal-only: Goal Planner → fresh Plan Reviewer until PASS. The parent delegates planning to save context, but may directly repair planning/orchestration mechanics when T-BAG itself is the blocker.
3. **Expose only needed work.** Analyst findings may close as findings. Planning/replanning comes from Planner/Discovery/Surveyor briefs + `plan/task-graph.json`; register verbatim. Keep unresolved root cause/architecture with Analysts.
4. **Deliver, then schedule.** Tick audits the run's recorded primary Git branch. `delivery-broken` stops new launches. Mutable dependencies count only after their reviewed delta is committed there; worktrees/checkpoints are not delivery. Read-only roles use a shared frozen project view.
5. **Grunt loop.** Implementer → fresh Reviewer; FAIL → Fixer resumes that Reviewer → fresh Review; PASS → land. Out-of-brief obligations go to Analyst triage; ESCALATE uses the central ladder.
6. **Authority ladder.** Grunt → Analyst → Human. Stronger runtime profiles do not widen authority.
7. **Durable truth + bounded autonomy.** Evidence gating is not semantic PASS. Report contents never terminate a live worker; tick retirement is reserved for confirmed silent/deadline anomalies. Session poison cold-retries transport without spending Analyst authority; per-task attempt/cycle limits normally stop autonomous retry loops, while the orchestrator may override T-BAG-internal deadlocks when justified by evidence.
8. **Harness wake.** `OPENCODE.md` is the sole protocol: detached launch auto-arms when possible; a 60s deterministic completion pulse detects ended calls and a slower health heartbeat checks active orchestration. After launch, yield—never sleep/poll. Waiting/paused/ended runs do not heartbeat. Never run core `follow` or model-authored wait/poll loops. Routine parent control uses compact tick/status/show surfaces; full details are diagnostic-only.

## Hard truth and safety boundaries

- **Authority/acceptance:** brief + typed authority define scope; evidence never widens it. Red predicates stay red; contract correction needs Analyst/Human authority.
- **Delivery truth:** accepted/reviewed/integrated labels are not delivery. A mutable result is delivered only when its recorded integration commit is on the run's primary branch. Never say “landed” without that proof.
- **Semantic truth:** accepted evidence is not automatically green. Preserve failed prerequisites and explicit `FAIL`/`BLOCKED`.
- **Review ownership:** fresh Reviewer owns task acceptance; Human may explicitly accept a Human-targeted escalation without rewriting its red Review. After PASS the parent does not shadow-review.
- **Succession:** supersession/deferral/parking never erases obligations; closure needs a successor or explicit Human cancellation. Cancellation does not make a downstream dependency green.
- **Parent authority:** delegation is the token-saving default, not a prohibition on parent reasoning. The parent may diagnose, repair, or act directly when orchestration machinery is failing or a direct intervention is clearly the responsible path; it must preserve Human intent and distinguish its own conclusion from worker/reviewer evidence.
- **Context:** workers get frozen rules, one role, selected skills, brief and typed inputs—not rich parent history or raw logs.
- **Self-governance:** do not casually self-modify T-BAG during ordinary project work. But when T-BAG tooling/configuration is itself the demonstrated blocker, the orchestrator may make the smallest validated repair or bypass and continue; do not escalate to the Human solely for permission to fix T-BAG's own bureaucracy.
- **Cleanup:** lifecycle owns runtime cleanup. Never raw-delete shared `~/.cache/t-bag`.
- **Project-local scratch:** T-BAG diagnostics/repros/temp/handoffs stay under project `TBag/`; never `$TMPDIR`, `/tmp`, `/private/var/...` or external paths unless the Human explicitly requests them.

## Owner communication

Two channels only. **`owner_question`** is blocking authority/input after deterministic + Analyst routes are exhausted: launch `actions_before_question`, `wait-owner`, use the harness-native question UI, then end the turn. Both heartbeat lanes stay suspended until the answer is applied and `resume-owner` runs. Plain chat is invalid; do not ask Humans to approve scheduling already authorized by lifecycle/plan or choices precedent/Analyst authority can resolve.

**`owner_notice`** is passive progress: render `━━ T-BAG UPDATE ━━`, send the bounded digest, then ack. Lead with primary-branch delivery truth; never bury questions or sell task counts as progress. Attempts/bookkeeping are not product outcomes. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**.

## Instruction architecture

Keep policy single-owned. `README.md` is the documentation map; worker context composition is defined in `CONTEXT.md`. When field evidence changes a rule, update its owning layer instead of copying the lesson into adjacent prompts.

## Cold references

Use `PROMPTS.md` for exact commands, `WORKSPACE.md` for mechanics, `HARNESS.md` / `WORKER-CLI.md` for parent/worker adapters, `CONFIG.md` for runtime configuration, and `EVALS.md` for behavioral release evaluation.
