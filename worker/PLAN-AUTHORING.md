# T-BAG Task Plan Authoring

Load only when emitting `plan/task-graph.json` and `plan/tasks/*.md`. This file is the **mechanical contract**; planning quality lives in `QUALITY.md` and the selected Analyst role.

## Graph

```json
{
  "format": "dsd-task-plan-v2.1",
  "rederive_from_primary": [],
  "tasks": [{
    "task_id": "T01",
    "kind": "implementation",
    "role": "implementer",
    "tier": "grunt",
    "brief": "tasks/T01.md",
    "dependencies": [],
    "requires_integration": true,
    "supersedes": [],
    "carry_from": null
  }]
}
```

Rules:

- IDs are unique, filesystem-safe and case-insensitively distinct.
- `brief` is relative to the graph directory.
- dependencies name graph/existing tasks and are acyclic.
- `supersedes` replaces unfinished semantic work; it does not imply filesystem inheritance.
- `carry_from` explicitly preserves one predecessor's unintegrated delta. A superseded implementation with retained/unknown work needs exactly one disposition: one `carry_from` successor or graph-level `rederive_from_primary`.
- Mutating dependencies must integrate before dependents execute.
- Order/combine tasks that share one hand-written/generated integration surface. Use only supplied roles/tiers.
- A mechanically assigned Review-follow-up triage is already bound to its exact finding IDs in durable task state. Do not repeat finding IDs in the graph; successful registration is the mechanical point at which that triage becomes durable.

## Brief

Use only the sections the task needs. Prefer:

```markdown
# T01 — Plain-language objective

## Objective
...

## Context
Task-specific facts not cheap to infer.

## Requirements
- ...

## Acceptance
- Observable real-mechanism predicate.
- Relevant negative/regression proof when knowable.

## Interaction surfaces
- Material cross-component contracts owned here.

## Allowed source changes
- path/prefix

## Required worktree fixtures
NONE

## Worker skills
- skill-id
```

Mechanical sections are strict:

- `Allowed source changes` / `Required worktree fixtures`: only `- project/relative/path` or `NONE`. `src/**` means the same directory-tree prefix as `src`; no other glob syntax.
- Skill sections accept only bare `- skill-id` bullets or `NONE`; explanations go elsewhere.
- `Allowed source changes` is an exceptional authority boundary, **not an output inventory**. Omit it when the worker should choose the surface; `NONE` means no project writes.
- Fixtures name only genuinely required ignored/runtime inputs, never ambient untracked files by habit.

## Planning discipline

Briefs are **minimum-sufficient**: task-specific authority, decisions, interactions and acceptance; no copied doctrine or full dependency reports.

Apply a **one focused worker-session fit** test: one coherent responsibility, production path and proof. Split independent acceptance/ownership clusters; keep genuinely atomic cross-cutting work whole. No file/token/time quotas.

Preserve obligations: partial results, supersession and accepted-but-red reports do not make prerequisites disappear. Assign every required capability/predicate to a surviving task or explicit authority decision.

Verification is baseline-relative unless clean baseline is authority. Never require “suite X is green” when already red; rebuild ignored derived artifacts in the worktree.

Before handoff, run the launcher-provided `preflight-plan` command and revise until it passes. The parent must never repair your plan mechanically for you.
