# T-BAG Analyst Routing & Escalation

Planner, Discovery, Phase Surveyor and Recovery own semantic routing when they are asked to decide what happens to existing work. The parent records that decision; it must not infer or rewrite it.

When a lifecycle decision is required, open the report with exactly one disposition:

- **`RESUME`** — the existing brief/authority is still sufficient; return the task to its normal standing lane without changing a required predicate.
- **`REPLAN`** — ownership, decomposition, dependency or contract must change. Emit the replacement/amending task graph before finalizing the report.
- **`REPLAN+RESUME`** — the current implementation/verification work should resume **and** additional planned work is required. Use only for an implementation/verification task, and emit the graph first.
- **`ESCALATE`** — genuine Human authority is required.
- **`ESCALATE CAPABILITY`** — the task and authority are sound, but this runtime cannot responsibly finish the analysis.

A standalone findings-only Analyst task does not need to invent a lifecycle disposition. If no existing task/plan transition is being decided, report the findings plainly and let the result close as findings.

`REPLAN` is not a synonym for “I have suggestions”: it requires an actual task-graph change. `RESUME` is not permission to waive a red predicate. If a lower-tier escalation triggered the analysis, treat that report as evidence, independently validate the blocker, and escalate to the Human only when the remaining decision truly belongs there.

For Human escalation, put the decision question first: why it matters, realistic options/consequences, your recommendation when justified, what is blocked, and what can continue independently.
