# T-BAG — The Beauty And the Grunt

I think of modern LLM skills as **semantic software**: natural language supplies goals, constraints and exceptions; the model supplies judgment; the skill supplies durable structure and mechanics.

T-BAG applies that idea to one problem: **how do you keep attacking hard technical work for hours or days without the orchestrator becoming the bottleneck or losing the plot after compaction?**

## T-BAG the problem

T-BAG is for problems you do not want an agent to merely discuss. **Literally T-BAG the problem: stomp on it repeatedly until it stops being a problem.**

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

Runtime strength is separate from authority. Cheap models can do repetitive work; stronger reasoning stays cold until needed. The point is not one giant agent. It is a structure that keeps hitting the problem, reviews itself adversarially, recovers, replans when assumptions break, and continues until the plan is exhausted.

## Install / setup

T-BAG is a **whole skill folder**: keep the repo intact; `SKILL.md` alone is not enough. You need Python 3 and whichever worker CLIs you choose, installed/authenticated.

For Claude Code:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/frozenpepper/T-BAG.git ~/.claude/skills/t-bag
```

Start a new Claude Code session and invoke `/t-bag ...`.

Update with:

```bash
git -C ~/.claude/skills/t-bag pull --ff-only
```

For another supported parent, put the repo in that host's skill directory. Parent adapters exist for **Claude Code, OpenCode, Codex and Kilo**; worker adapters for **OpenCode, OpenCode 2, Codex and Claude**.

On first use T-BAG resolves missing Grunt/Analyst runtime choices from your prompt/config (or asks once), then installs/checks the project-local harness adapter. There is no hidden model/provider default.

## The orchestrator is lightweight on purpose

The parent is deliberately **not** the repository engineer, main reviewer, or walking project memory. It routes.

Workers read source, run tests, write code and produce evidence. Reviewers start fresh. Fixers resume the Reviewer that found the defect. Analysts own architecture, replanning and hard diagnosis. Deterministic tooling owns task state, dependencies, worktrees, checkpoints and integration.

That keeps the parent's token diet small enough to orchestrate for days instead of drowning in source, logs and worker history.

A task fails. A reviewer catches another bug. A dependency was wrong. One model gets stuck. The plan changes. The parent gets compacted overnight. **The run keeps moving.**

## Memory lives outside the chat

Plans, briefs, attempts, reports, reviews, checkpoints, phase gates and Git carry the durable truth. Chat is a control surface over that state, not its only copy.

The parent can be compacted, restarted, or replaced by a fresh session and reconcile from recorded state. **Small active context, large durable memory.**

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

- **Goal → reviewed plan → executable work**, or execution of an existing plan.
- **Parallel Grunts** with isolated worktrees and fresh review/fix loops.
- **Analyst escalation/replanning**, Human escalation, and independent Phase Gates.
- **Durable recovery** across crashes, compaction and parent-session replacement.
- **Mixed runtimes** and collision-safe concurrency.

T-BAG's rule: **let LLMs reason where meaning matters; remember the decision once; mechanize the stable consequence.**

## Where to look next

| Concern | Authority |
|---|---|
| Parent/orchestration behavior | `SKILL.md` |
| Operator commands | `PROMPTS.md` |
| Runtime/model configuration | `CONFIG.md` |
| Task/worktree/lifecycle/integration | `WORKSPACE.md` |
| Context composition | `CONTEXT.md` |
| Harness behavior | `HARNESS.md` + harness-specific file |
| Worker roles | `worker/` |
| Release evaluation | `EVALS.md` + `evals/` |

T-BAG is MIT licensed.
