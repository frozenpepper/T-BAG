import { mkdirSync, readFileSync, writeFileSync, renameSync } from "node:fs"
import {
  COMPLETION_PULSE_MS,
  HEALTH_HEARTBEAT_MS,
  backgroundLaunchCommand,
  commandArg,
  createHeartbeatRegistry,
  createWakeQueue,
  decode,
  isCoreAttemptCommand,
  isParentTickCommand, isParentControlCommand,
  startHeartbeatTimers,
  structuredObjects,
  wakeText,
} from "../tbag-opencode-transport-core.js"

// OpenCode 2 server adapter. Durable T-BAG state remains authoritative; this file
// owns only disposable wake/observer transport for the current host process.
const follows = new Map()
const preparations = new Map()
const transportErrors = new Map()
const runHeartbeats = new Map()
const busySessions = new Set()
const pendingWakeSessions = new Set()
const pendingWakeKinds = new Map()
const wakeInflightSessions = new Set()
const deletedSessions = new Set()
let observerGeneration = 0
function projectRoot(ctx) {
  return ctx.location?.project?.canonical || ctx.location?.project?.directory || ctx.location?.directory
}

function transportPath(runRoot) { return `${runRoot}/.transport/opencode.json` }
function markActivation(root) {
  if (!root) return
  try {
    const request = JSON.parse(readFileSync(`${root}/.opencode/tbag-activation.json`, "utf8"))
    if (!request?.token) return
    const dir = `${root}/TBag/harness`
    const path = `${dir}/opencode-activation.json`
    const tmp = `${path}.tmp-${process.pid}`
    mkdirSync(dir, { recursive: true })
    writeFileSync(tmp, JSON.stringify({
      format: "tbag-opencode-activation-v1",
      token: request.token,
      transport_generation: "v2",
      opencode_major: 2,
      adapter_pid: process.pid,
      activated_at: new Date().toISOString(),
    }, null, 2) + "\n")
    renameSync(tmp, path)
  } catch (_) {
    // Bootstrap proof is diagnostic/transport state; failure must not corrupt host startup.
  }
}
function persistTransport(runRoot) {
  if (!runRoot) return
  try {
    const parents = [...runHeartbeats.values()]
      .filter((item) => item.run_root === runRoot)
      .map((item) => ({ session_id: item.sessionID, run_root: item.run_root, last_queued_at_ms: item.lastQueuedAt, last_completion_probe_at_ms: item.lastCompletionProbeAt, last_health_wake_at_ms: item.lastHealthWakeAt, heartbeat_state: item.heartbeatState }))
    const observers = [...follows.values()]
      .filter((item) => item.args?.run_root === runRoot)
      .map((item) => ({
        session_id: item.sessionID,
        phase_id: item.args?.phase_id,
        task_id: item.args?.task_id,
        event_dir: item.args?.event_dir,
        observer_pid: item.proc?.pid,
        generation: item.generation,
        armed_at_ms: item.armedAt,
        done: item.done === true,
        orphaned: item.orphaned === true,
      }))
    const prep = [...preparations.values()]
      .filter((item) => item.run_root === runRoot)
      .map((item) => ({ session_id: item.sessionID, task_id: item.task_id, phase_id: item.phase_id, pid: item.pid, started_at_ms: item.startedAt }))
    const path = transportPath(runRoot)
    const tmp = `${path}.tmp-${process.pid}`
    mkdirSync(`${runRoot}/.transport`, { recursive: true })
    writeFileSync(tmp, JSON.stringify({
      format: "tbag-opencode-transport-v2",
      adapter_pid: process.pid,
      updated_at: new Date().toISOString(),
      parent_sessions: parents,
      observers,
      preparations: prep,
      last_arm_error: transportErrors.get(runRoot) || null,
    }, null, 2) + "\n")
    renameSync(tmp, path)
  } catch (_) {
    // Transport diagnostics are never semantic authority.
  }
}

const {
  durableHeartbeatState,
  registerRunHeartbeat,
  removeRunHeartbeat,
  sessionHasRunnableHeartbeat,
  pruneQuiescentHeartbeats,
  syncHeartbeatFromTick,
} = createHeartbeatRegistry({
  runHeartbeats,
  pendingWakeSessions,
  pendingWakeKinds,
  persistTransport,
})

function followKey(sessionID, args) {
  return [sessionID, args.run_root, args.phase_id, args.task_id, args.event_dir].join("\u0000")
}

function attemptCli(root, args, command) {
  return [
    "python3", `${root}/TBag/tools/dsd_attempt.py`, command,
    "--run-root", args.run_root,
    "--phase-id", args.phase_id,
    "--task-id", args.task_id,
    ...(args.event_dir ? ["--event-dir", args.event_dir] : []),
  ]
}

function checkedSync(argv, label) {
  const result = Bun.spawnSync(argv, { stdout: "pipe", stderr: "pipe" })
  if (result.exitCode !== 0) {
    const detail = decode(result.stderr) || decode(result.stdout) || `exit=${result.exitCode}`
    throw new Error(`${label}: ${detail}`)
  }
  return decode(result.stdout)
}

function validateAttempt(root, args) {
  const text = checkedSync(attemptCli(root, args, "inspect"), "Refusing invalid T-BAG attempt target")
  try { return JSON.parse(text) } catch (_) { return { state: "unknown" } }
}

function enrollHeartbeatFromCommand(sessionID, command) {
  if (!sessionID) return false
  const launch = isCoreAttemptCommand(command, "launch")
  if (!isParentTickCommand(command) && !launch) return false
  const runRoot = commandArg(command, "run-root")
  if (!runRoot) return false
  deletedSessions.delete(sessionID)
  registerRunHeartbeat(sessionID, { run_root: runRoot, activity_hint: launch ? "launch" : undefined })
  return true
}

function pulseRun(root, runRoot) {
  const result = Bun.spawnSync([
    "python3", `${root}/TBag/tools/parent_tick.py`, "pulse", "--run-root", runRoot,
  ], { stdout: "pipe", stderr: "pipe" })
  if (result.exitCode !== 0) {
    return { heartbeat_state: "idle-recovery", wake_parent: false, error: decode(result.stderr) || decode(result.stdout) || `exit=${result.exitCode}` }
  }
  try {
    return JSON.parse(decode(result.stdout))
  } catch (_) {
    return { heartbeat_state: "idle-recovery", wake_parent: false, error: "pulse returned invalid JSON" }
  }
}

function spawnObserver(root, args) {
  return Bun.spawn(attemptCli(root, args, "follow"), { stdout: "ignore", stderr: "ignore" })
}

function logError(message, extra = {}) {
  try { console.error(`[T-BAG] ${message}`, extra) } catch (_) {}
}

async function wakeParent(ctx, sessionID, kind) {
  await ctx.session.prompt({ sessionID, text: wakeText(kind) })
}

const { flushPendingWake, queueWake } = createWakeQueue({
  pendingWakeSessions,
  pendingWakeKinds,
  wakeInflightSessions,
  deletedSessions,
  busySessions,
  pruneQuiescentHeartbeats,
  sessionHasRunnableHeartbeat,
  wakeParent,
  logError: (_ctx, message, extra) => logError(message, extra),
})

function armAttempt(ctx, sessionID, root, args, validate = true) {
  const key = followKey(sessionID, args)
  const existing = follows.get(key)
  if (existing && !existing.done && (existing.proc?.exitCode === null || existing.proc?.exitCode === undefined)) {
    return { armed: true, already_armed: true, observer_healthy: true, observer_generation: existing.generation }
  }
  if (existing) follows.delete(key)
  const observed = validate ? validateAttempt(root, args) : { state: "unknown" }
  if (observed?.state === "terminal" || observed?.state === "dead-unresolved") {
    return { armed: false, already_armed: false, observer_healthy: false, attempt_state: observed.state }
  }

  const proc = spawnObserver(root, args)
  const entry = { proc, done: false, generation: ++observerGeneration, armedAt: Date.now(), sessionID, args: { ...args } }
  follows.set(key, entry)
  persistTransport(args.run_root)
  void (async () => {
    try {
      await proc.exited
    } catch (error) {
      logError("attempt observer failed; waking parent to tick", { task_id: args.task_id, error: String(error?.stack || error) })
    } finally {
      entry.done = true
      if (follows.get(key) === entry) follows.delete(key)
      persistTransport(args.run_root)
      queueWake(ctx, sessionID)
    }
  })()
  return { armed: true, already_armed: false, observer_healthy: true, observer_generation: entry.generation }
}

function resultText(result) {
  if (typeof result === "string") return result
  if (!result || typeof result !== "object") return ""
  if (typeof result.output === "string") return result.output
  if (typeof result.content === "string") return result.content
  if (Array.isArray(result.content)) {
    return result.content.map((part) => {
      if (typeof part === "string") return part
      if (typeof part?.text === "string") return part.text
      if (typeof part?.content === "string") return part.content
      return ""
    }).filter(Boolean).join("\n")
  }
  return ""
}

function launchResults(text) {
  return structuredObjects(text).filter((value) =>
    ["started", "preparing"].includes(value?.status) && value?.run_root && value?.phase_id && value?.task_id
  )
}

function preparationKey(sessionID, item) {
  return [sessionID, item.run_root, item.phase_id, item.task_id, item.preparation_pid].join("\u0000")
}

function pidAlive(pid) {
  try {
    if (!Number.isInteger(pid) || pid <= 0) return false
    process.kill(pid, 0)
    return true
  } catch (_) { return false }
}

function watchPreparation(ctx, sessionID, item) {
  if (!Number.isInteger(item?.preparation_pid)) return
  const key = preparationKey(sessionID, item)
  if (preparations.has(key)) return
  const entry = {
    sessionID,
    run_root: item.run_root,
    phase_id: item.phase_id,
    task_id: item.task_id,
    pid: item.preparation_pid,
    startedAt: Date.now(),
    timer: null,
  }
  entry.timer = setInterval(() => {
    if (pidAlive(entry.pid)) return
    clearInterval(entry.timer)
    preparations.delete(key)
    persistTransport(entry.run_root)
    queueWake(ctx, sessionID)
  }, 500)
  entry.timer.unref?.()
  preparations.set(key, entry)
  persistTransport(entry.run_root)
}

function repairObserversFromPacket(ctx, sessionID, root, runRoot, packet) {
  const live = Array.isArray(packet?.live_attempts) ? packet.live_attempts : []
  for (const item of live) {
    if (!item?.phase_id || !item?.task_id || !item?.event_dir) continue
    try {
      armAttempt(ctx, sessionID, root, {
        run_root: runRoot,
        phase_id: item.phase_id,
        task_id: item.task_id,
        event_dir: item.event_dir,
      })
      transportErrors.delete(runRoot)
    } catch (error) {
      transportErrors.set(runRoot, {
        at: new Date().toISOString(),
        task_id: item.task_id,
        event_dir: item.event_dir,
        error: String(error?.stack || error),
      })
    }
  }
  persistTransport(runRoot)
}

function repairObserversFromTick(ctx, sessionID, root, command, text) {
  const runRoot = commandArg(command, "run-root")
  if (!runRoot) return
  for (const packet of structuredObjects(text)) repairObserversFromPacket(ctx, sessionID, root, runRoot, packet)
}

function eventSessionID(event) {
  const data = event?.data || event?.properties || {}
  return data.sessionID || data.session_id || data.info?.id || data.session?.id || null
}

function markSessionStatus(ctx, event) {
  const sessionID = eventSessionID(event)
  if (!sessionID) return
  const data = event?.data || event?.properties || {}

  if (event.type === "session.created") {
    deletedSessions.delete(sessionID)
    return
  }
  if (event.type === "session.deleted") {
    deletedSessions.add(sessionID)
    busySessions.delete(sessionID)
    pendingWakeSessions.delete(sessionID)
    pendingWakeKinds.delete(sessionID)
    wakeInflightSessions.delete(sessionID)
    const affected = new Set()
    for (const [key, item] of runHeartbeats) {
      if (item.sessionID === sessionID) { affected.add(item.run_root); runHeartbeats.delete(key) }
    }
    for (const item of follows.values()) {
      if (item.sessionID === sessionID) { item.orphaned = true; affected.add(item.args?.run_root) }
    }
    for (const runRoot of affected) if (runRoot) persistTransport(runRoot)
    return
  }

  if (event.type === "session.execution.started") {
    busySessions.add(sessionID)
    return
  }
  if (["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"].includes(event.type)) {
    busySessions.delete(sessionID)
    void flushPendingWake(ctx, sessionID)
    return
  }

  // Compatibility with early V2/V1-shaped hosts. Current V2 does not rely on it.
  const status = data.status?.type || data.status
  if (event.type === "session.idle" || status === "idle" || event.type === "session.error") {
    busySessions.delete(sessionID)
    void flushPendingWake(ctx, sessionID)
    return
  }
  if (event.type === "session.status" && status && status !== "idle") busySessions.add(sessionID)
}
function checkpointInstruction(root) {
  const script = `${root}/TBag/tools/context_checkpoint.py`
  const result = Bun.spawnSync(["python3", script, "--project-root", root, "instruction"], { stdout: "pipe", stderr: "pipe" })
  if (result.exitCode === 4) return null
  if (result.exitCode !== 0) {
    const stderr = decode(result.stderr)
    return `## T-BAG continuity warning\n${stderr}\nDo not assume resume orientation is safe.`
  }
  return [
    "## T-BAG durable continuation",
    decode(result.stdout),
    "On resume/wake/heartbeat run one parent_tick.py tick first. Launch attempts normally; the OpenCode 2 adapter backgrounds preparation and repairs observer transport automatically. Never poll/wait in the conversational turn.",
  ].join("\n")
}

const TBagV2Plugin = {
  id: "tbag.transport",
  async setup(ctx) {
    const root = projectRoot(ctx)
    if (!root) throw new Error("T-BAG OpenCode 2 adapter cannot resolve the project root")
    markActivation(root)

    const controller = new AbortController()
    const heartbeatTimers = startHeartbeatTimers({
      host: ctx,
      runHeartbeats,
      deletedSessions,
      durableHeartbeatState,
      removeRunHeartbeat,
      pulseRun: (runRoot) => pulseRun(root, runRoot),
      persistTransport,
      transportErrors,
      queueWake,
      onPulse: (item, pulse) => repairObserversFromPacket(ctx, item.sessionID, root, item.run_root, pulse),
    })

    await ctx.tool.hook("execute.before", (event) => {
      if (event.tool !== "bash") return
      const input = event.input || {}
      const original = String(input.command || "")
      if (isCoreAttemptCommand(original, "follow")) {
        throw new Error("OpenCode T-BAG parents must not foreground dsd_attempt.py follow")
      }
      enrollHeartbeatFromCommand(event.sessionID, original)
      const backgrounded = backgroundLaunchCommand(original)
      if (backgrounded !== original) input.command = backgrounded
    })

    await ctx.tool.hook("execute.after", (event) => {
      if (event.tool !== "bash" || event.status !== "completed") return
      const command = String(event.input?.command || "")
      const sessionID = event.sessionID
      const text = resultText(event.result)
      if (isParentControlCommand(command) && sessionID) {
        if (isParentTickCommand(command)) repairObserversFromTick(ctx, sessionID, root, command, text)
        syncHeartbeatFromTick(sessionID, command, text)
      }
      if (!isCoreAttemptCommand(command, "launch")) return
      const results = launchResults(text)
      if (!results.length) {
        const runRoot = commandArg(command, "run-root")
        if (runRoot) {
          transportErrors.set(runRoot, { at: new Date().toISOString(), error: "launch output contained no structured T-BAG launch/preparation result" })
          persistTransport(runRoot)
          if (sessionID) queueWake(ctx, sessionID, "health")
        }
        logError("launch output contained no structured result; durable pulse recovery is armed and a bounded reconciliation wake was queued")
        return
      }
      for (const launch of results) {
        if (!sessionID) continue
        deletedSessions.delete(sessionID)
        registerRunHeartbeat(sessionID, launch)
        if (launch.status === "preparing") {
          watchPreparation(ctx, sessionID, launch)
          continue
        }
        try {
          armAttempt(ctx, sessionID, root, launch)
          transportErrors.delete(launch.run_root)
          persistTransport(launch.run_root)
        } catch (error) {
          transportErrors.set(launch.run_root, {
            at: new Date().toISOString(),
            task_id: launch.task_id,
            event_dir: launch.event_dir,
            error: String(error?.stack || error),
          })
          persistTransport(launch.run_root)
          logError("launch observer auto-arm failed; next tick will retry automatically", { task_id: launch.task_id })
        }
      }
    })

    await ctx.session.hook("compaction", (event) => {
      const text = checkpointInstruction(root)
      if (text) event.system.push({ type: "text", text })
    })

    void (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          markSessionStatus(ctx, event)
        }
      } catch (error) {
        if (!controller.signal.aborted) logError("event subscription failed", { error: String(error?.stack || error) })
      }
    })()

    return () => {
      controller.abort()
      heartbeatTimers.stop()
      for (const item of preparations.values()) if (item.timer) clearInterval(item.timer)
      preparations.clear()
    }
  },
}

export default TBagV2Plugin
