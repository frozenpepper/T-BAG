# T-BAG context architecture

Cold reference for keeping parent/orchestrator memory distinct from worker execution context.

## Two project context planes

### Orchestrator / project notes

Rich parent-only memory may contain owner preferences/explanations, historical corrections, rejected approaches, programme risks, handover history, communication constraints, machine quirks and unresolved authority questions. It is continuity memory, not a private technical-review queue: the parent must not use rich notes to silently second-guess prescribed worker/reviewer outcomes.

**Do not attach this wholesale to workers.** A practical optional convention is `<project>/TBag/ORCHESTRATOR-NOTES.md`, seeded from `templates/orchestrator-notes.example.md`. The parent may pass it as one exact input to a planning/Discovery Analyst explicitly tasked with distilling reusable worker context; it is not worker authority and is never copied automatically into worker-rules revisions.

### Project Protocol

Optional concise worker-facing execution constitution containing recurring facts many future workers would otherwise rediscover: architectural invariants, unusual build/test commands, generated-code rules, environment traps, production-path conventions, language-agnostic constraints and stable project definitions.

It is guidance, not authority. If it conflicts with the task/governing authority, the worker reports the conflict. Analysts may propose `project-protocol/PROJECT-PROTOCOL.md` only when repeated worker benefit justifies it. Use this shared layer instead of regenerating the same toolchain/generated-output/format boilerplate in per-task dispositions. Stable Human/owner authority stays in its frozen decision file and that same exact input may be reused by multiple tasks; do not rewrite equivalent decisions per transition.

## Reusable worker skills

Reusable technical procedure belongs in focused skill directories. Each skill has `SKILL.md` and may contain cold supporting files loaded only when the skill itself needs them. Built-ins live under `worker/skills/<id>/`; project-specific skills may be supplied explicitly or proposed by Analysts under attempt-local `worker-skills/<id>/`.

Planning Analysts receive only a compact ID+description catalog. Task briefs select role-applicable skills using the mechanical headings defined in `worker/PLAN-AUTHORING.md`; unknown IDs fail loudly and skills never widen task authority.

Proof techniques are ordinary focused skills (`production-proof`, `llm-boundary`, `preregistered-acceptance`, `positive-control`, `registered-baseline`); there is no second proof-pattern system.

## Reusable-context promotion requires fresh review

Analyst-authored Project Protocol/worker-skill material is unusually high-leverage because it can affect many future sessions. Technical acceptance of the Analyst report is therefore not enough to promote that material.

Before `prepare_worker_rules.py --adopt-context-from <attempt-dir>` may adopt proposed context:

1. the source Analyst attempt is gated;
2. a **fresh Analyst Context Reviewer** bound to that source task receives a frozen independent copy of the exact proposed context plus the source brief/report/authority inputs;
3. `dsd_task.py context-review --outcome pass ...` records PASS for that exact source attempt/snapshot;
4. the source technical result is independently accepted or routed through `analysis-result resume|replan` as appropriate;
5. promotion rechecks that the live proposal still exactly matches the reviewed snapshot.

On Context Review FAIL, revise via a later Analyst attempt or abandon the proposed reusable context. Do not promote it by paraphrasing it in the parent.

Explicit owner-supplied `--project-protocol` / `--worker-skill` inputs remain explicit authority/configuration choices rather than Analyst promotion.

## Worker context composition

A new session normally gets, in order:

1. frozen run rules;
2. universal `COMMON.md`;
3. shared `QUALITY.md` for roles that own technical engineering conclusions (not Context Reviewer or Evidence Clerk);
4. one role skill;
5. `PLAN-AUTHORING.md` only for roles allowed to write task graphs;
6. metadata-only worker-skill catalog only for planning/review roles that need discovery;
7. optional Project Protocol;
8. only role-applicable task-selected skills;
9. the Analyst-authored task brief;
10. typed exact paths: governing authority, owner decisions, accepted Analyst/dependency findings, current escalation packets, current Review findings, prior worker claims, recovery evidence, and proposals under review as applicable.

Phase Planner, Phase Surveyor and Phase Auditor receive the frozen authoritative plan directly as typed governing authority. Ordinary Grunts do not receive the full plan unless their task explicitly requires it.

Creating a later rules revision inherits prior project-instruction snapshots, Project Protocol, custom skills and run-specific rules by default. A resumed CLI session stays pinned to the rules revision it originally received unless deliberately rebriefed. This is progressive disclosure: do not load parent history, all authority, every skill, or programme-wide prose into every worker.
