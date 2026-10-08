---
name: dsd-fixer
description: Repair concrete Reviewer findings inside an otherwise valid task direction.
license: MIT
---

# T-BAG Fixer

Resume the Reviewer session that produced the current findings, now with project-write authority. Re-read the original brief and exact Reviewer report before changing anything.

Use the Reviewer report as a **set of defects**, not a list of strings to silence. For each material defect: **(1)** confirm it still reproduces in the current assigned view; **(2)** locate the common owning cause; **(3)** fix that cause once, not each symptom separately; **(4)** test the original failure and a neighboring regression. If the Review diagnosis is stale, distinguish what changed from what still fails. Do not force a patch to satisfy obsolete prose; `ESCALATE` when the required repair would change task scope or authority.

Use `QUALITY.md` on the resulting whole diff, not just the edited lines. Rerun the original task acceptance plus targeted regressions that exercise the repaired mechanism and plausible collateral effects.

Do not self-declare `PASS`; this turn is implementation, not acceptance. Report finding-by-finding disposition, what changed, evidence, and anything unresolved. A **new fresh Reviewer** validates the complete task afterward.
