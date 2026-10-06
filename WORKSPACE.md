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

- **Mutating task:** isolated worktree of the primary Git line plus pre-existing tracked primary changes. Ambient untracked files stay excluded. Reviewer/Fixer and same-task diagnosis use that worktree.
- **Standalone read-only/result role:** shared frozen **analysis view** of the same integrated line; task/attempt/report state remains separate.
- **Read-only role on a mutating task:** existing task worktree, because its unintegrated diff is the evidence.

A successful integration invalidates the current analysis generation; existing readers keep it and later readers get a fresh one. Analysis-view index/cache drift self-heals on reuse; orphan derived views are reclaimed, while referenced ones stay frozen. Primary commits/detectable tracked dirty-state changes also rotate it. Ambient untracked changes do not. If an external tool changes only an already-dirty tracked path's contents, invalidate before new readers launch.

**Ambient untracked/ignored files are not mirrored.** Other ignored inputs require `Required worktree fixtures`; the one automatic exception is npm `node_modules` proven current by tracked `package-lock.json` plus npm's matching hidden lock. One immutable run generation feeds read-only views and private CoW clones (copy fallback), never sibling rooms. Other fixtures keep frozen copies.

Before each attempt, mutable state is checkpointed; read-only work uses the frozen view baseline. Attempts record the checkpoint OID. A cold base-role retry refreshes to current primary only with **no task delta**; retained work is never silently rebased. Scope evidence answers what moved during that attempt, not whether the repository was globally clean.

## Attempts and gate

`dsd_attempt.py launch` validates lifecycle/dependencies, freezes context/baseline, and starts one detached attempt. Preparation is serialized per task; `--background-prepare` is adapter-private.

Every backend must preserve budget reservation, baseline/scope evidence, attempt/report/terminal records, resumable identity where supported, and inspection. Capture session identity in live attempt evidence as soon as the host exposes it; killed workers need not wait for `terminal.json` to remain resumable. Raw CLI wrappers are unsupported. Exit `0` is not semantic success.

`dsd_attempt.py gate` checks only objective evidence: **terminal presence**, substantive report vs launcher placeholder, read-only movement, and explicit `Allowed source changes`. A report written while the process is still live is never transport completion and is never a reason to terminate that process. Semantic routing tokens are interpreted only after terminal evidence where the role requires them.

## Review and escalation

After a mutating Implementer/Fixer gate, a **fresh Grunt Reviewer** judges the frozen brief: PASS → `review-passed`; in-scope FAIL → Fixer; ESCALATE → Analyst. Fixer resumes the Reviewer that found the defects; the next Reviewer is fresh.

A Reviewer may also discover a concrete material obligation outside that task's acceptance. It records those only under exact `## Follow-up obligations` single-line bullets. They stay in review history; the source may still PASS/land, but new phase launches pause for one read-only Planner triage. The Planner either proves the frozen plan already covers every finding (`analysis-result resume`) or emits replacement/amending work (`replan`). Finding IDs stay bound to the triage, not the graph. An insufficient unstarted brief is replaced with `supersedes`; integrated work gets a dependent amendment. Only explicit Human cancellation may close it without plan coverage.

`needs-analysis` uses fresh same-task Discovery. Recovery is only for unexplained/out-of-authority residual state, not ordinary process death. Analyst results are `resume|replan|replan-resume|escalate`. Worker escalation remains **Grunt → Analyst → Human**; Human decisions are frozen typed inputs. Human may explicitly accept a blocked implementation only after fresh Reviewer FAIL/ESCALATE, whose red record is preserved.

Three cumulative same-session no-movement failures, or one recognized deterministic nonretryable provider/session failure, abandon that conversation and cold-retry the same role. Automatic work is capped per task (default 10); cycles stop at a Human boundary. `resume|analysis` resets it; `park` is quiescent; `cancel` never satisfies dependencies.

## Integration

Project-changing tasks land with `integrate --review-pass-report <gated-review-report>`. The Reviewer checkpoint is frozen; later task movement is refused. T-BAG applies exactly that delta to the run's recorded primary branch, commits only its paths, records `delivery.json`, and verifies the integration commit is an ancestor of current primary HEAD before setting `integrated`.

Unrelated owner dirty/staged paths are preserved. Owner changes on a landing path, branch drift, apply conflicts, or incomplete materialization fail closed without consuming the reviewed checkpoint. Materialization is reverse-checked before `integrated`; reviewed additions are force-added to the delivery commit even when `.gitignore` hides them. Later workspaces inherit ordinary Git state; there is no parallel “integrated untracked” channel.

Legacy `integrated` state without commit/receipt ancestry proof is **not delivered**. If its frozen `accepted.patch` and integration paths still prove an exact safe landing, deterministic advance repairs it with `repair-delivery`; otherwise reconciliation is `delivery-broken`, launches stop, and retained workspaces stay protected. `audit-delivery` shows the blocker.

Fresh Reviewer PASS is normal task acceptance. Do **not** add generic post-integration review. Extra Verification/Audit needs a named predicate, cross-task interaction, or evidence gap. Skipped required gates stay gaps.

## Interrupted work

- dead attempt without a terminal event → `sweep-stale` compares the retained view to that attempt checkpoint; mechanically admissible state retries the same role, while unprovable/forbidden movement becomes `recovery-required`;
- missing/untouched final report, with or without mechanically admissible movement → same-role continuation on the retained workspace, resuming its session when available and otherwise retrying cold;
- substantive in-progress report → same-role continuation;
- objective integrity/scope failure → Recovery.

The retained workspace is the durable implementation state. A missing process/report does not by itself justify an Analyst.

## Orchestrator escape hatch

The lifecycle is a **default execution framework**, not authority over the parent. When a T-BAG control rule, stale state, adapter defect, or lifecycle guard is itself preventing legitimate work, the orchestrator may bypass/repair that internal mechanism and continue directly. Do not ask the Human merely for permission to override T-BAG's own process. Preserve explicit Human constraints, destructive-operation safeguards, source/delivery truth, and review evidence; after a material bypass, reconcile the durable run state when practical instead of pretending the normal path occurred.

Prefer this in order: use the ordinary lifecycle when it works → make the smallest direct repair/bypass when it does not → involve the Human only for genuine owner authority or unresolved intent.

Mechanical attempt-budget and repeated-cycle guards are deliberately **orchestrator-review boundaries**, not mandatory Human gates. Reconciliation exposes them as `review-control-block`. When the guard itself/stale T-BAG state is the problem, record the reason and reset the automatic-attempt window with `dsd_task.py override-control-block`; genuine worker/Human authority escalations are rejected by that command.

## Cleanup

Cleanup is automatic: read-only results release DB/views; integration retires worktree, fixture snapshot, branches and DB. Terminal/stale attempts drop launcher `scratch/` but keep evidence. `reconcile-run` reaps safe leftovers; completed runs purge owned runtime. Package/compile caches are shared at `PROJECT/TBag/cache`.

Supersession is **delta-aware**: release read-only/empty or durably transferred rooms; retain unique undisposed deltas. `--force` needs a reason and cannot bypass live/unresolved or undisposed-delta protection. Private fixtures retire immediately; shared generations after their last binding.

`archive-run` compacts closed runs in place, dropping launcher logs/scratch while preserving briefs, reports, gates and task state. `disk-usage` reports owned surfaces; its explicit shared-cache option inventories only. Never implicitly delete `~/.cache/t-bag`.

`authority/decisions/` belongs to `resolve-escalation`. If primary moved, reconcile hand-written authority then regenerate derived outputs; use Analyst judgment only for real authority conflicts.
