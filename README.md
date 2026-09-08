# T-BAG — The Beauty And the Grunt

I think of modern LLM skills as **semantic software**. Traditional software expects fixed buttons and APIs; a skill can take goals, constraints, model preferences, exceptions and changes of mind in natural language. The LLM understands the instruction while the skill supplies durable structure and reusable mechanics, so the same workflow is not reinvented every turn.

T-BAG applies that idea to long technical work. A lightweight parent keeps the run moving. **Analysts** plan and resolve uncertainty; **Grunts** implement, review, fix and verify bounded tasks. Git and durable run files carry the memory.

## What using it can feel like

Already have a plan?

```text
/t-bag process file plan.md.
Use Muse Spark 1.3 Contributor through the opencode-go endpoint as Grunt,
and Opus 5 Medium through the Claude CLI as Analyst.
Work through the plan autonomously and interrupt me only for decisions that genuinely need me.
```

No plan yet? Start with the problem:

```text
/t-bag The application's boot process has become painfully slow.
Investigate the real production path, create and independently review a serious plan,
then execute it. Prioritize root causes over patches and continue until the plan is complete.
```

You can steer a live run just as naturally:

```text
If some tasks are getting stuck, you may spend one Analyst call on Astra (high)
through Codex for the difficult diagnosis. Use it only where it adds value,
then continue with the normal runtime.
```

Or add deeper capability without turning every launch into model selection:

```text
Use Muse as the normal Grunt and Astra as the normal Analyst.
If an Analyst explicitly cannot finish a coherent task safely, Opus via Claude is available
for deeper analysis. Use the expensive model only when the normal Analyst is genuinely insufficient.
```

The ordinary case still has two defaults; extra capability stays cold until needed.
Model effort such as `Medium` or `high` is preserved as runtime intent when the selected first-class CLI supports it.

## Semantic choices, mechanical memory

T-BAG tries to make a careful distinction:

- **Let the LLM reason** when the answer depends on context: architecture, decomposition, unfamiliar tools, task shape or whether stronger reasoning is warranted.
- **Use deterministic tools** for stable mechanics: task identity, dependencies, worktrees, budgets, fresh review, checkpoints, evidence, integration, wake/recovery and phase history.
- **Remember a semantic decision once.** Once a plan, runtime policy or worker outcome is established, durable state carries it forward instead of asking the parent to reconstruct it after every compaction.

OpenCode, OpenCode 2, Codex and Claude have first-class worker adapters because common paths should be cheap and reliable. They are optimizations, not capability boundaries; OpenCode 2 stays worker-only while its beta parent APIs remain breaking.

Parallel workers remain parallel; only CLI start instants are staggered (3 seconds by default) to avoid bootstrap/database collisions.

## Why the parent can stay small

The parent spends far fewer tokens reading source or replaying worker history. Workers get role-relevant context; Reviewers start fresh; Fixers continue from the Reviewer that found the defect; stronger models do not gain wider authority.

**Compaction therefore matters much less.** The authoritative history lives outside chat: plan, tasks, attempts, reports, reviews, runtime policy, checkpoints, phase gates and Git. A compacted—or replacement—parent can reconcile and continue instead of reconstructing the project from memory.

## The loop

```text
Goal or accepted plan
        ↓
Analyst planning/decomposition when needed
        ↓
parallel dependency-ready Grunt work
        ↓
Implementer → fresh Reviewer → Fixer → fresh Review until PASS
        ↓
reviewed integration
        ↓
fresh Phase Gate against the actual phase goal
        ↓
next phase / remaining work

Grunt ESCALATE → Analyst → Human
ESCALATE CAPABILITY → stronger configured runtime in the same authority lane
```

Phase-gate reviews live beside the run plan as `plan/PHASE-<phase>-GATE-01.md`, `...-02.md`, ... so progression is easy to inspect.

## Where to look next

| Concern | Authority |
|---|---|
| Parent/orchestration behavior | `SKILL.md` |
| Operator commands | `PROMPTS.md` |
| Runtime/model configuration | `CONFIG.md` |
| Task/worktree/lifecycle/integration mechanics | `WORKSPACE.md` |
| Context composition | `CONTEXT.md` |
| Harness wake/resume behavior | `HARNESS.md` + harness-specific file |
| Worker roles and technical method | `worker/` |
| Release/behavioral evaluation | `EVALS.md` + `evals/` |

T-BAG is MIT licensed. Historical helper names retain `dsd_*` / `dsd-*` prefixes in v2.2 to avoid migration churn; they do not imply a model/provider dependency.
