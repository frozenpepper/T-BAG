# T-BAG Behavioral Evaluation

Mechanical tests prove the control plane. Behavioral evals test what Python cannot: whether parent/worker models actually use the architecture well.

## Protocol

Use `evals/cases.jsonl` as the stable corpus. For a release candidate:

1. run every case with the skill enabled;
2. when useful, compare against the previous stable skill or no skill;
3. repeat across more than one parent model/harness when available;
4. preserve the parent transcript plus launched-task summary;
5. score every declared expected/forbidden behavior;
6. record efficiency: elapsed time, attempts, unnecessary owner questions, unnecessary parent repository work and achieved parallelism.

Do not change expected behavior after seeing a result. Revise the case first, then rerun.

The corpus focuses on behavioral contracts: planning/decomposition and authority, parent semantic abstention, deep Analyst/Reviewer reasoning, bounded quality, acceptance integrity, review/fix convergence, authority vs capability escalation, task-shape diagnosis, phase-exit gates, semantic runtime flexibility, session/recovery choices, owner reporting, plan-owned assurance, harness supervision/interactivity, parallel launch admission, and isolated OpenCode 2 worker use.

Purely deterministic mechanics belong in `tests/`, not duplicated as prose evals.

## Release expectation

Mechanics-green is not behavioral acceptance. Live runs must demonstrate that the prompts change real orchestration and defect discovery. Record live-eval results separately so historical failures remain visible without turning this file or the corpus into a changelog.
