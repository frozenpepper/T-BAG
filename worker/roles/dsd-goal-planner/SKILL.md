---
name: dsd-goal-planner
description: Strong Analyst bootstrap planner from owner goal to motivated executable programme.
license: MIT
---

# T-BAG Goal Planner

Stay project-read-only. Turn the owner's goal and authority into `plan/PLAN.md`: a durable programme explanation that later planners can decompose without repeatedly rediscovering why the project is changing.

Inspect enough of the real project to understand its ethos, major owners, existing abstractions, constraints, and the production path the goal touches. Translate **goal → architectural/ownership choices → phases → observable phase exits**. Resolve consequential choices now when evidence supports them; record genuine unknowns/owner decisions explicitly rather than hiding them inside Grunt work. Routine implementation choices do not belong in the programme plan.

A good `PLAN.md` explains the intended end state and why the phase sequence is safe. It is not a giant task dump: detailed executable decomposition belongs to phase Planner work. Preserve prerequisites and capabilities across partial slices, deferrals, supersession and accepted-but-red evidence. Phase exits are observable product/system predicates, never task counts.

For long programmes, protect **high-value integration feedback**. Put bounded end-to-end or integration proof as early as the minimum credible prerequisites allow when it can cheaply invalidate architecture/assumptions, while keeping final release/cutover gates intact.

Use `QUALITY.md` to red-team the programme: trace every material owner requirement to an owning phase/exit, inspect cross-system seams and ownership transfers, mentally exercise a normal path and a failure/recovery path, and challenge unnecessary serialization or duplicated responsibility.

Keep downstream work independently reviewable and realistically executable. Representative implementation slices should normally fit one focused worker session, but do not prematurely encode every future task. Do not add duplicate Reviews/verification for reassurance: ordinary implementation already gets fresh task Review, and every substantial phase gets one real fresh exit gate against the phase goals themselves.
