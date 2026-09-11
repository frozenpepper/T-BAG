#!/usr/bin/env python3
from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p=Path(path); text=p.read_text(encoding="utf-8")
    count=text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement target, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old,new),encoding="utf-8")


# --- dsd_task: tolerant explicit routing protocol, footer-safe followups, supersession gate ---
replace_once("scripts/dsd_task.py",
'''    first=nonempty[0] if nonempty else ""
    outcome=allowed.get(first)
    if outcome is not None:
        return outcome
''',
'''    first=nonempty[0] if nonempty else ""
    outcome=allowed.get(first)
    if outcome is None and first:
        # Still deterministic: accept only an allowed token anchored at the start of
        # the first line, optionally Markdown-bolded and followed by an explicit
        # punctuation separator. Never infer PASS/FAIL from ordinary prose.
        for token in sorted(allowed,key=len,reverse=True):
            pattern=rf"^(?:\\*\\*)?{re.escape(token)}(?:\\*\\*)?(?:\\s*(?:—|–|-|:)\\s+.+)?$"
            if re.fullmatch(pattern,first):
                outcome=allowed[token]; break
    if outcome is not None:
        return outcome
''')

replace_once("scripts/dsd_task.py",
'''    for raw in lines[starts[0]+1:]:
        stripped=raw.strip()
        if stripped.startswith("## "): break
        if not stripped: continue
        if not stripped.startswith("- ") or not stripped[2:].strip():
            raise ValueError(f"{FOLLOWUP_HEADING} must contain only concise single-line '- ...' bullets")
        items.append(stripped[2:].strip())
    if not items: raise ValueError(f"{FOLLOWUP_HEADING} is present but contains no obligations")
    return items
''',
'''    for raw in lines[starts[0]+1:]:
        stripped=raw.strip()
        if stripped.startswith("## "): break
        if not stripped: continue
        # Harness metadata and common trailing report prose are outside the dedicated
        # obligations section even when a worker forgot to add another Markdown H2.
        if stripped.startswith(("Attempt:","Baseline:","Next technical step:")): break
        if stripped in {"None","None.","- None","- None."} and not items: return []
        if stripped.startswith("- ") and stripped[2:].strip():
            items.append(stripped[2:].strip()); continue
        # Markdown-wrapped bullet continuations are structural when indented.
        if items and (raw.startswith(" ") or raw.startswith("\\t")):
            items[-1]+=" "+stripped; continue
        raise ValueError(f"{FOLLOWUP_HEADING} must contain only '- ...' bullets; indent wrapped continuation lines")
    return items
''')

replace_once("scripts/dsd_task.py",
'''def _phase_task_success(run: Path, phase: str, task: dict[str, Any]) -> bool:
    if open_review_findings(task): return False
    status=str(task.get("status") or "")
    if task.get("requires_integration"): return status=="integrated"
    if status=="superseded":
        try: return dependency_satisfied(run,phase,str(task.get("task_id") or ""))
''',
'''def _phase_task_success(run: Path, phase: str, task: dict[str, Any]) -> bool:
    if open_review_findings(task): return False
    status=str(task.get("status") or "")
    # Supersession preserves the obligation through its successors. Check it before
    # requires_integration so an integrated successor can discharge an old mutable task.
    if status=="superseded":
        try: return dependency_satisfied(run,phase,str(task.get("task_id") or ""))
''')
# The old function's requires_integration line was removed with the replacement above;
# restore it immediately after the supersession branch's exception block by targeting
# the following stable return sequence.
replace_once("scripts/dsd_task.py",
'''        except ValueError: return False
    if status not in {"accepted","integrated"}: return False
''',
'''        except ValueError: return False
    if task.get("requires_integration"): return status=="integrated"
    if status not in {"accepted","integrated"}: return False
''')

# --- run_worker: each technical worker owns a process group so lifecycle retirement
# can terminate worker-spawned MCP/child servers without touching the launcher. ---
replace_once("scripts/run_worker.py",
'''        proc=staggered_popen(cmd,interval_seconds=float(getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS)),cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT)
''',
'''        proc=staggered_popen(cmd,interval_seconds=float(getattr(args,"launch_start_interval_seconds",DEFAULT_LAUNCH_START_INTERVAL_SECONDS)),cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT,start_new_session=True)
''')
replace_once("scripts/run_worker.py",
'''                cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT,
            )
''',
'''                cwd=launch_cwd,env=env,stdout=out,stderr=err if err is not None else subprocess.STDOUT,start_new_session=True,
            )
''')

# --- dsd_attempt: lifecycle-owned worker retirement ---
replace_once("scripts/dsd_attempt.py","import re\nimport shutil\n", "import re\nimport shutil\nimport signal\n")

marker='''def command_inspect(args:argparse.Namespace)->dict[str,Any]:
'''
retire='''def command_retire(args:argparse.Namespace)->dict[str,Any]:
    """Request bounded termination of one exact live worker attempt.

    The launcher remains alive and owns terminal.json. New RC45 workers start in their
    own process group, so SIGTERM also reaches worker-spawned MCP/child processes. For
    older attempts without a dedicated group, fall back to signaling only worker_pid.
    """
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    task=dsd_task.load_task(run,phase,tid); event=resolve_event(run,phase,tid,args.event_dir)
    _attempt_record_for_event(task,event)  # exact durable binding proof
    class I: pass
    i=I(); i.run_root=run; i.phase_id=phase; i.task_id=tid; i.event_dir=event; i.details=True; i.skip_duration_reference=True
    observed=command_inspect(i)
    if observed.get("state")!="running":
        return {"task_id":tid,"event_dir":str(event),"retired":False,"state":observed.get("state"),"reason":"attempt-not-live"}
    detail_path=event/"attempt.json"
    if not detail_path.is_file(): raise ValueError("live attempt has no attempt.json; refusing raw process retirement")
    detail=json.loads(detail_path.read_text(encoding="utf-8"))
    worker_pid=detail.get("worker_pid"); launcher_pid=detail.get("launcher_pid")
    if not isinstance(worker_pid,int) or worker_pid<=0 or not pid_alive(worker_pid):
        raise ValueError("recorded worker_pid is not live; reconcile/sweep stale state instead")
    request={
        "format":"tbag-attempt-retirement-v1","requested_at":datetime.now(timezone.utc).isoformat(),
        "task_id":tid,"phase_id":phase,"event_dir":str(event),"reason":str(args.reason),
        "worker_pid":worker_pid,"launcher_pid":launcher_pid,"report_state":observed.get("report_state"),
        "elapsed_seconds":observed.get("elapsed_seconds"),"log_age_seconds":observed.get("log_age_seconds"),
    }
    dsd_task.write_json(event/"retirement-request.json",request)
    mode="worker-pid"
    try:
        pgid=os.getpgid(worker_pid)
    except OSError:
        pgid=None
    if pgid==worker_pid:
        os.killpg(worker_pid,signal.SIGTERM); mode="worker-process-group"
    else:
        os.kill(worker_pid,signal.SIGTERM)
    return {**request,"retired":True,"signal":"SIGTERM","mode":mode}


'''
replace_once("scripts/dsd_attempt.py",marker,retire+marker)

replace_once("scripts/dsd_attempt.py",
'''    for name in ("inspect","follow"):
        p=sub.add_parser(name); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True); p.add_argument("--event-dir",type=Path)
        if name=="inspect": p.add_argument("--details",action="store_true")
        if name=="follow":
            p.add_argument("--interval",type=float,default=15.0); p.add_argument("--timeout",type=float)
''',
'''    for name in ("inspect","follow","retire"):
        p=sub.add_parser(name); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True); p.add_argument("--event-dir",type=Path)
        if name=="inspect": p.add_argument("--details",action="store_true")
        if name=="follow":
            p.add_argument("--interval",type=float,default=15.0); p.add_argument("--timeout",type=float)
        if name=="retire": p.add_argument("--reason",required=True)
''')
replace_once("scripts/dsd_attempt.py",
'''        out=command_launch(args) if args.command=="launch" else command_gate(args) if args.command=="gate" else command_inspect(args) if args.command=="inspect" else command_follow(args)
''',
'''        out=command_launch(args) if args.command=="launch" else command_gate(args) if args.command=="gate" else command_inspect(args) if args.command=="inspect" else command_retire(args) if args.command=="retire" else command_follow(args)
''')

# --- OpenCode adapter: per-attempt observers remain fast wakes; a low-frequency
# run heartbeat makes lost wakes recoverable and validates already_armed health. ---
replace_once("adapters/opencode/tbag.js",
'''import { tool } from "@opencode-ai/plugin"\n''',
'''import { tool } from "@opencode-ai/plugin"\nimport { readFileSync } from "node:fs"\n''')
replace_once("adapters/opencode/tbag.js",
'''const follows = new Set()
const busySessions = new Set()
''',
'''const follows = new Map()
const runHeartbeats = new Map()
let observerGeneration = 0
const HEARTBEAT_MS = Math.max(60_000, Number(process.env.TBAG_PARENT_HEARTBEAT_MS || 600_000))
const busySessions = new Set()
''')
replace_once("adapters/opencode/tbag.js",
'''function validateAttempt(root, args) {
  // Read-only inspect proves this event belongs to the exact run/phase/task tuple.
  checkedSync(attemptCli(root, args, "inspect"), "Refusing invalid T-BAG attempt target")
}
''',
'''function validateAttempt(root, args) {
  // Read-only inspect proves this event belongs to the exact run/phase/task tuple.
  const text = checkedSync(attemptCli(root, args, "inspect"), "Refusing invalid T-BAG attempt target")
  try { return JSON.parse(text) } catch (_) { return { state: "unknown" } }
}

function heartbeatKey(sessionID, runRoot) { return `${sessionID}\\u0000${runRoot}` }
function registerRunHeartbeat(sessionID, args) {
  runHeartbeats.set(heartbeatKey(sessionID, args.run_root), {
    sessionID, run_root: args.run_root, lastQueuedAt: Date.now(),
  })
}
function runIsActive(runRoot) {
  try { return JSON.parse(readFileSync(`${runRoot}/run.json`, "utf8")).status === "active" } catch (_) { return false }
}
''')
replace_once("adapters/opencode/tbag.js",
'''function armAttempt(client, sessionID, root, args, validate = true) {
  const key = followKey(sessionID, args)
  if (follows.has(key)) {
    return { armed: true, already_armed: true, task_id: args.task_id, event_dir: args.event_dir }
  }
  if (validate) validateAttempt(root, args)

  const proc = spawnObserver(root, args)
  follows.add(key)
  void (async () => {
    try {
      await proc.exited
    } catch (error) {
      await logError(client, "T-BAG attempt observer failed; waking parent to reconcile", {
        task_id: args.task_id,
        event_dir: args.event_dir,
        error: String(error?.stack || error),
      })
    } finally {
      // Delete before waking so a deadline/error wake can re-arm the same still-live
      // attempt during the resumed parent turn.
      follows.delete(key)
      queueWake(client, sessionID)
    }
  })()

  return { armed: true, already_armed: false, task_id: args.task_id, event_dir: args.event_dir }
}
''',
'''function armAttempt(client, sessionID, root, args, validate = true) {
  const key = followKey(sessionID, args)
  const observed = validate ? validateAttempt(root, args) : { state: "unknown" }
  const existing = follows.get(key)
  if (existing && !existing.done && (existing.proc?.exitCode === null || existing.proc?.exitCode === undefined)) {
    return { armed: true, already_armed: true, observer_healthy: true, observer_generation: existing.generation, task_id: args.task_id, event_dir: args.event_dir }
  }
  if (existing) follows.delete(key)
  if (observed?.state === "terminal" || observed?.state === "dead-unresolved") {
    return { armed: false, already_armed: false, observer_healthy: false, attempt_state: observed.state, task_id: args.task_id, event_dir: args.event_dir }
  }

  const proc = spawnObserver(root, args)
  const entry = { proc, done: false, generation: ++observerGeneration, armedAt: Date.now() }
  follows.set(key, entry)
  void (async () => {
    try {
      await proc.exited
    } catch (error) {
      await logError(client, "T-BAG attempt observer failed; waking parent to tick", {
        task_id: args.task_id,
        event_dir: args.event_dir,
        error: String(error?.stack || error),
      })
    } finally {
      entry.done = true
      if (follows.get(key) === entry) follows.delete(key)
      queueWake(client, sessionID)
    }
  })()

  return { armed: true, already_armed: false, observer_healthy: true, observer_generation: entry.generation, task_id: args.task_id, event_dir: args.event_dir }
}
''')
replace_once("adapters/opencode/tbag.js",
'''          "Run reconcile-run now, process only authorized lifecycle actions, refill free slots, and call tbag_follow for every live attempt before yielding again.",
          "For each new attempt: run the normal detached core dsd_attempt.py launch, immediately call tbag_follow with the exact returned run_root/phase_id/task_id/event_dir, then yield when no immediate lifecycle action remains.",
''',
'''          "Run one parent_tick.py tick now. Treat its monitoring/actions/update/project-end packet as the canonical parent turn boundary.",
          "For each new attempt: run the normal detached core dsd_attempt.py launch, immediately call tbag_follow with the exact returned tuple. A periodic transport heartbeat will request another tick even if an individual observer wake is lost.",
''')
replace_once("adapters/opencode/tbag.js",
'''    deletedSessions.add(sessionID)
    busySessions.delete(sessionID)
    pendingWakeSessions.delete(sessionID)
    wakeInflightSessions.delete(sessionID)
    return
''',
'''    deletedSessions.add(sessionID)
    busySessions.delete(sessionID)
    pendingWakeSessions.delete(sessionID)
    wakeInflightSessions.delete(sessionID)
    for (const [key, item] of runHeartbeats) if (item.sessionID === sessionID) runHeartbeats.delete(key)
    return
''')
replace_once("adapters/opencode/tbag.js",
'''const TBagPlugin = async (ctx) => ({
''',
'''const TBagPlugin = async (ctx) => {
  const heartbeatTimer = setInterval(() => {
    for (const [key, item] of runHeartbeats) {
      if (deletedSessions.has(item.sessionID) || !runIsActive(item.run_root)) {
        runHeartbeats.delete(key); continue
      }
      if (Date.now() - item.lastQueuedAt < HEARTBEAT_MS) continue
      item.lastQueuedAt = Date.now()
      queueWake(ctx.client, item.sessionID)
    }
  }, HEARTBEAT_MS)
  heartbeatTimer.unref?.()
  return ({
''')
# Close the extra function block at the plugin object's end.
replace_once("adapters/opencode/tbag.js",
'''})

// Exactly one plugin export.''',
'''  })
}

// Exactly one plugin export.''')
replace_once("adapters/opencode/tbag.js",
'''        const observer = armAttempt(ctx.client, sessionID, root, args)
        return JSON.stringify({ ...observer, semantics: "per-attempt wake observation only; durable T-BAG state remains authoritative" })
''',
'''        registerRunHeartbeat(sessionID, args)
        const observer = armAttempt(ctx.client, sessionID, root, args)
        return JSON.stringify({ ...observer, heartbeat_registered: true, semantics: "wake transport only; parent tick and durable T-BAG state remain authoritative" })
''')
replace_once("adapters/opencode/tbag.js",
'''    deletedSessions.delete(sessionID)
    busySessions.add(sessionID)
    try {
      armAttempt(ctx.client, sessionID, root, launch)
''',
'''    deletedSessions.delete(sessionID)
    busySessions.add(sessionID)
    registerRunHeartbeat(sessionID, launch)
    try {
      armAttempt(ctx.client, sessionID, root, launch)
''')
replace_once("adapters/opencode/tbag.js",
'''    output.context.push(`\\n## T-BAG durable continuation\\n${text}\\nOpenCode invariant: for every new attempt run the normal detached core dsd_attempt.py launch, immediately call tbag_follow with the exact returned run_root/phase_id/task_id/event_dir, and use the same tbag_follow call to re-arm every live attempt after resume/wake. Never run core follow or wait/poll in the conversational turn. Once every live attempt is observed and no immediate lifecycle action remains, end the routine turn so lifecycle wakes can resume orchestration.\\n`)
''',
'''    output.context.push(`\\n## T-BAG durable continuation\\n${text}\\nOpenCode invariant: every resume/wake/heartbeat begins with one parent_tick.py tick. For every new attempt run the normal detached core dsd_attempt.py launch and immediately tbag_follow its exact tuple. Wakes are hints; tick owns monitoring, updates and project-end state. Never poll/wait in the conversational turn.\\n`)
''')

# --- docs: one parent tick, legitimate updates, explicit project end ---
replace_once("SKILL.md",
'''## Parent loop

1. **Reconcile first.** On start/resume run `dsd_task.py reconcile-run`; when deterministic transitions are pending, `advance` may collapse them until the next launch or semantic boundary. Select/load exactly one parent harness adapter before the first worker launch. In OpenCode, refresh the project adapter once per parent start/resume and require stable `tbag_follow` before autonomous wakes. Launch READY work before housekeeping. If orientation requires technical archaeology, delegate Discovery instead of doing it as parent.
''',
'''## Parent loop

Every owner turn, resume, adapter wake and periodic heartbeat begins with exactly one **parent tick**: `parent_tick.py tick`. The tick reconciles durable truth, collapses deterministic transitions, inspects every live attempt, applies bounded lifecycle supervision, tells the parent whether to continue/launch/yield/update/intervene/finish, and emits the only routine owner-update decision. Wakes are timing hints; they are never proof that supervision is healthy.

1. **Tick first.** Select/load exactly one parent harness adapter before the first worker launch. In OpenCode, refresh the project adapter once per parent start/resume and require `tbag_follow` before autonomous wakes. Consume the tick packet instead of manually reconstructing lifecycle state. Launch READY work before housekeeping. If orientation requires technical archaeology, delegate Discovery instead of doing it as parent.
''')
replace_once("SKILL.md",
'''7. **Continue from durable truth.** Evidence gating is not semantic PASS. Interrupted work that remains inside authority retries retained state. A very long/silent call is ambiguous: consider endpoint trouble, oversized task shape, insufficient capability, or legitimate long work; split oversized work before buying strength.
8. **Gate phases; launch/arm/yield attempts.** Completed non-bootstrap phases require a fresh Phase Gate; its readable report lives in run `plan/`. Ordinary `launch` stays detached. Every live attempt must have the selected harness observer armed before the turn ends. **OpenCode:** `OPENCODE.md` is the sole protocol; use the normal detached core `launch`, immediately call `tbag_follow`, re-arm live attempts after wake/resume, then yield. File/log activity proves liveness, not semantic progress; never run core `follow`, sleep, poll, Python-wait or another watcher.
''',
'''7. **Continue from durable truth.** Evidence gating is not semantic PASS. Interrupted work that remains inside authority retries retained state. Tick supervision distinguishes active logs, silent anomalous work, and a final report whose process failed to exit. Final-report hangs are retired automatically; confirmed silent stalls are lifecycle-retired so retained state/session recovery can continue instead of burning hours.
8. **Gate phases; launch/arm/yield attempts.** Completed non-bootstrap phases require a fresh Phase Gate; its readable report lives in run `plan/`. Ordinary `launch` stays detached. Every new OpenCode attempt is immediately `tbag_follow`-armed, but observer wakes are only fast hints; the adapter heartbeat requests periodic ticks when hints are lost. Never run foreground `follow`, sleep/poll, or model-authored wait loops.
''')
replace_once("SKILL.md",
'''## Owner communication

Normal transitions are silent. Speak for an explicit status/report request, a Human decision/blocker, material safety/recovery issue, or terminal/milestone state.

Owner reports assume the user does not know task IDs or subsystem jargon. Use `owner-status`; explain **purpose before internals**, then IDs only as secondary references. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**. Phase-Gate outcomes are contextual milestones. Never sell task counts as progress.
''',
'''## Owner communication

Owner communication is part of the durable parent loop, not an improvisation. `parent_tick.py tick` emits `owner_update.due`, reasons, a token, and bounded purpose-first status. Immediate updates are due for owner decisions, worker intervention/recovery and terminal/project-end state; active work also gets a periodic heartbeat (default 30 minutes) so long jobs do not look abandoned. After actually sending that update, record `parent_tick.py ack-update --token ...`; do not acknowledge an update that was never sent.

Owner reports assume the user does not know task IDs or subsystem jargon. Explain **purpose before internals**, then IDs only as secondary references. State **Status; Decisions/blockers; Material outcomes; Running now; Backlog**. Phase-Gate outcomes are contextual milestones. Never sell task counts as progress. A `completion-candidate` is an explicit project-end boundary: finish the run only after confirming the accepted plan has no remaining obligations; otherwise replan/register the missing work.
''')

# Replace OpenCode canonical loop / forbidden supervisor wording with tick-centric transport.
replace_once("OPENCODE.md",
'''## Canonical OpenCode loop

There is exactly one parent protocol, including across adapter upgrades:

1. Run `reconcile-run` first and process authorized lifecycle actions.
2. For each new task attempt, run the normal detached core `dsd_attempt.py launch` command. Its JSON result contains `run_root`, `phase_id`, `task_id`, and `event_dir`.
3. **Immediately call `tbag_follow`** with those exact four values. Always make this call, even on a host with the newest adapter: it is idempotent and may simply return `already_armed:true` because the adapter safety hook armed the observer before Bash returned.
4. For every attempt in `reconcile-run.live_attempts` after wake, resume, compaction, or plugin reload, call the same `tbag_follow` operation with its exact recorded tuple.
5. Refill free worker slots. Before ending the routine turn, every live attempt must have an observer armed.
6. When no immediate lifecycle action remains, **end the parent turn**. Do not keep OpenCode alive with Bash, Python, `sleep`, polling, or a blocking tool.
7. Per-attempt observer completion wakes the same parent session. Return to step 1. Reconciliation is authoritative and idempotent, so duplicate/coalesced wakes are harmless.

This is the field-proven Muse sequence made canonical. The model still chooses the authorized task; the adapter only observes a concrete already-launched attempt.
''',
'''## Canonical OpenCode loop

There is exactly one parent protocol, including across adapter upgrades:

1. On every owner turn, resume, lifecycle wake or periodic heartbeat run `python3 TBag/tools/parent_tick.py tick --run-root <run>`. Do not separately reconstruct reconcile/advance/monitor/update state.
2. Process the tick packet until it reaches a launch/semantic/owner boundary. If it says `actions-ready`, execute only those authorized actions and tick again.
3. For each new attempt run normal detached `dsd_attempt.py launch`, then **immediately call `tbag_follow`** with its exact returned tuple. This also registers the run for the adapter's low-frequency heartbeat.
4. `tbag_follow already_armed:true` is only returned for an observer entry whose process still appears live; it is not semantic progress. The next tick remains authoritative.
5. If the tick says `owner_update.due`, send the bounded purpose-first update and then `parent_tick.py ack-update --token ...`.
6. If the tick says `completion-candidate`, explicitly finish after confirming accepted-plan obligations are exhausted, or replan remaining work. If it says `workers-running`, yield.
7. Do not keep the conversation alive with Bash/Python sleeps or polling. Per-attempt completion requests an early tick; a periodic transport heartbeat requests another tick even when a wake was lost.

The model still chooses semantic work. The adapter only supplies disposable wake timing; `parent_tick.py` + durable run state own orchestration truth.
''')
replace_once("OPENCODE.md",
'''- `tbag_supervise`, `wait-edge`, watcher daemons, sentinel files, run-wide supervisors, or background subagent relays;
''',
'''- model-authored polling/wait loops, sentinel-file schedulers, or background subagent relays. The built-in adapter heartbeat is allowed because it grants no task authority and only requests a deterministic parent tick;
''')
replace_once("PROMPTS.md",
'''## Resume / turn boundary

```bash
python3 <skill>/scripts/dsd_task.py reconcile-run --run-root ... [--phase-id ...] [--details]
python3 <skill>/scripts/dsd_task.py idle-check    --run-root ... [--phase-id ...]
```

After reconcile, `dsd_task.py advance --run-root ... [--phase-id ...]` collapses decided transitions until a launch/semantic boundary. It never waits or chooses a model.
''',
'''## Resume / tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Use this on every owner turn, resume, adapter wake and heartbeat. It owns reconcile + deterministic advance + live-attempt monitoring + update/project-end classification. If `owner_update.due=true`, send its bounded status then:

```bash
python3 <skill>/scripts/parent_tick.py ack-update --run-root ... --token <token>
```

A `completion-candidate` is not silent idle. Either register/replan remaining accepted-plan work or, after confirming plan exhaustion:

```bash
python3 <skill>/scripts/parent_tick.py finish --run-root ... --reason "accepted plan obligations exhausted"
```
''')
replace_once("PROMPTS.md",
'''Analyst preflights before handoff; registration repeats it:

```bash
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan  --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
```
''',
'''Analyst preflights before handoff; registration repeats it. For an amendment/replan, **record `analysis-result --outcome replan` first, then register the graph**:

```bash
python3 <skill>/scripts/dsd_task.py analysis-result --run-root ... --phase-id phase-1 --task-id PLAN-X --outcome replan --report .../report.md
python3 <skill>/scripts/dsd_task.py preflight-plan --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
python3 <skill>/scripts/dsd_task.py register-plan  --run-root ... --phase-id phase-1 --plan .../plan/task-graph.json
```
''')
replace_once("PROMPTS.md",
'''`inspect`: elapsed/report age; running means **progress unknown**. Observation is harness-owned: OpenCode uses `OPENCODE.md`; other adapters use `HARNESS.md`. Core defaults are 2h for Grunts and 6h for Analysts.
''',
'''`inspect` remains a diagnostic surface. Routine monitoring belongs to `parent_tick.py tick`: final-report/no-terminal attempts are retired after a short grace; silent anomalies use the existing role-history detector plus a confirmation window before retirement. Active logs remain progress-unknown and are not killed merely for being long.
''')

# Changelog top entry.
replace_once("CHANGELOG.md","# Changelog\n",'''# Changelog\n\n## v2.2.0 RC45 — durable parent tick and bounded supervision\n\n- Added one canonical parent tick spanning reconcile, deterministic advance, live-attempt monitoring, owner-update cadence and explicit project-end classification. Adapter wakes are now optional fast hints rather than the only way long-lived orchestration makes progress.\n- OpenCode registers active runs for a low-frequency heartbeat, validates `already_armed` observer health, and wakes the parent into the tick. No task/model/semantic authority moved into the plugin.\n- Added lifecycle-owned attempt retirement. Final-report/no-terminal workers retire automatically after a short grace; confirmed silent anomalies are terminated through the recorded worker process group so retained state/session recovery can continue and spawned MCP children do not linger.\n- Owner updates are durable/acknowledged and periodic during long active work. Quiescent active runs surface `completion-candidate` instead of silently idling; explicit finish is mechanically refused while registered work remains.\n- Relaxed only the mechanical report envelope (anchored suffixed/bold verdict tokens, footer-safe/empty follow-up obligations), fixed superseded mutable-task phase-gate readiness, and documented replan-before-register ordering.\n''')
