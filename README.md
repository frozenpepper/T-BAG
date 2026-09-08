# T-BAG — The Beauty And the Grunt

I think of modern LLM skills as **semantic software**. Traditional software expects fixed inputs and APIs; a skill can take goals, constraints, model choices, exceptions and changes of mind in natural language. The model supplies judgment; the skill supplies durable structure and mechanics.

T-BAG applies that idea to one problem: **how do you keep attacking hard technical work for hours or days without the orchestrator becoming the bottleneck, losing the plot after compaction, or asking a human to rescue every setback?**

## T-BAG the problem

T-BAG is for problems you do not want an agent to merely discuss. **Literally T-BAG the problem: stomp on it repeatedly until it stops being a problem.**

Give it a goal or an accepted plan:

```text
problem
  ↓
Analyst plans / decomposes / resolves uncertainty
  ↓
parallel Grunt work
  ↓
Implement → fresh Review → Fix → fresh Review until PASS
  ↓
reviewed integration → fresh Phase Gate → next attack
```

A Grunt that hits something outside its authority escalates instead of inventing architecture:

```text
Grunt → Analyst → Human
```

Runtime strength is separate from authority. Cheap models can do repetitive implementation/review work; stronger reasoning stays cold until needed. A stronger model never silently gains a wider job.

The point is not one giant agent that knows everything. It is a structure that keeps hitting the problem from fresh angles, reviews its own work adversarially, recovers from failure, replans when assumptions break, and continues until the plan is exhausted.

## The orchestrator is lightweight on purpose

The parent is deliberately **not** the repository engineer, main reviewer, or walking project memory. It routes.

Workers read source, run tests, write code and produce evidence. Reviewers start fresh. Fixers resume the Reviewer that found the defect. Analysts own architecture, replanning and hard diagnosis. Deterministic tooling owns task state, dependencies, worktrees, checkpoints and integration.

That keeps the parent's token diet small enough to orchestrate for days instead of drowning in source code, logs and worker history.

A task fails. A reviewer catches another bug. A dependency was wrong. One model gets stuck. The plan changes. The parent gets compacted overnight. **The run keeps moving.**

## Memory lives outside the chat

Plans, task briefs, attempts, reports, reviews, checkpoints, phase gates and Git carry the durable truth. Chat is a control surface over that state, not its only copy.

So the parent can be compacted, restarted, or replaced by a fresh session and reconcile from recorded state. It does not need to remember what task 37 was doing three days ago.

**Small active context, large durable memory.** That lets the orchestrator stay useful for very large jobs.

## What using it can feel like

Already have a plan?

```text
/t-bag process file plan.md.
Use Muse Spark 1.3 Contributor through opencode-go as Grunt,
and Opus 5 Medium through Claude as Analyst.
Work through the plan autonomously and interrupt me only for decisions that genuinely need me.
```

No plan yet?

```text
/t-bag The application's boot process has become painfully slow.
Investigate the real production path, create and independently review a serious plan,
then execute it. Prioritize root causes over patches and continue until the plan is complete.
```

Steer a live run:

```text
If some tasks are stuck, spend one Analyst call on Astra (high) through Codex.
Use it only where it adds value, then continue with the normal runtime.
```

## What T-BAG provides

- **Goal → reviewed plan → executable work**, or execution of a plan you already have.
- **Parallel Grunts** with isolated mutable worktrees and frozen read-only views.
- **Fresh review loops:** Implementer → Reviewer → Fixer → new Reviewer until PASS.
- **Analyst replanning/escalation** for uncertainty, architecture and broken assumptions.
- **Human escalation** only when owner authority is genuinely required.
- **Independent Phase Gates** against the accumulated goal, not task-count theater.
- **Durable recovery** across crashes, compaction and parent-session replacement.
- **Mixed runtimes:** OpenCode, OpenCode 2, Codex and Claude have first-class worker adapters.
- **Safe concurrency:** parallel workers, staggered fragile CLI starts.

T-BAG's rule is simple: **let LLMs reason where meaning matters; remember the decision once; mechanize the stable consequence.**

## Where to look next

| Concern | Authority |
|---|---|
| Parent/orchestration behavior | `SKILL.md` |
| Operator commands | `PROMPTS.md` |
| Runtime/model configuration | `CONFIG.md` |
| Task/worktree/lifecycle/integration mechanics | `WORKSPACE.md` |
| Context composition | `CONTEXT.md` |
| Harness behavior | `HARNESS.md` + harness-specific file |
| Worker roles | `worker/` |
| Release evaluation | `EVALS.md` + `evals/` |

T-BAG is MIT licensed.
