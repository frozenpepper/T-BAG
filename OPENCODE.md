# T-BAG — OpenCode Parent Adapter

Load when the premium parent runs in OpenCode. Worker transport is separate (`worker-cli/OPENCODE.md` when OpenCode is also the technical-worker CLI).

## Startup / upgrade check

Refresh the project-local adapter once when an OpenCode parent starts or resumes T-BAG:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness opencode --project-root <project>
```

The installer detects the local host generation with `opencode --version` and installs the matching **presentation companion** while keeping the stable `tbag.js` transport adapter unchanged. OpenCode 1.x receives the v1 `@opencode-ai/plugin/tui` companion plus an explicit entry merged into `.opencode/tui.json` or existing `tui.jsonc`; OpenCode 2.x receives the separate `tbag-ui/` companion. T-BAG does not add `solid-js`, `@opentui/solid`, or OpenCode plugin packages to the project: the host owns those runtime dependencies.

The installer proves the **file on disk**, not the live OpenCode tool registry; it additionally reports the project TUI config it changed. Restart/reload OpenCode after adapter or companion changes. `live_capability_verified=false` is intentional until the running host proves activation.

The project plugin may expose **`tbag_follow`** as a diagnostic tool, but normal autonomy does not depend on that custom tool being present. The first normal `parent_tick.py tick` enrolls heartbeat supervision; every tick also lets the adapter rediscover and re-arm missing live observers from durable attempt state.

If `tbag_follow` is absent, do not invent a workaround or treat it as a lifecycle blocker. Ordinary Bash hooks can still be live. Tick/launch hooks plus durable state are the normal path; reload the host only when adapter hooks themselves are demonstrably stale.

## Canonical OpenCode loop

There is exactly one parent protocol, including across adapter upgrades:

1. On every owner turn, resume, lifecycle wake or periodic heartbeat run `python3 TBag/tools/parent_tick.py tick --run-root <run>`. Do not separately reconstruct reconcile/advance/monitor/update state.
2. Process the tick packet until it reaches a launch/semantic/owner boundary. If it says `actions-ready`, execute only those authorized actions and tick again.
3. For each new attempt run normal `dsd_attempt.py launch`, then yield. The OpenCode adapter transparently backgrounds expensive workspace preparation, watches that preparation, and arms the resulting worker observer. Multiple launch commands may share one Bash call; structured results are parsed independently.
4. Missing observer state is repaired automatically after a normal tick. `tbag_follow`, when the host exposes it, is diagnostics only and is never a required lifecycle step.
5. If the tick says `owner_update.due`, send the bounded purpose-first update and then `parent_tick.py ack-update --token ...`.
6. If the tick says `completion-candidate`, explicitly finish after confirming accepted-plan obligations are exhausted, or replan remaining work. If it says `workers-running`, yield.
7. Do not keep the conversation alive with Bash/Python sleeps or polling. Per-attempt completion requests an early tick; a periodic transport heartbeat requests another tick even when a wake was lost.

The model still chooses semantic work. The adapter only supplies disposable wake timing; `parent_tick.py` + durable run state own orchestration truth. A Human `--route analysis` opens Analyst authority only; the Analyst's later `replan` is the separate technical graph decision.

## Automatic enrollment and observer arm

The current adapter owns wake setup mechanically. Before a normal parent `parent_tick.py tick` or `dsd_attempt.py launch` executes, the plugin extracts `--run-root` and enrolls that OpenCode session/run in the low-frequency heartbeat. After a successful structured launch, `tool.execute.after` also arms the exact recorded attempt observer before the launch output returns to the model.

Therefore:

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

Wake state is disposable. Per-attempt wakes are only fast hints; the run heartbeat requests another parent tick when one is lost. The tick re-derives live/terminal/action state from durable T-BAG files. Session deletion suppresses obsolete delivery; a successor session's first normal parent tick enrolls its own heartbeat automatically.

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

Repeated same-session instant deaths with a launcher-placeholder report and zero project movement are mechanically routed to `recovery-required` after three consecutive failures. That poisoned session is then abandoned and the existing `launch-recovery` action commissions an Analyst. Human authority is not consumed merely because a worker session became unusable.

## Forbidden substitutes

Do **not** use:

- direct Bash/Python `dsd_attempt.py follow` from the OpenCode parent;
- `sleep`, polling, repeated reconcile loops, or a long-running Python/tool call to stay active;
- model-authored polling/wait loops, sentinel-file schedulers, or background subagent relays. The built-in adapter heartbeat is allowed because it grants no task authority and only requests a deterministic parent tick;
- a model-authored scheduler or a tool call kept open merely so the parent will be awakened later.

Do not block merely because a newer optional adapter capability is absent. On the current adapter the stable contract is parent tick + detached launch with automatic wake enrollment; `tbag_follow` is an optional re-arm path, not setup ceremony.

## Compaction

The project plugin injects tick-first orientation plus launch → yield; explicit `tbag_follow` appears only for re-arm/recovery. It creates no parallel checkpoint stream.
