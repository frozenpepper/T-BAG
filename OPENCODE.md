# T-BAG — OpenCode Parent Adapter

Load when the premium parent runs in OpenCode. Worker transport is separate (`worker-cli/OPENCODE.md` when OpenCode is also the technical-worker CLI).

## Startup / upgrade check

Refresh the project-local adapter once when an OpenCode parent starts or resumes T-BAG:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness opencode --project-root <project>
```

Host generation detection first follows the running parent via `OPENCODE_PID`. If that beta/runner does not export the variable, T-BAG walks only the current process ancestry (maximum six known-PID hops) and stops at the first explicit OpenCode **executable identity**. Wrapper-shell arguments are never host identity, so `--harness opencode` cannot misclassify a V2 parent. This lets V2 win over a co-installed PATH V1 without a global process scan. Outside an OpenCode-owned ancestry, historical `opencode --version` behavior remains primary; `opencode2` is only the fallback when `opencode` is absent.

Parent diagnostics also obey the top-level `SKILL.md` project-local scratch boundary: T-BAG repro projects, SDK probes, smoke fixtures, reports and handoff intermediates stay under the project's `TBag/` tree, never host system temp unless the Human explicitly requested an external destination.

The installer now requires **live generation proof**, not merely matching files. It writes `.opencode/tbag-activation.json`; the actually loaded V1/V2 adapter acknowledges that exact token under `TBag/harness/`. Until the tokens match in an interactive host, installer output is `bootstrap_ready=false` with a blocking **Restart OpenCode** question. Invoke OpenCode's native `question` tool and stop; after restart/reload, rerun the installer and continue only when `bootstrap_ready=true`. V1 and V2 remain distinct transport generations.

For CI/offline/headless maintenance, pass `--headless` (or `TBAG_HEADLESS=1`). T-BAG deliberately does **not** infer headlessness from TTY state because a real OpenCode tool shell may itself be non-TTY. Headless installation reports `degraded_manual=true`, emits no unfulfillable restart question, and requires explicit parent ticks until a live host proves the token. Re-running an unchanged installer also preserves the existing activation request instead of rewriting its timestamp. The installer is bootstrap/update machinery, not a runtime-health probe.

The V1 project plugin may expose **`tbag_follow`** as a diagnostic tool, but normal autonomy does not depend on that custom tool being present. A normal active `parent_tick.py tick` or worker launch enrolls supervision; every tick also lets the adapter rediscover and re-arm missing live observers from durable attempt state. V2 uses its native setup/domain-hook adapter and `session.execution.*` lifecycle.

If `tbag_follow` is absent, do not invent a workaround or treat it as a lifecycle blocker. Ordinary Bash hooks can still be live. Tick/launch hooks plus durable state are the normal path; reload the host only when adapter hooks themselves are demonstrably stale.

## Canonical OpenCode loop

There is exactly one parent protocol, including across adapter upgrades:

1. On every owner turn, resume, lifecycle wake or periodic heartbeat run `python3 TBag/tools/parent_tick.py tick --run-root <run>`. Its default output is deliberately compact and incremental; reserve `--details` for bounded diagnosis. Do not separately reconstruct reconcile/advance/monitor/update state.
2. Process the tick packet until it reaches a launch/semantic/owner boundary. If it says `actions-ready`, execute only those authorized actions and tick again.
3. For each new attempt run normal `dsd_attempt.py launch`, then yield. The OpenCode adapter transparently backgrounds expensive workspace preparation, watches that preparation, and arms the resulting worker observer. `--background-prepare` is adapter-private and direct parent use is rejected. Multiple launch commands may share one Bash call; structured results are parsed independently.
4. Missing observer state is repaired automatically after a normal tick. `tbag_follow`, when the host exposes it, is diagnostics only and is never a required lifecycle step.
5. If the tick says `owner_question_required`, run `actions_before_question`, call `parent_tick.py wait-owner --question-id <id>`, then invoke OpenCode's native `question` tool and end the turn. While it is open, **both heartbeat lanes are unenrolled** even if detached workers continue. After applying the answer, call `resume-owner --question-id <id>` then tick; completed workers reconcile then. Otherwise render `owner_notice` with `━━ T-BAG UPDATE ━━` and acknowledge it.
6. If the tick says `completion-candidate`, explicitly finish after confirming accepted-plan obligations are exhausted, or replan remaining work. If it says `workers-running`, yield.
7. Do not keep the conversation alive with Bash/Python sleeps or polling. Observer completion is the fastest hint; independently, a **60-second deterministic completion pulse** reads durable state without prompting the parent and wakes it only when a worker attempt actually finished. A separate, slower **health heartbeat** wakes the parent for a general orchestration checkup while autonomous work/recovery remains active.

The model still chooses semantic work. The adapter only supplies disposable wake timing; `parent_tick.py` + durable run state own orchestration truth. A Human `--route analysis` opens Analyst authority only; the Analyst's later `replan` is the separate technical graph decision.

## Automatic enrollment and observer arm

The current adapter owns wake setup mechanically. Before a normal active parent `parent_tick.py tick` or `dsd_attempt.py launch` executes, the plugin extracts `--run-root` and enrolls that OpenCode session/run in supervision. After a successful structured launch, `tool.execute.after` also arms the exact recorded attempt observer before the launch output returns to the model.

Therefore:

- structured tick/launch stdout is an acceleration surface, not transport authority: keep it unfiltered for immediate auto-arm, while the deterministic durable pulse can restore heartbeat state, missing attempt observers, and launch-preparation watchers if shell presentation mangles that output;
- a recognized new launch is activity evidence and clears stale `idle-recovery`; the fast pulse also revisits stale `idle-recovery` registrations instead of parking them forever;
- the orchestrator never performs a separate heartbeat-registration ritual;
- `tbag_follow` may remain available for diagnosis, but observer repair is tick-driven and does not require it;
- headless/host modes where project hooks are unavailable degrade to manual owner-turn ticks;
- auto-arm failure cannot hide or invalidate an already detached worker because heartbeat supervision remains active;
- no semantic task authority moves into the plugin.

Direct Bash/Python `dsd_attempt.py follow` remains forbidden because it can monopolize the conversational turn. Observer repair belongs to the adapter and normal tick path, not to model-authored waiting or re-arm ceremony.

Credential/config rotation is not assumed to hot-reload inside an already-running worker. If a worker stops making progress after rotation, use lifecycle retirement plus retained-session resume/retry; never make the parent inventory sibling processes or issue raw `ps`/`kill`.

## Wake transport boundary

`tbag_follow` validates the exact recorded attempt and backgrounds the core `dsd_attempt.py follow` observer. The default 2h Grunt / 6h Analyst deadline is measured from the durable **attempt start**, not from observer arm time, so parent succession or re-arming cannot reset it. `running` means the recorded worker process exists; it never means semantic progress.

OpenCode session lifecycle events are used only as a thin transport interlock. If an observer finishes while the parent is still busy, the plugin coalesces one **in-memory wake bit** for that session and flushes it when OpenCode reports idle (or releases the busy turn on a terminal session error). A completion that races the wake-generated parent turn receives one final non-blocking flush when that turn releases.

Wake state is disposable. Per-attempt wakes are the primary completion edge; the 60-second deterministic attempt-liveness pulse recovers a lost completion wake without spending parent-model tokens, and the slower health lane recovers broader orchestration drift. `human-blocked`, `paused-by-user`, and a parked-only orchestration state suspend autonomous wake activity; `completed` and `abandoned` end it. Recording a Human escalation decision automatically reactivates `human-blocked`; an explicit pause requires explicit `set-run-status active`. A subsequent tick/worker launch re-enrolls transport automatically.

The adapter never polls idleness, chooses models/tasks, launches additional work, gates evidence, accepts tasks, integrates, or persists semantic notification state.

## Status display

The status UI is additive and read-only. Both host generations render the existing `TBag/tools/tbag_status.py` snapshot: registered-plan progress, phase gates, active Grunt/Analyst sessions, task purpose, model, process/observer health, elapsed/deadline state and attention items. Presentation never ticks, launches, retires, accepts or integrates work.

- **OpenCode 1.x:** the installer writes `.opencode/plugins/tbag-status-tui-v1.tsx` and merges `./plugins/tbag-status-tui-v1.tsx` into the local TUI config. `/tbag` opens the detail route; the sidebar carries the compact status card. The v1 companion id is `tbag.status.v1`.
- **OpenCode 2.x:** the installer writes the existing `.opencode/plugins/tbag-ui/` companion and removes T-BAG's stale v1 file/config registration when upgrading across the major-version boundary.
- **Unknown/unsupported major:** transport still installs, but presentation is deliberately skipped rather than guessing an incompatible TUI API.

### Fast troubleshooting

After a restart, open OpenCode's built-in **Plugins** dialog. On 1.x this is the quickest activation test:

- `tbag.status.v1` **missing** → the TUI file/config registration was not loaded; rerun the installer and inspect its reported `tui_config` / `opencode_version`.
- row present but **inactive** → enable/activate it in the Plugins dialog, then retry.
- row enabled+active but `/tbag` missing → command registration failed; inspect the TUI-side plugin error rather than the server adapter log.
- `/tbag` works but transport is red → diagnose `tbag_follow`/observer transport separately. Presentation health does not prove server-adapter health, and vice versa.

Observer registrations are mirrored into run-local `.transport/opencode.json` only as disposable transport diagnostics. Durable task/run files remain semantic authority. Missing observer state is a reason to re-arm the exact live attempt, not evidence that the task failed.

Repeated same-session failures are transport facts, not Analyst work. After three cumulative zero-movement failures of the currently failing session/role—or three narrowly recognized deterministic nonretryable provider/session failures such as encrypted reasoning content issued to another caller—the session is abandoned and the same role is cold-retried on the retained workspace. Unrelated attempts may interleave without resetting this count. The per-task automatic-attempt budget still bounds total burn and escalates to one Human decision when exhausted.

## Forbidden substitutes

Do **not** use:

- direct Bash/Python `dsd_attempt.py follow` from the OpenCode parent;
- `sleep`, polling, repeated reconcile loops, or a long-running Python/tool call to stay active;
- model-authored polling/wait loops, sentinel-file schedulers, or background subagent relays. The built-in adapter heartbeat is allowed because it grants no task authority and only requests a deterministic parent tick;
- a model-authored scheduler or a tool call kept open merely so the parent will be awakened later.

Do not block merely because a newer optional adapter capability is absent. On the current adapter the stable contract is parent tick + detached launch with automatic wake enrollment; `tbag_follow` is an optional re-arm path, not setup ceremony.

## Compaction

The project plugin injects tick-first orientation plus launch → yield; explicit `tbag_follow` appears only for re-arm/recovery. It creates no parallel checkpoint stream.
