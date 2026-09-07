# T-BAG — The Beauty And the Grunt

I think of modern LLM skills as a kind of **semantic software**. Traditional software expects buttons, arguments and APIs. A skill can take something much closer to how we actually think about work: natural language. You describe the goal, the models you want to spend, the constraints that matter, and changes of mind along the way. The skill turns that into a durable process.

T-BAG applies that idea to long technical work. A lightweight parent keeps the run moving. **Analysts** plan and resolve uncertainty; **Grunts** implement, review, fix and verify bounded tasks. Durable files and Git carry the memory.

## What using it can feel like

Already have a plan? Give it the plan and the team you want:

```text
/t-bag process file plan.md.
Use Muse Spark 1.3 Contributor through the opencode-go endpoint as Grunt.
Use Astra (high) through the Codex CLI as Analyst.
Work through the plan autonomously and only interrupt me for decisions that genuinely need me.
```

No plan yet? Start with the problem:

```text
/t-bag The application's boot process has become painfully slow.
Investigate the real production path, create a serious plan, have the plan independently reviewed, then execute it.
Use Muse Spark 1.3 Contributor as Grunt and Astra (high) via Codex as Analyst.
Prioritize root causes over patches and continue until the accepted plan is complete.
```

You can also steer a live run in ordinary language:

```text
If some tasks are getting stuck, you may spend one Analyst call on Astra (high) via the Codex CLI for the difficult diagnosis. Use it only where it adds value, then continue with the normal runtime.
```

Consequential instructions can become run/task authority rather than disappearing into chat history.

> **Worker backends in v2.2:** OpenCode and Codex are wired as technical-worker drivers. Claude Code can host the parent, but is not yet a task-worker driver. So “Opus 5 via Claude CLI as Analyst” is not a valid v2.2 worker configuration; route that Analyst through a wired backend instead.

## Why the parent can stay small

The expensive parent spends far fewer tokens reading source and replaying task history. **Context loss also matters much less.** After compaction—or even in a fresh parent session—the real history still lives outside chat: plan authority, task records, attempts, reports, review outcomes, checkpoints and Git state. The parent reconciles and continues instead of reconstructing the project from memory.

Workers get only the context for their job. Reviewers start fresh; a Fixer resumes the Reviewer that found the defects; a new Reviewer checks the task again.

## The loop

```text
Goal or accepted plan
        ↓
Analyst decomposition when needed
        ↓
parallel dependency-ready Grunt tasks
        ↓
Implementer → fresh Reviewer → Fixer → fresh Review until PASS
        ↓
reviewed integration → next READY work

Grunt ESCALATE → Analyst → Human when genuinely necessary
```

## Under the hood

The documentation follows **one rule, one home**:

| Concern | Authority |
|---|---|
| Parent/orchestration behavior | `SKILL.md` |
| Operator commands | `PROMPTS.md` |
| Runtime/model configuration | `CONFIG.md` |
| Task/worktree/lifecycle/integration mechanics | `WORKSPACE.md` |
| Context composition | `CONTEXT.md` |
| Harness wake/resume behavior | `HARNESS.md` + harness-specific file |
| Worker roles and methods | `worker/` |
| Behavioral/release evaluation | `EVALS.md` + `evals/` |

The public name is T-BAG and new runs live under `PROJECT/TBag`. Historical helper names retain `dsd_*` / `dsd-*` prefixes in v2.2 to avoid needless migration churn; they do not imply a model/provider dependency.
