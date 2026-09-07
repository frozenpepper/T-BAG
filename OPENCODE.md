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

1. Run `reconcile-run` first and process authorized lifecycle actions.
2. For each new task attempt, run the normal detached core `dsd_attempt.py launch` command. Its JSON result contains `run_root`, `phase_id`, `task_id`, and `event_dir`.
3. **Immediately call `tbag_follow`** with those exact four values. Always make this call, even on a host with the newest adapter: it is idempotent and may simply return `already_armed:true` because the adapter safety hook armed the observer before Bash returned.
4. For every attempt in `reconcile-run.live_attempts` after wake, resume, compaction, or plugin reload, call the same `tbag_follow` operation with its exact recorded tuple.
5. Refill free worker slots. Before ending the routine turn, every live attempt must have an observer armed.
6. When no immediate lifecycle action remains, **end the parent turn**. Do not keep OpenCode alive with Bash, Python, `sleep`, polling, or a blocking tool.
7. Per-attempt observer completion wakes the same parent session. Return to step 1. Reconciliation is authoritative and idempotent, so duplicate/coalesced wakes are harmless.

This is the field-proven Muse sequence made canonical. The model still chooses the authorized task; the adapter only observes a concrete already-launched attempt.

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

The wake bit is disposable. Durable T-BAG state remains authoritative: after plugin/server restart or a lost wake submission, the next owner turn begins with `reconcile-run`, which rediscovers terminal-but-ungated attempts and reports already-live attempts that need re-arming. Session deletion suppresses obsolete wake delivery; a successor parent simply reconciles and re-arms under its own session.

The adapter never polls idleness, chooses models/tasks, launches additional work, gates evidence, accepts tasks, integrates, or persists notification state.

## Forbidden substitutes

Do **not** use:

- direct Bash/Python `dsd_attempt.py follow` from the OpenCode parent;
- `sleep`, polling, repeated reconcile loops, or a long-running Python/tool call to stay active;
- `tbag_supervise`, `wait-edge`, watcher daemons, sentinel files, run-wide supervisors, or background subagent relays;
- a model-authored scheduler or a tool call kept open merely so the parent will be awakened later.

Do not block merely because a newer optional adapter capability is absent. The stable contract is core detached launch + `tbag_follow`.

## Compaction

The project plugin injects reconcile-first orientation plus the launch → follow → yield invariant into compaction context. It creates no parallel checkpoint stream.
