# T-BAG — OpenCode Parent Adapter

Load when the premium parent runs in OpenCode. Worker transport is separate (`worker-cli/OPENCODE.md` when OpenCode is also the technical-worker CLI).

## Startup / upgrade check

Refresh the project-local adapter once when an OpenCode parent starts or resumes T-BAG:

```bash
python3 <skill>/scripts/install_harness_adapter.py --harness opencode --project-root <project>
```

The installer proves the **file on disk**, not the live OpenCode tool registry. OpenCode loads project plugins from `.opencode/plugins/` at host startup. If the adapter file changed, restart/reload OpenCode when practical to activate the newest wake-race safeguards. Do not infer live capabilities from installer output.

The only required custom tool is **`tbag_follow`**. If `tbag_follow` is already visible, the canonical protocol below is valid even when the current host loaded an older follow-only T-BAG adapter. A newer T-BAG release must not require a newly invented tool name in order to launch safely.

If `tbag_follow` is absent, do not improvise a foreground waiter or scheduler. Stay conversation-first and ask for/rely on a host reload before autonomous long-running orchestration.

## Canonical OpenCode loop

There is exactly one parent protocol, including across adapter upgrades:

1. On every owner turn, resume, lifecycle wake or periodic heartbeat run `python3 TBag/tools/parent_tick.py tick --run-root <run>`. Do not separately reconstruct reconcile/advance/monitor/update state.
2. Process the tick packet until it reaches a launch/semantic/owner boundary. If it says `actions-ready`, execute only those authorized actions and tick again.
3. For each new attempt run normal detached `dsd_attempt.py launch`, then **immediately call `tbag_follow`** with its exact returned tuple. This also registers the run for the adapter's low-frequency heartbeat.
4. `tbag_follow already_armed:true` is only returned for an observer entry whose process still appears live; it is not semantic progress. The next tick remains authoritative.
5. If the tick says `owner_update.due`, send the bounded purpose-first update and then `parent_tick.py ack-update --token ...`.
6. If the tick says `completion-candidate`, explicitly finish after confirming accepted-plan obligations are exhausted, or replan remaining work. If it says `workers-running`, yield.
7. Do not keep the conversation alive with Bash/Python sleeps or polling. Per-attempt completion requests an early tick; a periodic transport heartbeat requests another tick even when a wake was lost.

The model still chooses semantic work. The adapter only supplies disposable wake timing; `parent_tick.py` + durable run state own orchestration truth.

## Safety auto-arm (new adapter, not protocol authority)

The current adapter has one defensive hook: after a successful native Bash `dsd_attempt.py launch`, OpenCode's `tool.execute.after` hook attempts to arm that exact recorded attempt **before the launch output returns to the model**. This closes the small launch→follow race when the host supports the hook.

It does not replace step 3. The parent still calls `tbag_follow` immediately. Therefore:

- older follow-only project adapters remain compatible;
- headless/host modes where tool hooks are unavailable do not change the protocol;
- auto-arm failure cannot hide or invalidate an already detached worker;
- no semantic task authority moves into the plugin.

Direct Bash/Python `dsd_attempt.py follow` remains forbidden because it can monopolize the conversational turn. The project-local `tbag_follow` tool backgrounds the same core observer and returns immediately.

## Wake transport boundary

`tbag_follow` validates the exact recorded attempt and backgrounds the core `dsd_attempt.py follow` observer. The core role-aware deadline remains authoritative: 2h for Grunts and 6h for Analysts unless explicitly overridden.

OpenCode session lifecycle events are used only as a thin transport interlock. If an observer finishes while the parent is still busy, the plugin coalesces one **in-memory wake bit** for that session and flushes it when OpenCode reports idle (or releases the busy turn on a terminal session error). A completion that races the wake-generated parent turn receives one final non-blocking flush when that turn releases.

Wake state is disposable. Per-attempt wakes are only fast hints; the run heartbeat requests another parent tick when one is lost. The tick re-derives live/terminal/action state from durable T-BAG files. Session deletion suppresses obsolete delivery; a successor session registers its own heartbeat on `tbag_follow`.

The adapter never polls idleness, chooses models/tasks, launches additional work, gates evidence, accepts tasks, integrates, or persists semantic notification state.

## Forbidden substitutes

Do **not** use:

- direct Bash/Python `dsd_attempt.py follow` from the OpenCode parent;
- `sleep`, polling, repeated reconcile loops, or a long-running Python/tool call to stay active;
- model-authored polling/wait loops, sentinel-file schedulers, or background subagent relays. The built-in adapter heartbeat is allowed because it grants no task authority and only requests a deterministic parent tick;
- a model-authored scheduler or a tool call kept open merely so the parent will be awakened later.

Do not block merely because a newer optional adapter capability is absent. The stable contract is core detached launch + `tbag_follow`.

## Compaction

The project plugin injects tick-first orientation plus launch → follow → yield. It creates no parallel checkpoint stream.
