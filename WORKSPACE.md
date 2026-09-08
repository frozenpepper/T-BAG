# T-BAG Workspace and Lifecycle

Cold mechanical reference for task-local state, project views, attempts, review, integration and cleanup. Worker-context composition is owned by `CONTEXT.md`; task-graph syntax is owned by `worker/PLAN-AUTHORING.md`.

## Durable layout

```text
TBag/runs/<run-id>/
  run.json
  worker-rules/rNNNN/...
  phases/<phase-id>/tasks/<task-id>/
    task.json
    brief.md
    workspace.json
    attempts/<role-N>/
      launch-prompt.txt
      scope-baseline.json
      attempt.json
      worker.log
      report.md
      terminal.json
      scope-diff.json
      evidence-gate.json
```

`run.json` holds run/runtime configuration. Each `task.json` is the live control record for one task, so independent tasks do not contend on one global state file.

## Registration and readiness

`register-plan` accepts only approved Analyst-authored graphs and copies briefs verbatim, read-only, after mechanical preflight. A consumed standalone Analyst replan closes as `accepted`; the result also returns newly READY registrations. Engineering authority is in the Markdown brief; graph JSON is scheduling metadata. `register-direct` is limited to Analyst control/analysis plus bounded Human-authorized implementation with a frozen `--owner-authority` file. The parent does not author implementation scope.

Task briefs are immutable once registered; do not chmod/edit them in place. Materially changed execution meaning gets a new task ID. `supersedes` retires future/unintegrated work but does not inherit its mutations. If a superseded implementation retains work, the Analyst graph must either assign one `carry_from` successor or explicitly list the predecessor in graph-level `rederive_from_primary`; omission fails preflight. T-BAG freezes carried movement since that predecessor's baseline and applies it to current primary, failing closed on conflict/scope ambiguity. Ignored fixtures are never carried. Supersession/deferral must preserve every capability/acceptance obligation or record explicit Human cancellation.

Dependency readiness:

- non-project/analysis dependency: `accepted` or `integrated` means its result is available, **not that every predicate it measured is green**;
- project-changing dependency: must be `integrated` so the dependent workspace actually contains it.

Accepted specialist findings inform downstream work without widening authority. `BLOCKED`/`NOT READY` evidence stays red until replanned or resolved.

## Project views

Allocation follows mutation needs:

- **Mutating task:** isolated worktree of the integrated primary line: `HEAD` + tracked primary changes + still-non-tracked paths with T-BAG integration provenance. Ambient untracked files stay excluded. Reviewer/Fixer and same-task diagnosis use that worktree.
- **Standalone read-only/result role:** shared frozen **analysis view** of the same integrated line; task/attempt/report state remains separate.
- **Read-only role on a mutating task:** existing task worktree, because its unintegrated diff is the evidence.

A successful integration invalidates the current analysis generation; existing readers keep it and later readers get a fresh one. Analysis-view index/cache drift self-heals on reuse; orphan derived views are reclaimed, while referenced ones stay frozen. Primary commits/detectable tracked dirty-state changes also rotate it. Ambient untracked changes do not. If an external tool changes only an already-dirty tracked path's contents, invalidate before new readers launch.

**Ambient untracked/ignored files are not mirrored.** A reviewed non-tracked addition becomes later project state across phases; current primary bytes win. Other ignored inputs belong under `Required worktree fixtures`; files or directory trees such as `node_modules` are copied before launch and missing fixtures fail early. Presence is not freshness: rebuild derived ignored artifacts inside the isolated verification workspace. A commit is not a build; copied `dist` may be stale.

Before each attempt, mutable state is checkpointed; read-only work uses the frozen view baseline. Attempts record the checkpoint OID. A cold base-role retry refreshes to current primary only with **no task delta**; retained work is never silently rebased. Scope evidence answers what moved during that attempt, not whether the repository was globally clean.

## Attempts and gate

`dsd_attempt.py launch` checks lifecycle/dependencies, resolves the project view, freezes the baseline, renders context, launches detached, and records the attempt. Different tasks may run concurrently; one task cannot have two live attempts.

Every backend must preserve budget reservation, baseline/scope evidence, attempt/report/terminal records, resumable identity where supported, and inspection. Capture session identity in live attempt evidence as soon as the host exposes it; killed workers need not wait for `terminal.json` to remain resumable. Raw CLI wrappers are unsupported. Exit `0` is not semantic success.

`dsd_attempt.py gate` checks only objective evidence: terminal presence, substantive report vs launcher placeholder, read-only movement, and explicit `Allowed source changes`. It never parses report prose into semantic PASS/FAIL.

## Review and escalation

After a mutating Implementer/Fixer gate, a **fresh Grunt Reviewer** judges the frozen brief: PASS → `review-passed`; in-scope FAIL → Fixer; ESCALATE → Analyst. Fixer resumes the Reviewer that found the defects; the next Reviewer is fresh.

A Reviewer may also discover a concrete material obligation outside that task's acceptance. It records those only under exact `## Follow-up obligations` single-line bullets. They stay in review history; the source may still PASS/land, but new phase launches pause for one read-only Planner triage. The Planner either proves the frozen plan already covers every finding (`analysis-result resume`) or emits replacement/amending work (`replan`). Finding IDs stay bound to the triage, not the graph. An insufficient unstarted brief is replaced with `supersedes`; integrated work gets a dependent amendment. Only explicit Human cancellation may close it without plan coverage.

`needs-analysis` uses fresh same-task Discovery. Recovery is only for unexplained/out-of-authority residual state, not ordinary process death. Analyst results are `resume|replan|replan-resume|escalate`. Worker escalation remains **Grunt → Analyst → Human**; Human decisions are frozen typed inputs. Human may explicitly accept a blocked implementation only after fresh Reviewer FAIL/ESCALATE, whose red record is preserved.

## Integration

Project-changing tasks normally land with `integrate --review-pass-report <gated-review-report>`: parent supplies semantic PASS once; T-BAG records PASS → acceptance → integration mechanically. The Reviewer checkpoint is the reviewed state; later worktree movement is refused.

Normally the patch is baseline → reviewed checkpoint. If a legitimate rebase displaced an **empty** baseline, integration may use `merge-base(current primary, reviewed checkpoint)`; pre-existing primary dirty state forbids that fallback. Apply is checked before primary mutation, then reverse-checked before `integrated` is asserted so the complete reviewed patch must materially exist. Exact already-present content closes mechanically; divergent untracked candidates are preserved with known producers; genuine authority/merge conflicts route to Analyst.

Successful integration marks the task `integrated` and invalidates the current analysis view. Reviewed non-tracked additions become integrated primary state even when `.gitignore` hides them; every later view receives them. Dependencies govern readiness, not visibility of already-integrated files. Independent accepted patches may integrate in dependency-valid order when they apply cleanly.

Fresh Reviewer PASS is normal task acceptance. Do **not** add generic post-integration review. Extra Verification/Audit needs a named predicate, cross-task interaction, or evidence gap. Skipped required gates stay gaps.

## Interrupted work

- dead attempt without a terminal event → `sweep-stale` compares the retained view to that attempt checkpoint; mechanically admissible state retries the same role, while unprovable/forbidden movement becomes `recovery-required`;
- missing/untouched final report, with or without mechanically admissible movement → same-role continuation on the retained workspace, resuming its session when available and otherwise retrying cold;
- substantive in-progress report → same-role continuation;
- objective integrity/scope failure → Recovery.

The retained workspace is the durable implementation state. A missing process/report does not by itself justify an Analyst.

## Cleanup

Task DBs live outside project/run trees. Completed read-only tasks release DB/view bindings; reusable review conduits reacquire a current view per fresh attempt.

Mutating worktrees remain until integrated/retired. **A superseded mutable workspace stays until every recorded successor integrates or one durably captures it with `carry_from`; cleanup refuses earlier destruction even with `--force`.** Isolated cleanup also retires its workspace binding. `cleanup-phase` handles phase hygiene; `gc-analysis-views --drop-current-if-unused` reclaims unused shared views.

`~/.cache/t-bag` is a shared multi-project store; one run owns only its `run.json.runtime_root`. Never delete/move the shared root, `projects/`, or siblings. Reclaim a completed run with `purge-run --dry-run` then `purge-run`; durable `PROJECT/TBag` authority remains.

`authority/decisions/` is tool-owned by `resolve-escalation`; keep parent notes elsewhere. Numbering skips collisions defensively.

If primary moved, do not hand-merge generated outputs to force a stale patch. Reconcile hand-written authority, then regenerate from current sources; use Analyst judgment only for real hand-written authority conflicts.
