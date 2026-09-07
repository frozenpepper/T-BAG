---
name: preregistered-acceptance
description: Predeclare experimental or live-probe predicates so results are interpreted against criteria fixed before observation.
---

# Preregistered Acceptance

Use whenever a task has a result-sensitive gate, live probe, verifier, join/readiness condition, migration acceptance, or experiment that could be reinterpreted after the evidence is seen. Before execution, identify the literal required predicates, the real production entry point/observable when one is named, and the interpretation rule.

After observation, **freeze the meaning of those predicates**. A red required predicate cannot be laundered into PASS by declaring it “not really part of this task,” swapping in a narrower local check, changing the denominator/scope, treating skipped evidence as irrelevant, or inventing a new proxy after the fact. If the original predicate is genuinely wrong/impossible/obsolete, report the red evidence and route an explicit Analyst/Human amendment; the amended contract governs a new/revised attempt, not the already-observed one.

For reviews, compare the worker's final interpretation against the literal pre-observation contract. Treat post-hoc scope/criterion drift as a material finding even when the implementation itself looks reasonable.
