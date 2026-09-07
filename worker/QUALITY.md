# T-BAG Technical Quality Method

Load this for roles that own a technical conclusion. The standard is **production-grade, bounded by authority**: follow the causally relevant surface until the conclusion is trustworthy; do not gold-plate unrelated systems.

## Establish the real mechanism

- Identify the production owner/entry point, invariants, observable behavior and relevant callers/consumers.
- Follow only boundaries that can change correctness: schema/API, persistence/reload, lifecycle, concurrency/retry/error/cleanup, configuration, generated/build output, provider/adapters, and material performance/resource/security effects when implicated.
- For object-oriented design and adjacent architecture, check responsibility/state ownership, dependency direction, substitutability/extension points and duplicated or parallel mechanisms. Reuse abstractions only when the responsibility truly belongs there.
- Separate observed fact, inference and unknown; prior reports are navigation/claims, not proof.

## Try to falsify the easy answer

- Test at least one credible competing explanation or failure mode when practical.
- Read what proof actually exercises. A green test can still bypass production, normalize away the defect, hit the wrong path or miss the meaningful trigger.
- Use negative/sensitivity evidence when useful; task-selected proof skills contain the specialized procedure.
- Do not weaken a frozen acceptance predicate after seeing red evidence. If the predicate itself is wrong, preserve the red result and escalate/replan.

## Before finalizing

Make one deliberate second pass over the role-relevant surface: literal acceptance, production wiring, ownership/duplication, negative/sensitivity evidence, and material regression/lifecycle/error/resource effects.

Review/Audit roles do not stop at the first defect: return the consolidated material defect set unless the premise/authority is invalid enough that further review is meaningless. If the required depth exceeds your safe capability/context, `ESCALATE` rather than lowering the standard.
