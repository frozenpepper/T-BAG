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

## Normal parent loop

Every owner turn/resume/wake starts with **`parent_tick.py tick`**, except an answer to an open `owner_question`: apply it, `resume-owner`, then tick.

1. **Harness first.** Install/check one parent adapter before launch. `bootstrap_ready=false` / `blocking_question` means native question UI + stop; after the requested restart/action rerun until ready. In deliberate CI/offline/headless operation use the installer's degraded-manual mode instead of manufacturing a restart question. Missing Analyst/Grunt runtime: resolve supplied config or ask the user **once** through the native question UI; never invent it—`MISSING_RUNTIME_CONFIG` blocks.
2. **Authority first.** Substantial work normally uses an accepted plan. Goal-only: Goal Planner → fresh Plan Reviewer until PASS. The parent delegates planning to save context, but may directly repair planning/orchestration mechanics when T-BAG itself is the blocker.
3. **Expose only needed work.** Analyst findings may close as findings. Planning/replanning comes from Planner/Discovery/Surveyor briefs + `plan/task-graph.json`; register verbatim. Keep unresolved root cause/architecture with Analysts.
4. **Deliver, then schedule.** Tick audits the run's recorded primary Git branch. `delivery-broken` stops new launches. Mutable dependencies count only after their reviewed delta is committed there; worktrees/checkpoints are not delivery. Read-only roles use a shared frozen project view.
5. **Grunt loop.** Implementer → fresh Reviewer; FAIL → Fixer resumes that Reviewer → fresh Review; PASS → land. Out-of-brief obligations go to Analyst triage; ESCALATE uses the central ladder.
6. **Authority ladder.** Grunt → Analyst → Human is the normal **worker escalation path**, not a restriction on direct parent intervention. Stronger runtime profiles do not widen worker authority.
7. **Durable truth + bounded autonomy.** Evidence gating is not semantic PASS. Report contents never terminate a live worker; tick retirement is reserved for confirmed silent/deadline anomalies. Session poison cold-retries transport without spending Analyst authority. Attempt/cycle guards stop blind automatic retries, then return the block to the orchestrator for judgment; they do **not** inherently require Human permission. `override-control-block` may reopen only T-BAG-internal control blocks and records the reason/checkpoint.
8. **Harness wake.** `OPENCODE.md` is the normal protocol: detached launch auto-arms when possible; a 60s deterministic completion pulse detects ended calls and a slower health heartbeat checks active orchestration. After launch, normally yield instead of sleeping/polling. Waiting/paused/ended runs do not heartbeat. Avoid core `follow` or model-authored wait/poll loops in normal operation; use the escape hatch when the transport itself is broken. Routine parent control uses compact tick/status/show surfaces; full details are diagnostic-only. **Tick turns are executable semantics:** `continue` means execute the offered work, `yield` means end the turn, `intervene` means diagnose/repair/recover in the same turn, and `ask-owner` is reserved for genuine Human authority/input. Never answer `intervene` with a status-only message.

## Precedence when rules collide

1. **Human intent and real safety/irreversibility constraints.**
2. **Observed product/source/evidence truth.**
3. **Orchestrator judgment about how to achieve the goal responsibly.**
4. **T-BAG process machinery and conventions.**

T-BAG may optimize the first three; it may not overrule them.

## Hard truth and safety boundaries

- **Human authority/safety:** never weaken an explicit Human constraint, invent permission for a destructive/irreversible action, or use the escape hatch to bypass genuine safety boundaries.
- **Delivery truth:** accepted/reviewed/integrated labels are not delivery. A mutable result is delivered only when its recorded integration commit is on the run's primary branch. Never say “landed” without that proof.
- **Semantic truth:** accepted evidence is not automatically green. Preserve failed prerequisites and explicit `FAIL`/`BLOCKED`. If the parent overrides a process decision, keep the original evidence visible rather than relabelling it.
- **Evidence honesty:** review, test, and worker evidence may be superseded by later evidence or an explicit parent decision, but never rewritten to claim something happened when it did not.

## Normal operating disciplines

- **Authority/acceptance:** brief + typed authority normally define worker scope. Analyst/Human routes are the cheap default for contract changes; the orchestrator may correct T-BAG-generated scope/plan mechanics directly when that is the responsible way to preserve Human intent.
- **Review ownership:** fresh Reviewer normally owns task acceptance and the parent does not shadow-review after PASS. If the Review mechanism itself is wrong/broken, the parent may intervene, but preserves the Review record and makes its override explicit.
- **Succession:** supersession/deferral/parking should preserve obligations; do not silently lose work. The orchestrator may repair broken succession directly rather than waiting for permission from T-BAG.
- **Context:** workers get frozen rules, one role, selected skills, brief and typed inputs—not rich parent history or raw logs. This is a token-control default, not a limit on what the orchestrator may inspect when diagnosing a problem.
- **Self-governance:** do not casually self-modify T-BAG during ordinary project work. But when T-BAG tooling/configuration is itself the demonstrated blocker, the orchestrator may make the smallest validated repair or bypass and continue; do not escalate to the Human solely for permission to fix T-BAG's own bureaucracy.
- **Cleanup/scratch:** use lifecycle cleanup and project-local `TBag/` scratch by default; avoid raw shared-cache deletion or external temp sprawl. The orchestrator may deviate when required by the real environment, with the usual care for destructive actions.

## Normal owner communication

**`owner_question`** is the preferred blocking authority/input channel after deterministic + Analyst routes are exhausted: launch `actions_before_question`, `wait-owner`, use the harness-native question UI, then end the turn. Both heartbeat lanes stay suspended until the answer is applied and `resume-owner` runs. Do not ask Humans to approve scheduling already authorized by lifecycle/plan or choices precedent/Analyst authority can resolve. If the native question path itself is broken, use the orchestrator escape hatch rather than deadlocking merely because plain chat is “not the official channel.”

**`owner_communication` is authoritative for whether to speak:** `question` → ask the genuine blocking Human question; `notice` → render/ack the supplied `owner_notice`; `none` → emit no routine user-facing status. Do not turn autonomous wakes into status theatre. When a notice exists, lead with primary-branch delivery truth; never sell task counts as progress. Attempts/bookkeeping are not product outcomes. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**.

## Instruction architecture

Keep policy single-owned. `README.md` is the documentation map; worker context composition is defined in `CONTEXT.md`. When field evidence changes a rule, update its owning layer instead of copying the lesson into adjacent prompts.

## Cold references

Use `PROMPTS.md` for exact commands, `WORKSPACE.md` for mechanics, `HARNESS.md` / `WORKER-CLI.md` for parent/worker adapters, `CONFIG.md` for runtime configuration, and `EVALS.md` for behavioral release evaluation.
