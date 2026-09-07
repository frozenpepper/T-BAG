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
- `carry_from` is exceptional, explicit predecessor-delta inheritance; use only when preserving that exact unintegrated delta is intended and safe.
- A superseded implementation with retained/unknown work needs one explicit delta disposition: one successor uses `carry_from`, or graph-level `rederive_from_primary` lists the predecessor.
- Mutating dependencies must integrate before dependents execute.
- Order/combine tasks expected to touch the same hand-written or generated integration surface.
- Use only valid roles/tiers from the supplied role/catalog metadata.

## Brief

Use a descriptive heading and only the sections the task needs. Prefer this shape:

```markdown
# T01 — Plain-language objective

## Objective
...

## Context
Task-specific facts the worker cannot cheaply infer.

## Requirements
- ...

## Acceptance
- Observable predicate through the real mechanism.
- Relevant negative/regression/failure proof when knowable.

## Interaction surfaces
- Cross-component contracts this task owns, when material.

## Allowed source changes
- path/prefix

## Required worktree fixtures
NONE

## Worker skills
- skill-id
```

Mechanical sections are strict:

- `Allowed source changes` and `Required worktree fixtures`: only `- project/relative/path` bullets or `NONE` (bare or as `- NONE`). A trailing `/**` is accepted as the same directory-tree prefix (`src/**` = `src`); no other glob syntax is defined.
- `Worker skills`, `Implementer skills`, `Reviewer skills`, `Analyst skills`, `Verification skills`: only bare `- skill-id` bullets or `NONE` (bare or as `- NONE`). Put explanations elsewhere.
- `Allowed source changes` is an exceptional authority boundary, **not an output inventory**. Omit it when the writer should choose its implementation/generated surface. Entries are paths only; `NONE` means no project writes.
- Do not list ambient untracked inputs as fixtures by habit. Declare only exact ignored/runtime inputs genuinely required.

## Planning discipline

Briefs are **minimum-sufficient**. Do not copy shared doctrine, Project Protocol, full dependency reports or generic advice. Include only task-specific authority, decisions, interactions and acceptance.

Preserve obligations: partial results, supersession and accepted-but-red reports do not make prerequisites disappear. Assign every required capability/predicate to a surviving task or explicit authority decision.

Verification predicates are baseline-relative unless a clean baseline is established authority. State the pre-change baseline; never require “suite X is green” when it is already red. Rebuild ignored derived artifacts in the isolated worktree rather than assuming copied `dist` is fresh.

Before handoff, run the launcher-provided `preflight-plan` command and revise until it passes. The parent must never repair your plan mechanically for you.
