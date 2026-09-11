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

Every owner turn, resume or harness wake starts with **`parent_tick.py tick`**. It reconciles, advances decided transitions, monitors live work and returns one continue/launch/yield/update/intervene/finish boundary. Wakes are hints, never supervision truth.

1. **Tick first.** Load one harness adapter, consume the tick packet, and never reconstruct a parallel monitor loop. Launch READY work before housekeeping; delegate technical archaeology to Discovery.
   Resolve missing Analyst/Grunt runtime from supplied authority/config; if still unknown, ask the user **once**. Never invent it; `MISSING_RUNTIME_CONFIG` blocks launch.
2. **Establish authority.** Substantial work needs an accepted plan. With only a goal: Goal Planner → fresh Plan Reviewer until PASS. Parent never authors or repairs technical plans.
3. **Expose executable work only when needed.** Analyst findings may close as findings. When decomposition/replanning is actually needed, Planner/Discovery/Surveyor emits briefs + `plan/task-graph.json`; register that graph verbatim after mechanical preflight. Never invent a duplicate graph merely to satisfy a role label. Keep unresolved root cause/architecture with Analysts, not Grunts.
4. **Schedule aggressively but safely.** Launch dependency-ready tasks up to budget. Mutating tasks use isolated worktrees; standalone read-only roles inspect a shared frozen project view. Dependencies that change project state integrate before dependents run.
5. **Run the Grunt loop.** Implementer → fresh Reviewer. PASS → land; FAIL → Fixer resumes that Reviewer → fresh Review. Material out-of-brief obligations use Review `Follow-up obligations`; new phase launches pause until Analyst triage. ESCALATE → central escalation.
6. **Escalate authority separately from runtime strength.** Grunt → Analyst → Human is the authority ladder. Optional stronger profiles stay cold until owner direction or exact `ESCALATE CAPABILITY`; stronger models never gain wider authority.
7. **Continue from durable truth.** Evidence gating is not semantic PASS. Tick monitoring distinguishes active work, confirmed silence and final-report/no-terminal hangs; lifecycle retirement preserves retained recovery state.
8. **Gate phases; launch/arm/yield attempts.** Non-bootstrap phases require fresh Phase Gates. In OpenCode, `OPENCODE.md` is the sole protocol: normal detached core `launch`, immediately call `tbag_follow`, then yield. Observer wakes are fast hints; heartbeat ticks recover missed wakes. Never run core `follow` or model-authored wait/poll loops.

## Non-negotiable boundaries

- **Authority:** brief + typed governing/owner authority define the job. Evidence informs; it does not widen authority.
- **Acceptance:** red predicates stay red. Workers cannot waive/narrow/proxy a required criterion after observing failure. Contract correction requires Analyst/Human authority.
- **Semantic truth:** a valid report may conclude `FAIL`, `BLOCKED` or `NOT READY`. Recorded/accepted evidence is not a green milestone. Preserve open prerequisites.
- **Review ownership:** fresh Reviewer owns task acceptance normally. Human authority may explicitly accept a Human-targeted escalation without rewriting the Reviewer outcome; otherwise the parent never substitutes its own review. After PASS the parent does not inspect code, rerun tests, or commission confidence-only reviews.
- **Scope:** follow relevant interactions deeply enough to establish the assigned conclusion; unrelated obligations go to planning/escalation.
- **Succession:** supersession/deferral does not erase obligations. Bulk closure requires an explicit successor or Human cancellation.
- **Context:** workers receive frozen common rules, technical method when applicable, one role, optional Project Protocol, selected skills, brief and typed inputs. Rich parent history stays parent-only. The parent is a router, not a reader: never pipe raw logs/reports or full process commands into context; consume bounded JSON/routing surfaces directly instead of reformatting them through helper scripts.
- **Cleanup/blast radius:** runtime cleanup is lifecycle-owned; the parent never inventories or raw-deletes cache paths. T-BAG reaps only mechanically disposable state inside the current run's owned runtime. `~/.cache/t-bag` is shared; never `rm -rf` it.

## Owner communication

The tick decides when an owner update is due: decisions/recovery/end-state immediately, plus a periodic active-work heartbeat. Send its purpose-first digest, then acknowledge its token; never ack an unsent update. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**. Never sell task counts as progress. `completion-candidate` is an explicit end boundary: finish only after confirming accepted-plan obligations are exhausted; otherwise replan.

## Instruction architecture

Keep policy single-owned. `README.md` is the documentation map; worker context composition is defined in `CONTEXT.md`. When field evidence changes a rule, update its owning layer instead of copying the lesson into adjacent prompts.

## Cold references

Use `PROMPTS.md` for exact commands, `WORKSPACE.md` for mechanics, `HARNESS.md` / `WORKER-CLI.md` for parent/worker adapters, `CONFIG.md` for runtime configuration, and `EVALS.md` for behavioral release evaluation.
