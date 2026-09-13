# T-BAG — The Beauty And the Grunt

I think of modern LLM skills as **semantic software**. The input is mostly normal language: what you want, what matters, what may change, what must not happen. Models supply judgment; the skill supplies durable machinery around that judgment.

T-BAG applies that idea to long technical work: **keep a serious project moving for hours or days without turning the main orchestrator into an exhausted repository archaeologist.**

## What it does

Give T-BAG a goal, a plan, or a messy problem. It turns that into reviewed work and keeps pushing until the accepted plan is exhausted:

```text
goal / plan
   ↓
Analyst plans, decomposes, diagnoses uncertainty
   ↓
parallel Grunts implement bounded tasks
   ↓
Implement → fresh Review → Fix → fresh Review until PASS
   ↓
reviewed integration → fresh Phase Gate → next work
```

If a Grunt hits a decision outside its authority, it does not improvise architecture:

```text
Grunt → Analyst → Human
```

## What using it can look like

Already have a plan:

```text
/t-bag process file plan.md.

Use Muse Spark 1.3 Contributor through opencode-go as Grunt,
and Opus 5 Medium through the Claude CLI as Analyst.

Work through the plan autonomously. Keep the normal implement → fresh review
→ fix → fresh review loop, and involve me only for real owner decisions.
```

Starting from a problem instead:

```text
/t-bag Our application's boot process has become painfully slow and nobody is
sure why. Trace the real production path, find the root causes, create and
independently review a plan, then execute it. Prefer fixing the underlying design
over stacking patches. Continue until the accepted plan is complete.
```

Steer a live run in ordinary language:

```text
If some tasks are genuinely stuck, you may spend one Analyst call on Astra (high)
through the Codex CLI. Use it only where it adds value, then continue normally.
```

Or change a rule mid-run:

```text
For the next phase, keep concurrency at 3. Do not touch the migration folder.
If review finds work outside the plan, send it to Analyst triage instead of
quietly expanding the task.
```

That natural-language steering is intentional. T-BAG records the durable consequence; you do not need to learn a miniature workflow language.

## Why the parent stays small

The parent routes work. It is deliberately **not** the main coder, main reviewer, or walking project memory.

Workers read source, run tests, write code and produce evidence. Reviewers start fresh. Fixers resume the Reviewer that found the defect. Analysts own architecture, replanning and hard diagnosis. Deterministic tooling owns task state, worktrees, supervision and integration.

That keeps the parent's active context small. A worker fails, the plan changes, the chat compacts, or you resume the next morning: **the run is reconstructed from durable state instead of from the parent's memory of the conversation.**

## See what it is doing

The same read-only run state appears in each harness:

- **OpenCode:** native TUI status + `/tbag`.
- **Claude Code:** a native status line, even while the parent is idle.
- **Codex:** `tbag_render.py status|watch` in another terminal/tmux/zellij pane.

You can see phase/progress, active Analysts and Grunts, their purpose/model/session/health, gates and warnings. The display cannot accept work or mutate the run.

## Install / update

T-BAG is a **whole skill folder**; `SKILL.md` alone is not enough. You need Python 3 and whichever parent/worker CLIs you want to use, already installed and authenticated.

For Claude Code:

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/frozenpepper/T-BAG.git ~/.claude/skills/t-bag
```

Start a fresh Claude Code session and invoke `/t-bag ...`.

Update with:

```bash
git -C ~/.claude/skills/t-bag pull --ff-only
```

Parent adapters exist for **Claude Code, OpenCode, Codex and Kilo**. Worker adapters exist for **OpenCode, OpenCode 2, Codex and Claude**. On first use T-BAG resolves Grunt/Analyst runtimes from your prompt or configuration; if it still cannot tell, it asks instead of inventing a provider/model default.

## The short version

**Let LLMs reason where meaning matters; remember the decision once; mechanize the stable consequence.**

Plans, briefs, attempts, reports, reviews, sessions, checkpoints, phase gates and Git carry the durable truth. Chat is a control surface, not the database.

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
