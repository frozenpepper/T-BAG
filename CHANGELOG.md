# T-BAG changelog

This release package keeps only recent architectural history. Detailed pre-RC22 development logs were intentionally removed from the shipped skill because they were non-authoritative, duplicated obsolete mechanics, and materially outweighed the active documentation. Older release artifacts remain the historical record.

## v2.2.0 RC41 — collision-safe worker starts and isolated OpenCode 2 workers

- Added a machine-global worker-start admission gate. Detached T-BAG monitors can still be launched immediately and `max_workers` remains true execution concurrency; only the instant each underlying worker CLI process starts is spaced (3 seconds by default) to avoid shared CLI/SQLite bootstrap collisions. The interval is cold run configuration, applies across projects/runs, respects both the previous and current launcher's requested interval, uses monotonic timing so wall-clock corrections cannot create pathological sleeps, and treats post-reboot monotonic state as stale rather than waiting indefinitely. Admission timing is made durable before spawn, so a later cache-metadata write failure cannot turn an already-running worker into an unsupervised launcher-error orphan.
- Added `opencode2` as a first-class **worker** driver without claiming OpenCode 2 parent-harness compatibility. V2 workers use `opencode2 --standalone run --format json`, an isolated external `OPENCODE_DB`, exact JSON-event session capture, `--session` continuation, provider/model selection, and model-specific `--variant` mapping for explicitly configured effort.
- Kept stable OpenCode and OpenCode 2 state separate. The V2 beta normally uses a shared background service/database and has breaking plugin/server APIs; T-BAG therefore avoids the shared service for workers and leaves the existing stable OpenCode parent adapter untouched until a separate V2 parent integration is actually proven.
- Added focused regression and behavioral coverage for cross-run interval arbitration, stale monotonic state, isolated V2 DB/server use, JSON session identity, V2 continuation/variant command construction, the requirement that startup staggering never serialize the workers' actual execution, and post-spawn gate-metadata failure without worker orphaning.

## v2.2.0 RC40 — durable Review follow-ups and stale-frontier triage

- Closed the gap where a fresh Reviewer could correctly PASS its frozen task while burying a separate material obligation as “planner-owned”/future work with no durable route. Reviewers now preserve only concrete current-plan/phase obligations under exact `## Follow-up obligations` bullets; suggestions/polish stay out, and Reviewers still do not author successor tasks.
- Stored those obligations inside the existing `review_history` instead of adding another result/registry artifact. An unresolved follow-up makes the reviewed source dependency non-green and creates a short phase planning barrier for **new** launches; live attempts continue. `advance` creates one read-only Planner triage immediately after Review; it can run alongside the source Fixer/landing path while other new phase launches stay paused.
- Kept semantic decomposition with Analysts. Triage may `resume` only when the current frozen plan genuinely already carries every finding; otherwise it emits replacement/amending work. The triage task is already durably bound to the exact finding IDs, so registration marks those findings triaged only after that graph is accepted without duplicating IDs in the graph. Frozen insufficient tasks are replaced through existing `supersedes`; integrated work gets an amendment. If neither plan route is valid, triage may escalate and explicit Human `accept` can cancel the bound obligations with the decision file preserved as authority; Reviewer/Planner waiver remains impossible. No brief-mutation or generic plan-version state machine was added.
- Rejected launch-time prose/`Allowed source changes` comparison as brittle semantic inference. The explicit Review finding is the single durable stale-frontier signal; readiness/phase gates then use ordinary deterministic state. Open follow-ups surface through bounded `owner-status`, and all findings plus Analyst resolution remain visible in the later phase-gate dossier.
- Added behavioral/regression coverage for the exact field failure: material “planner-owned” observations cannot evaporate, earlier READY phase tasks cannot launch before triage, finding ownership stays bound to the mechanically-created triage task rather than another plan field, and the phase gate retains the finding/resolution trail.

## v2.2.0 RC39 — semantic kernel, cold capability ladders and phase-exit gates

- Rebalanced semantic reasoning versus deterministic plumbing. Grunt and Analyst remain the only machine authority lanes; optional ordered runtime profiles are cold same-authority capability choices, surfaced only by owner direction or exact `ESCALATE CAPABILITY`. Stronger models never widen task authority. One-shot profiles preserve configured order after consumption, so escalation cannot wrap backward.
- Added first-class Claude Code technical-worker execution alongside OpenCode and Codex, including stream-JSON session capture/resume. Runtime `effort` is now durable intent: Claude uses native `--effort`, Codex uses `model_reasoning_effort`; unsupported OpenCode effort is rejected at configuration time instead of guessed. First-class adapters remain optimized mechanics, not the semantic capability boundary of the skill.
- Formalized exact first-line routing tokens for roles that own lifecycle judgments. The worker makes the semantic decision; the kernel records/routes it without sentiment inference. Verification `BLOCKED` stays red and cannot satisfy dependencies. Legacy free-form Reviewer records remain operable through explicit outcome commands.
- Added a bounded synchronous `advance` reducer for already-decided transitions only. It never waits, launches, chooses models, authors plans or diagnoses work; internal phase-gate/verification/capability transitions are kept out of the parent-facing CLI so routine orchestration has fewer switch-statement turns, not more commands to remember.
- Added serious phase-exit gating for completed non-bootstrap phases. A fresh Phase Auditor receives the accepted plan plus a compact task/outcome dossier and audits the actual integrated phase goals/cross-task seams. Gate verdicts are bound to the primary snapshot seen by the Auditor. Human-readable append-only reports are saved directly beside `plan/PLAN.md` as `PHASE-<phase>-GATE-NN.md`; BLOCKED history is preserved through corrective work and fresh re-audit.
- Added purpose-first bounded `owner-status`. It assumes the owner does not know task IDs or subsystem jargon, keeps complete backlog counts while previewing only a small meaningful set, and surfaces recent outcomes, live work, phase gates and Human decisions without dumping internal task tables.
- Strengthened task-shape handling without numerical task-size heuristics. Planner/Plan Reviewer apply a one-focused-session-fit test; unusually long/silent attempts are treated as ambiguous evidence (transport, oversized task, insufficient capability, or legitimate long work). Runtime duration baselines are model/driver aware, and guidance prefers splitting oversized work before spending stronger models.
- Kept ordinary cognitive density flat: no new authority tiers, generic owner-directive DSL, generic adapter SDK, background scheduler, polling loop or extra result artifact. The default two-model run still configures one Grunt and one Analyst; richer capability remains invisible until used.

## v2.2.0 RC38 — stable OpenCode launch/follow contract and deployment-truth cleanup

- Reverted the RC37 requirement for a newly introduced `tbag_launch` host tool. Field evidence showed a restarted OpenCode parent could still expose only the older stable `tbag_follow` tool because project plugins are copied snapshots and skill upgrades do not refresh that project copy automatically. The canonical protocol is now the exact Muse-proven sequence that works across adapter revisions: normal detached core `dsd_attempt.py launch` → immediate `tbag_follow` for that exact attempt → yield. A release may not make safe launching depend on a newly invented host tool name.
- Added a current-adapter safety auto-arm through native Bash `tool.execute.after`: after a successful recorded core launch, the adapter tries to arm the exact observer before Bash output returns to the model. The parent still performs the immediate `tbag_follow` call; it is idempotent and therefore remains compatible with older follow-only adapters and host modes where the safety hook is unavailable. Auto-arm failure is logged but never converts an already-detached worker into a failed launch.
- Fixed adapter deployment truth. `install_harness_adapter.py` now reports the installed adapter hash/match, distinguishes disk update from live-host activation, and explicitly sets `live_capability_verified=false` because it cannot inspect the current OpenCode tool registry. Harness detection likewise describes the required stable tool without claiming it is active. OpenCode startup/resume refreshes the project adapter once, while an already-visible `tbag_follow` remains sufficient to continue safely.
- Fixed a plugin-loader defect in RC37: the adapter exported the same plugin function as both a named and default export. OpenCode loads every function export, so that shape could instantiate hooks twice. RC38 exports exactly one default plugin function and adds executable coverage for the module export surface.
- Hardened wake cleanup: deleted parent sessions suppress obsolete late wakes, while successor sessions recover solely through durable `reconcile-run` state and re-arm with `tbag_follow`. Busy-turn coalescing and the final wake-race flush remain ephemeral transport only.
- Extended core launch's bounded routing result with `run_root` and `phase_id` alongside the existing `task_id`/`event_dir`. This lets the OpenCode safety hook bind to the exact recorded attempt without reparsing shell quoting or inferring path structure.
- Added upgrade/idempotence regressions for an old follow-only project adapter and executable plugin-runtime coverage for launch auto-arm + immediate idempotent follow, follow-only compatibility, auto-arm failure recovery, wake chaining, session deletion, direct-launch legality and direct-follow rejection.
- Kept the simplification boundary from RC36/37: no supervisor, persistent wake queue, run-wide waiter, scheduler, secret store, hardware-task DSL, `settle`, or semantic authority in the plugin. Secrets/operator-task primitives remain separate design candidates rather than being smuggled into this orchestration repair.

## v2.2.0 RC37 — canonical OpenCode launch/arm/yield orchestration

- Canonized the successful OpenCode field mechanics behind one enforced parent path. New attempts use project-local `tbag_launch`, which invokes the existing detached core launch and arms that exact per-attempt observer before returning; `tbag_follow` is now only the re-arm primitive for attempts already live after resume, plugin reload, observer deadline, or the rare partial launch/arm failure. Direct parent Bash `dsd_attempt.py launch` / `follow` is rejected, removing both the unarmed-worker race and the foreground-wait/UI-lock failure mode.
- Hardened wake transport without creating a supervisor: observer targets are validated before re-arm; a successful launch whose observer cannot start preserves its `event_dir` and returns the exact `tbag_follow` recovery move; observer-process failure wakes the parent to reconcile; core role-aware deadlines remain 2h Grunt / 6h Analyst instead of the old OpenCode-wide 6h override.
- Close the busy-turn wake race with OpenCode's native `session.status` / `session.idle` events. Completions coalesce into one disposable in-memory wake bit while the parent is busy and flush when the host becomes idle; a terminal session error also releases the busy transport state. If another observer finishes during the generated wake turn, releasing the in-flight wake performs one final non-blocking flush so the second terminal cannot remain stranded behind an already-consumed idle event. Durable T-BAG state remains authoritative, so plugin/server restart or a lost poke is recovered by the next `reconcile-run`. No notification database, idle poller, run-wide watcher, model switcher, or second scheduler was added.
- Moved the OpenCode protocol to one authoritative `OPENCODE.md` and kept only its load-bearing invariant in `SKILL.md`; `HARNESS.md`, `PROMPTS.md`, worker-CLI notes, adapter installation output, compaction orientation, and the behavioral corpus now route consistently to the same atomic-launch / re-arm / yield contract. Generic shell-launch cookbook examples are explicitly non-OpenCode parent commands.
- Adopted the remaining low-cost Muse findings that are still real against RC36: cold retries with retained task delta now warn when their frozen baseline predates current primary, and `register-direct` / `analysis-result` help exposes its role asymmetries before authoring. The reported replacement-deadlock shape was already a mechanical preflight error in RC36, so no duplicate planner doctrine or new state was added.
- Kept the simplification boundary: consume existing bounded JSON/routing surfaces directly instead of adding a human renderer; keep `register-plan.ready_registered` and bounded `gate.report_surface` rather than add `settle`/auto-gating/auto-launch; leave credentials/operator hardware schemas out until they have a generic, security-reviewed contract. Fresh Review, red-evidence preservation, Analyst/Human escalation, integrated-primary visibility and derived-view self-healing are unchanged.

## v2.2.0 RC36 — self-healing derived views and cheaper control closure

- Self-heal shared analysis-view runtime drift: reconcile `index.json` with actual `vNNNN` directories, preserve referenced orphan views as stale, reclaim unreferenced derived orphans, prune stale Git worktree administration, and verify new task/analysis worktrees physically materialize before reporting success.
- Standalone Analyst control tasks approved with `analysis-result --outcome replan` now close as the existing non-integration terminal state `accepted` only after their graph registers successfully. `register-plan` also returns `ready_registered`, removing the routine follow-up `ready` query without mixing worker launch into plan registration.
- Added an explicit Human `resolve-escalation --route accept` for project-changing implementation tasks only after a recorded fresh Reviewer FAIL/ESCALATE. The Reviewer outcome remains red; the frozen Human decision authorizes that exact Reviewer checkpoint through integration instead of falsifying a PASS.
- Confirmed `Required worktree fixtures` supports ignored directory trees such as `node_modules`; kept fixture provisioning explicit rather than adding NODE_PATH/symlink conventions. Attempt records now surface the project-view primary HEAD / analysis-view generation for stale-view diagnosis.
- Compressed the single shared `QUALITY.md` method instead of creating full/slim context profiles. Ordinary workers still receive the same technical standard and only task-selected skill bodies; planning/review roles alone receive the metadata skill catalog.
- Deliberately did not add semantic import/dependency preflight, a generated-output manifest, `await`/auto-gating observers, auto-launching plan registration, reviewer-optional content heuristics, a spend database, or a generic doctor daemon. RC35 already makes integrated non-tracked state globally visible; observation remains non-mutating; fresh Review stays mandatory for mutating work.

## v2.2.0 RC35 — coherent integrated-primary views and legal recovery routing

- Replaced dependency-specific non-tracked overlays with one coherent integrated-primary snapshot. Every new mutating worktree and shared Analyst view now sees `HEAD` + current tracked primary movement + every still-non-tracked path established by any integrated T-BAG task across the run/phases; unrelated ambient untracked files remain excluded. Dependency edges govern readiness, not physical visibility of already-integrated project state.
- Shared analysis views also verify the current integrated non-tracked path set/content before reuse, and every successful `integrated` transition invalidates the reusable view even when the accepted bytes were already present.
- Isolated cleanup now retires `workspace.json`/task workspace binding as well as Git branches/DB state. Legacy stale bindings whose worktree and branches are already gone can rebuild cleanly; surviving branches still fail closed as potentially recoverable work.
- A frozen `carry_from` apply conflict now writes structured evidence and moves the successor itself to `needs-analysis` before workspace setup rolls back, eliminating the prior impossible instruction to launch an Analyst while the task remained `planned`.
- Analyst graph preflight exempts only the exact live read-only Analyst attempt authoring a replacement graph from blocking its own supersession/carry check; every other live/unresolved attempt remains a blocker.
- Added explicit `analysis-result --outcome replan-resume` for the bounded case where one Analyst report both registers additional graph work and returns the current implementation/verification task to its prior lane.
- Worker launch captures host session identity into live `attempt.json` as soon as OpenCode/Codex exposes it; resume lookup reads that evidence before `terminal.json`, avoiding private-DB archaeology after a killed worker. Terminal-time discovery remains fallback.
- Deliberately did not make integration commit owner repositories, add project-specific build/typecheck gates, or infer semantic stall/progress. Primary working state remains the integration line; builds remain worker/reviewer evidence.

## v2.2.0 RC34 — integration materialization and progress observability

- Added replacement-delta continuity preflight: if a superseded implementation retains (or may retain) unintegrated work, an Analyst graph must choose one successor with `carry_from` or explicitly list the predecessor in graph-level `rederive_from_primary`. A null/omitted carry decision can no longer silently cut a clean successor and strand hours of preserved work; intentional re-derivation remains legal and the predecessor workspace stays protected until succession is durable.
- Independently hardened dependent baselines for accepted additions hidden by `.gitignore`: integration records every reviewed non-tracked path regardless of ignore rules, declared dependents inherit it even after producer cleanup, and T-BAG force-records that provenance-owned overlay in the dependent task's internal baseline so later checkpoints/reviews cannot lose it again. Ambient ignored files remain excluded. This is a separate defensive fix; the corrected P34 incident was ultimately a missing `carry_from`, not a half-integrated prerequisite.
- Integration now reverse-checks the accepted patch immediately after apply before asserting `integrated`. If Git cannot prove the complete reviewed delta is materially present, T-BAG records an `integration-materialization-mismatch`, preserves Reviewer acceptance, invalidates stale analysis views, and routes the exceptional primary state for diagnosis instead of reporting success.
- `inspect` now reports attempt elapsed time and report age, labels a live attempt as `running-progress-unknown`, and—only on explicit inspection—compares long-running Grunt work with completed same-role durations. A fresh log plus a stale report far outside the observed band surfaces `consider-intervention`; it never auto-kills, gates, or changes lifecycle state. Background `follow` deliberately skips the historical scan.
- Quiet per-attempt observation now defaults to a 2-hour Grunt deadline and 6-hour Analyst deadline, reducing the maximum blind interval without adding a run-wide supervisor or ticker. Worker guidance tells specialists to prove/report an inconsistent prerequisite baseline rather than repairing unrelated code.
- Clarified interruption/session continuity: safe `sweep-stale` retries may use `--resume-last` directly; genuinely unsafe residue still requires Recovery, after which `analysis-result --outcome resume` can hand control back to the prior base-role session when its identity survives.
- Deliberately did not add project-specific build/typecheck hooks, automatic kill heuristics, or blanket capture of ignored files. Build consistency remains task/reviewer evidence; ignored content becomes dependency authority only after it appears in a reviewed integrated delta.

## v2.2.0 RC33 — scoped reclamation and field-hardening

- Added guarded `purge-run`: deletion target comes only from `run.json`, a run/project/id ownership marker is required, actual purge requires a completed/cleanup-safe run, `--dry-run` reports blockers without mutation, Git worktrees are reclaimed through existing cleanup, and durable `PROJECT/TBag` state is never deleted. Canonical legacy runtime paths may receive the marker through idempotent `init-run`; arbitrary legacy custom runtime roots are never auto-claimed. Hot docs explicitly identify `~/.cache/t-bag` as a multi-project shared root and prohibit raw deletion of it or sibling run/project stores.
- Fixed Human decision snapshot collisions by choosing the next free sequence number instead of assuming parent-written files never occupy `authority/decisions`; that directory is now documented as tool-owned.
- A cross-driver Analyst override without an explicit model now fails before worker launch instead of combining the new driver with the configured runtime's model name.
- `reconcile-run` emits a loud scheduler warning when useful launch actions exist with zero live workers.
- Kept RC32's existing strict allowlist/`/**` parsing and launch-time ignored-fixture provisioning. Added guidance that fixture presence is not build freshness: rebuild derived ignored artifacts in the isolated verification workspace, use baseline-relative verification predicates, serialize sibling tasks expected to touch the same integration surface, and regenerate derived outputs after primary movement instead of hand-merging them.
- Deliberately did not add generator-output registries, lockfile ignores, task-ID naming heuristics, automatic primary builds, or a second `unmerged-report`; `purge-run --dry-run` is the scoped cleanup-safety surface.

## v2.2.0 RC32 — contract plumbing and parent-context austerity

- Mechanical path sections now reject decorated prose bullets before registration instead of silently converting them into useless literal prefixes. `Allowed source changes` is explicitly an exceptional authority boundary, not a generated-output inventory.
- `gate` now returns the bounded report decision surface plus first evidence error/warning, eliminating the routine `gate -> report_surface` round trip while still making no semantic PASS/FAIL inference.
- Collapsed the common fresh-Reviewer PASS landing path: the parent explicitly selects PASS by supplying the current gated Reviewer report to `integrate --review-pass-report`; T-BAG then records PASS -> accept -> integrate mechanically in the same control call. Reviewer semantic authority is unchanged.
- Routine parent-facing output is smaller: default `reconcile-run`, `idle-check`, `launch`, `inspect`, and successful `integrate` return routing/liveness facts rather than repeated policy/provenance dumps; verbose status is explicit with `--details` where supported. Parent-facing control CLIs emit JSON-shaped errors to avoid traceback/context pollution from success-only parsers.
- Clean isolated workspaces refresh to current primary before a cold base-role retry when primary moved; any real task delta prevents automatic refresh. Each attempt/scope baseline records the resolved Git checkpoint OID for revision provenance rather than asking workers to restate engine versions.
- Per-attempt observers remain quiet but default to a six-hour deadline; Claude guidance requires `follow` as its own native background tool call rather than shell-chaining it onto launch.
- Deliberately did not add a generated-output registry, filename ignore list, parent-certified interruption flag, standing-authority subsystem, or semantic verdict parser. Existing Project Protocol and Reviewer/Analyst boundaries remain the simpler owners.

## v2.2.0 RC31 — Recovery as uncertainty boundary; dependency untracked continuity

- Removed the universal Recovery tax for dead workers. `sweep-stale` now compares the retained project view against that attempt's frozen checkpoint and retries the same role when residual state is mechanically admissible; only unprovable, read-only-mutating, control-tree, or out-of-authority residue routes to Recovery.
- Admissible mutation with a missing final report now stays on the same-role continuation path. A recorded session is preferred; if transport lost the session identity, the retained workspace can be finished by a fresh same-role attempt before fresh Review.
- Fixed the recurring self-generated untracked integration conflict: integrated tasks record their still-untracked reviewed outputs, and declared dependents inherit exactly those files into their baseline. Arbitrary ambient untracked files remain excluded.
- Integration conflict evidence now distinguishes divergent untracked authority candidates and records known T-BAG producers, keeping Analyst work for genuine authority choices rather than plumbing failures.

## v2.2.0 RC30 — non-bypassable succession retention

- Closed the remaining supersession-cleanup footgun: `cleanup --force` can no longer bypass carry-forward retention. A recorded successor that has neither integrated nor durably captured `carry_from` makes predecessor cleanup mechanically impossible.
- Clarified `--force` as an override for ordinary completion-state cleanup only; it never bypasses live-attempt or succession-retention safety.
- Added a regression for the exact field failure: supersede predecessor → register/name successor → forced tidy cleanup must preserve the predecessor worktree and delta.

## v2.2.0 RC29 — canonical path-prefix contracts

- Fixed the field regression where `Allowed source changes` entries written naturally as `dir/**` were treated as literal prefixes, causing evidence-gate and `carry_from` scope failures for valid nested changes.
- Canonicalized the one supported tree shorthand (`dir/**` → `dir`) in the shared contract parser so every consumer receives identical prefix semantics; no evidence-gate-specific glob patch remains to be re-overwritten.
- Reject other glob metacharacters mechanically instead of accepting ambiguous entries that would fail later. PLAN-AUTHORING now states the exact rule.
- Added regressions at parser, evidence-gate, and carry-forward boundaries.

## v2.2.0 RC28 — parent-context austerity and supersession retention

- Made routine parent orchestration bounded by routing value: `reconcile-run` omits full backlog/cleanup inventories and dependency-wait rows by default; `--details` is explicit owner/status expansion.
- Made `follow` quiet while live: one small start line, then only terminal/dead-unresolved/deadline. It no longer emits 15-second ticks or worker-log tails.
- Added multi-task evidence gating with repeated `--task-id` so objective terminal transitions can be batched without batching semantic Reviewer/Analyst judgment.
- Changed `report_surface.py` to scan locally for an explicit routing conclusion and print only a bounded section, with a small-prefix fallback. Hot/cookbook guidance now forbids raw worker artifact dumps and full-command-line `ps`; the parent is a router, not a reader.
- Hardened supersession cleanup: a superseded mutable workspace cannot be reclaimed until all recorded successors integrate or one successor durably captures the predecessor delta with `carry_from`. A successor explicitly named by an earlier manual supersession may capture that still-retained delta later, closing the field-recovery path without chmod/state surgery.

## v2.2.0 RC27 — brief parser/preflight closure

- Made mechanical Markdown contract parsing fence-aware so quoted control headings (skills, write boundaries, fixtures) cannot be mistaken for live contract sections.
- Accepted natural `- none` / `- NONE` skill bullets as empty declarations, matching the existing path-section behavior.
- Strengthened plan preflight to validate every declared role-scoped skill section against the frozen worker-rules catalogue, not only the task's initial role. Later Reviewer/Fixer launches therefore cannot discover skill-reference defects that were mechanically knowable before registration.
- Clarified that registered briefs are immutable control artifacts; repair before registration or supersede later rather than chmod/editing durable authority in place.
- Made the generic escalation failure point to the legal Analyst/reviewer semantic commands instead of leaving the parent to discover the routing verb after writing an unusable report.

## v2.2.0 RC26 — per-attempt native supervision and state-machine closure

- Deleted the default run-wide OpenCode supervisor. The only supervision primitive is now `dsd_attempt.py follow` for one concrete recorded attempt. Claude Code backgrounds that observer through native Bash so the owner gets a real task chip and completion wake; OpenCode exposes a thin `tbag_follow` plugin tool that backgrounds the same primitive and sends a short same-session lifecycle poke when it exits.
- Removed OpenCode session-idle polling, parent model/agent preservation logic, `wait-edge`, the old generic `wait`/`wait_worker.py` path, the Claude-specific re-wake helper, background-subagent recipes, and model-authored watcher protocols. Wake/display code has no semantic task authority.
- Closed stale-attempt dead ends: a mechanically swept `stale-unresolved` attempt is no longer considered perpetually unresolved and repeated sweeps no longer undo a later resume route.
- Dependencies now follow explicit `superseded_by` chains with cycle protection; superseded obligations without a successor remain unsatisfied.
- Integration first proves whether a reviewed patch is already present with `git apply --reverse --check`, so byte-identical primary/untracked collisions close mechanically. Genuine conflicts no longer invalidate an unchanged fresh Reviewer PASS; a corrected primary-tree precondition can retry the same reviewed ref, while semantic conflicts still route to analysis.
- Plan preflight now validates requested worker-skill IDs against the frozen worker-rules revision and calls out role names accidentally used as skills.
- Read-only integrity failures now point directly at mutating verification artifacts such as `__pycache__/*.pyc`, so the brief can be fixed instead of repeatedly burning Reviewer/Analyst attempts.
- `register-direct` and bootstrap-only Plan Reviewer failures now provide actionable control-plane errors instead of opaque late failures.
- Decoupled Analyst specialization from result artifact shape: a `planner` findings task can now be accepted without fabricating `task-graph.json`; a graph is mandatory only for transitions that actually consume one (`analysis-result --outcome replan` / `register-plan`). This closes legacy plans whose role label and brief intent disagree without adding a role-rewrite command.

## v2.2.0 RC25 — OpenCode plugin-native autonomous supervision

- Replaced the experimental background-subagent supervision recipe with one project-local OpenCode plugin tool, `tbag_supervise`. The parent calls it after detached launches; it returns immediately while the plugin owns the blocking `wait-edge` process and wakes the same parent session on lifecycle edges or bounded deadlines.
- OpenCode supervision no longer depends on `OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS`, foreground Task/subagent relays, or model-authored polling protocols.
- The supervision plugin waits for parent idleness, preserves the current parent agent/model explicitly, wakes through synchronous OpenCode `session.prompt`, and stops on repeated identical immediate-action loops. It never gates, reviews, mutates, launches technical work, accepts, or integrates.
- The harness installer now installs `.opencode/plugins/tbag.js` plus stable `context_checkpoint.py` and `dsd_task.py` project shims, and removes the obsolete `dsd-compaction.ts` OpenCode plugin.
- Updated OpenCode docs, idle-check supervision output, tests, and behavioral evals around the named plugin tool instead of asking the parent LLM to invent its own wake mechanism.

## v2.2.0 RC24 — dead-path and duplicate cleanup

- Removed obsolete/unreferenced compatibility and research material: old compaction installer wrapper, standalone state checker, unused OpenCode health probe, Kilo compatibility contrib scripts, unwired Command Code/Kilo worker manuals, unused adapter README/config fragments, duplicate task-plan example, and the cold 2026 research note.
- Removed the separate `COMPACTION.md`; compaction/resume orientation is now owned by `HARNESS.md` and the selected harness adapter.
- Simplified `context_checkpoint.py` to its two live responsibilities: emit reconcile-first orientation and service current SessionStart hooks. Removed unused `prepare`, `rehydrate`, `verify-resume`, pre/post-compact event compatibility, and legacy `AG_*` / `DSD_*` environment aliases.
- Removed remaining legacy orchestrator/project environment aliases; current configuration uses `TBAG_*` names only.
- Reduced `WORKSPACE.md` by deleting historical migration prose, duplicate task-plan syntax, duplicate integrated-verification policy, and repeated explanations while preserving task-local lifecycle/worktree/review/integration semantics.
- Reduced `CONTEXT.md`, `PROMPTS.md`, `WORKER-CLI.md`, README/config duplication, and retained only wired OpenCode/Codex worker transport references.
- Replaced tests that protected compatibility clutter with architecture/dead-path assertions so removed concepts do not silently return.
- Renamed test modules by capability rather than historical release number, renamed `CONFIG.example.md` to authoritative `CONFIG.md`, and pruned behavioral evals from 49 to 35 by removing cases that merely re-tested deterministic mechanics already covered in Python tests.

## v2.2.0 RC23 — architecture/compaction cleanup

- Removed the unused append-only compaction checkpoint stream; durable execution truth remains run/task-local state.
- Made all parent harnesses follow the same supervision invariant: native non-blocking wake when available, otherwise conversation-first degraded mode.
- Restored documentation ownership boundaries between harness, context, workspace and role layers.
- Removed project-shaped planning terminology from universal doctrine and trimmed role files that had begun re-copying shared `QUALITY.md` method.

## v2.2.0 RC22 — instruction architecture refactor

- Replaced accumulated duplicated policy with compositional worker context: `COMMON` + role-aware `QUALITY` + one role mandate + selected skills + brief/typed inputs.
- Turned `PROMPTS.md` into an operator command cookbook rather than a second policy manual.
- Added instruction-size/composition tests so field lessons are updated at their owning layer instead of copied throughout the skill.
- Preserved older frozen worker-rule revisions while new revisions explicitly snapshot the shared quality layer.

## v2.2.0 RC20–RC21 — field-hardening summary

- Fixed stale Reviewer launch actions, reusable review-conduit supervision traps, integration-conflict routing, report-marker false positives, failed-worktree branch cleanup, and Analyst plan self-preflight.
- Reinforced literal acceptance integrity: required red predicates cannot be weakened after observation; accepted evidence is not synonymous with a green milestone; prerequisites survive supersession/deferral until satisfied or explicitly cancelled.

## Earlier development

Earlier RCs established the current task-local architecture, detached/inspectable worker lifecycle, shared frozen Analyst project views, fresh Reviewer/Fixer loop, typed escalation, runtime cleanup, and harness-specific wake adapters. Their verbose incremental changelog is intentionally not shipped in the compact current package.
