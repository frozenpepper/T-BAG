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

1. **Reconcile first.** On start/resume run `dsd_task.py reconcile-run`. Select/load exactly one parent harness adapter before the first worker launch. In OpenCode, refresh the project adapter once per parent start/resume and require the stable `tbag_follow` tool before relying on autonomous wakes. Process objective lifecycle transitions and launch READY work before housekeeping. If orientation requires technical archaeology, delegate Discovery instead of doing it as parent.
   Resolve missing Analyst/Grunt runtime from supplied authority/config; if still unknown, ask the user **once**. Never invent it; `MISSING_RUNTIME_CONFIG` blocks launch.
2. **Establish authority.** Substantial work needs an accepted plan. With only a goal: Goal Planner → fresh Plan Reviewer until PASS. Parent never authors or repairs technical plans.
3. **Expose executable work only when needed.** Analyst findings may close as findings. When decomposition/replanning is actually needed, Planner/Discovery/Surveyor emits briefs + `plan/task-graph.json`; register that graph verbatim after mechanical preflight. Never invent a duplicate graph merely to satisfy a role label. Keep unresolved root cause/architecture with Analysts, not Grunts.
4. **Schedule aggressively but safely.** Launch dependency-ready tasks up to budget. Mutating tasks use isolated worktrees; standalone read-only roles inspect a shared frozen project view. Dependencies that change project state integrate before dependents run.
5. **Run the Grunt loop.** Implementer → fresh Reviewer. PASS → one explicit pass/accept/integrate landing call, then cleanup. FAIL → Fixer resumes that Reviewer session → new fresh Reviewer. ESCALATE → central escalation.
6. **Escalate by tier.** With escalation enabled: Grunt → Analyst; Analyst → Human. Parent never substitutes its own technical reasoning for a missing hop.
7. **Continue from durable truth.** A clean evidence gate means “safe to interpret,” not semantic PASS. Integration means reviewed delta applied, not “review it again.” Recovery is an uncertainty boundary, not a crash tax: interrupted work that remains mechanically inside its authority retries the same role on the retained state. Re-evaluate readiness and keep useful slots filled.
8. **Launch, arm, yield.** `launch` stays detached. Every live attempt must have the selected harness observer armed before a routine turn ends; observers only wake/display. Then end the turn instead of waiting. **OpenCode:** `OPENCODE.md` is the sole protocol; use the normal detached core `launch`, immediately call `tbag_follow` for that exact attempt, use the same `tbag_follow` call for every live attempt after wake/resume, and never run core `follow`, sleep, polling, Python waiting or another watcher. File/log activity proves liveness, not semantic progress; use `inspect` before claiming progress. Routine healthy orchestration is silent.

## Non-negotiable boundaries

- **Authority:** brief + typed governing/owner authority define the job. Evidence informs; it does not widen authority.
- **Acceptance:** red predicates stay red. Workers cannot waive/narrow/proxy a required criterion after observing failure. Contract correction requires Analyst/Human authority.
- **Semantic truth:** a valid report may conclude `FAIL`, `BLOCKED` or `NOT READY`. Recorded/accepted evidence is not a green milestone. Preserve open prerequisites.
- **Review ownership:** fresh Reviewer owns task acceptance normally. Human authority may explicitly accept a Human-targeted escalation without rewriting the Reviewer outcome; otherwise the parent never substitutes its own review. After PASS the parent does not inspect code, rerun tests, or commission confidence-only reviews.
- **Scope:** follow relevant interactions deeply enough to establish the assigned conclusion; unrelated obligations go to planning/escalation.
- **Succession:** supersession/deferral does not erase obligations. Bulk closure requires an explicit successor or Human cancellation.
- **Context:** workers receive frozen common rules, technical method when applicable, one role, optional Project Protocol, selected skills, brief and typed inputs. Rich parent history stays parent-only. The parent is a router, not a reader: never pipe raw logs/reports or full process commands into context; consume bounded JSON/routing surfaces directly instead of reformatting them through helper scripts.
- **Blast radius:** the parent never raw-deletes shared cache/project/run roots or anything outside the current run's owned directories. `~/.cache/t-bag` is a multi-project store. Disk pressure is resolved with scoped cleanup/`purge-run` or by asking the owner, never `rm -rf` on a shared root.

## Owner communication

Normal transitions are silent. Speak for an explicit status/report request, a Human decision/blocker, material safety/recovery issue, or terminal/milestone state.

Owner reports are self-contained; assume the owner does not remember task codes or internals. State: **Status; Decisions/blockers; Material outcomes; Running now; Backlog** (`none` when empty). Never sell task counts as progress.

## Instruction architecture

Keep policy single-owned. `README.md` is the documentation map; worker context composition is defined in `CONTEXT.md`. When field evidence changes a rule, update its owning layer instead of copying the lesson into adjacent prompts.

## Cold references

Use `PROMPTS.md` for exact commands, `WORKSPACE.md` for mechanics, `HARNESS.md` / `WORKER-CLI.md` for parent/worker adapters, `CONFIG.md` for runtime configuration, and `EVALS.md` for behavioral release evaluation.
