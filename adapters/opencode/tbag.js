import { tool } from "@opencode-ai/plugin"
import { readFileSync, mkdirSync, writeFileSync, renameSync } from "node:fs"

// OpenCode owns wake delivery; T-BAG durable task/run files own orchestration truth.
// This adapter keeps only disposable per-session/per-attempt transport state.
const follows = new Map()
const preparations = new Map()
const transportErrors = new Map()
const runHeartbeats = new Map()
let observerGeneration = 0
const COMPLETION_PULSE_MS = Math.max(60_000, Number(process.env.TBAG_COMPLETION_PULSE_MS || 60_000))
const HEALTH_HEARTBEAT_MS = Math.max(
  COMPLETION_PULSE_MS,
  Number(process.env.TBAG_PARENT_HEALTH_HEARTBEAT_MS || process.env.TBAG_PARENT_HEARTBEAT_MS || 900_000),
)
const busySessions = new Set()
const pendingWakeSessions = new Set()
const pendingWakeKinds = new Map()
const wakeInflightSessions = new Set()
const deletedSessions = new Set()

function transportPath(runRoot) { return `${runRoot}/.transport/opencode.json` }
function persistTransport(runRoot) {
  if (!runRoot) return
  try {
    const parents = [...runHeartbeats.values()]
      .filter((item) => item.run_root === runRoot)
      .map((item) => ({ session_id: item.sessionID, run_root: item.run_root, last_queued_at_ms: item.lastQueuedAt, last_completion_probe_at_ms: item.lastCompletionProbeAt, last_health_wake_at_ms: item.lastHealthWakeAt, heartbeat_state: item.heartbeatState }))
    const observers = [...follows.values()]
      .filter((item) => item.args?.run_root === runRoot)
      .map((item) => ({
        session_id: item.sessionID, phase_id: item.args?.phase_id, task_id: item.args?.task_id, event_dir: item.args?.event_dir,
        observer_pid: item.proc?.pid, generation: item.generation, armed_at_ms: item.armedAt, done: item.done === true, orphaned: item.orphaned === true,
      }))
    const path = transportPath(runRoot); const tmp = `${path}.tmp-${process.pid}`
    mkdirSync(`${runRoot}/.transport`, { recursive: true })
    const prep = [...preparations.values()].filter((item) => item.run_root === runRoot).map((item) => ({ session_id:item.sessionID, task_id:item.task_id, phase_id:item.phase_id, pid:item.pid, started_at_ms:item.startedAt }))
    writeFileSync(tmp, JSON.stringify({ format: "tbag-opencode-transport-v1", adapter_pid: process.pid, updated_at: new Date().toISOString(), parent_sessions: parents, observers, preparations: prep, last_arm_error: transportErrors.get(runRoot) || null }, null, 2) + "\n")
    renameSync(tmp, path)
  } catch (_) { /* presentation/diagnostic state may never break orchestration */ }
}


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

function decode(value) {
  return new TextDecoder().decode(value || new Uint8Array()).trim()
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
  // Read-only inspect proves this event belongs to the exact run/phase/task tuple.
  const text = checkedSync(attemptCli(root, args, "inspect"), "Refusing invalid T-BAG attempt target")
  try { return JSON.parse(text) } catch (_) { return { state: "unknown" } }
}

function heartbeatKey(sessionID, runRoot) { return `${sessionID}\u0000${runRoot}` }

function heartbeatStateForStatus(status) {
  if (status === "human-blocked") return "waiting"
  if (status === "paused-by-user") return "paused"
  if (status === "completed" || status === "abandoned") return "ended"
  return "running"
}

function durableHeartbeatState(runRoot) {
  try {
    const status = JSON.parse(readFileSync(`${runRoot}/run.json`, "utf8")).status
    return heartbeatStateForStatus(status)
  } catch (_) {
    return "idle-recovery"
  }
}

function registerRunHeartbeat(sessionID, args) {
  if (!sessionID || !args?.run_root) return
  const key = heartbeatKey(sessionID, args.run_root)
  const prior = runHeartbeats.get(key)
  const stamp = Date.now()
  runHeartbeats.set(key, {
    sessionID,
    run_root: args.run_root,
    lastQueuedAt: stamp,
    lastCompletionProbeAt: prior?.lastCompletionProbeAt || 0,
    lastHealthWakeAt: stamp,
    heartbeatState: durableHeartbeatState(args.run_root),
  })
  persistTransport(args.run_root)
}

function commandArg(command, name) {
  const text = String(command || "")
  const marker = `--${name}`
  const index = text.indexOf(marker)
  if (index < 0) return null
  let rest = text.slice(index + marker.length).trimStart()
  if (!rest) return null
  const quote = rest[0]
  if (quote === '"' || quote === "'") {
    const end = rest.indexOf(quote, 1)
    return end > 0 ? rest.slice(1, end) : null
  }
  return rest.split(/\s/, 1)[0] || null
}

function isParentTickCommand(command) {
  return /parent_tick\.py["']?\s+tick(?:\s|$)/.test(String(command || ""))
}

function enrollHeartbeatFromCommand(sessionID, command) {
  if (!sessionID) return false
  if (!isParentTickCommand(command) && !isCoreAttemptCommand(command, "launch")) return false
  const runRoot = commandArg(command, "run-root")
  if (!runRoot) return false
  deletedSessions.delete(sessionID)
  busySessions.add(sessionID)
  registerRunHeartbeat(sessionID, { run_root: runRoot })
  return true
}
function runIsActive(runRoot) {
  return durableHeartbeatState(runRoot) === "running"
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

function sessionHasRunnableHeartbeat(sessionID) {
  return [...runHeartbeats.values()].some((item) =>
    item.sessionID === sessionID
    && ["running", "idle-recovery"].includes(item.heartbeatState)
    && runIsActive(item.run_root)
  )
}

function spawnObserver(root, args) {
  // Core role-aware deadlines are canonical: 2h Grunt, 6h Analyst.
  return Bun.spawn(attemptCli(root, args, "follow"), { stdout: "ignore", stderr: "ignore" })
}

async function logError(client, message, extra = {}) {
  try {
    await client.app.log({ body: { service: "tbag", level: "error", message, extra } })
  } catch (_) {}
}

function wakeText(kind = "completion") {
  if (kind === "health") {
    return [
      "[T-BAG health heartbeat]",
      "This is a periodic orchestration checkup; no worker completion is implied.",
      "Run one parent_tick.py tick now and use that packet as the canonical parent turn boundary.",
      "If the tick says workers-running, yield again. Do not manufacture work or user updates.",
    ].join("\n")
  }
  return [
    "[T-BAG completion wake]",
    "A worker/lifecycle transition was detected by an observer or the deterministic completion pulse.",
    "Run one parent_tick.py tick now and use that packet as the canonical parent turn boundary.",
    "For new attempts run the normal detached dsd_attempt.py launch, then yield.",
  ].join("\n")
}

async function wakeParent(client, sessionID, kind) {
  await client.session.prompt({
    path: { id: sessionID },
    body: { parts: [{ type: "text", text: wakeText(kind) }] },
  })
}

async function flushPendingWake(client, sessionID) {
  if (deletedSessions.has(sessionID)) {
    pendingWakeSessions.delete(sessionID)
    return
  }
  if (!pendingWakeSessions.has(sessionID)) return
  if (busySessions.has(sessionID) || wakeInflightSessions.has(sessionID)) return
  if (!sessionHasRunnableHeartbeat(sessionID)) {
    pendingWakeSessions.delete(sessionID)
    pendingWakeKinds.delete(sessionID)
    return
  }

  const kind = pendingWakeKinds.get(sessionID) || "completion"
  pendingWakeSessions.delete(sessionID)
  pendingWakeKinds.delete(sessionID)
  wakeInflightSessions.add(sessionID)
  let delivered = false
  try {
    await wakeParent(client, sessionID, kind)
    delivered = true
  } catch (error) {
    // Durable task state is authoritative. Preserve only this disposable hint and
    // wait for a later host lifecycle transition; never retry-loop here.
    pendingWakeSessions.add(sessionID)
    if (!pendingWakeKinds.has(sessionID)) pendingWakeKinds.set(sessionID, kind)
    await logError(client, "T-BAG parent wake failed; durable task state will reconcile on the next owner turn", {
      session_id: sessionID,
      error: String(error?.stack || error),
    })
  } finally {
    wakeInflightSessions.delete(sessionID)
    // An observer can finish while the generated wake turn itself is running. Its
    // idle event may race this interlock. After a successful delivery only, give
    // the coalesced bit one final non-blocking flush. Failed delivery never spins.
    if (delivered && pendingWakeSessions.has(sessionID) && !busySessions.has(sessionID) && !deletedSessions.has(sessionID)) {
      void flushPendingWake(client, sessionID)
    }
  }
}

function queueWake(client, sessionID, kind = "completion") {
  if (!sessionID || deletedSessions.has(sessionID)) return
  const prior = pendingWakeKinds.get(sessionID)
  if (kind === "completion" || !prior) pendingWakeKinds.set(sessionID, kind)
  pendingWakeSessions.add(sessionID)
  void flushPendingWake(client, sessionID)
}

function armAttempt(client, sessionID, root, args, validate = true) {
  const key = followKey(sessionID, args)
  const existing = follows.get(key)
  if (existing && !existing.done && (existing.proc?.exitCode === null || existing.proc?.exitCode === undefined)) {
    return { armed: true, already_armed: true, observer_healthy: true, observer_generation: existing.generation, task_id: args.task_id, event_dir: args.event_dir }
  }
  if (existing) follows.delete(key)
  const observed = validate ? validateAttempt(root, args) : { state: "unknown" }
  if (observed?.state === "terminal" || observed?.state === "dead-unresolved") {
    return { armed: false, already_armed: false, observer_healthy: false, attempt_state: observed.state, task_id: args.task_id, event_dir: args.event_dir }
  }

  const proc = spawnObserver(root, args)
  const entry = { proc, done: false, generation: ++observerGeneration, armedAt: Date.now(), sessionID, args: { ...args } }
  follows.set(key, entry)
  persistTransport(args.run_root)
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
      persistTransport(args.run_root)
      queueWake(client, sessionID)
    }
  })()

  return { armed: true, already_armed: false, observer_healthy: true, observer_generation: entry.generation, task_id: args.task_id, event_dir: args.event_dir }
}

function syncHeartbeatFromTick(sessionID, command, text) {
  const runRoot = commandArg(command, "run-root")
  if (!runRoot || !sessionID) return
  const item = runHeartbeats.get(heartbeatKey(sessionID, runRoot))
  if (!item) return
  const packet = structuredObjects(text).find((value) => value?.format === "tbag-parent-loop-v1")
  if (!packet) return
  const statusState = heartbeatStateForStatus(packet.run_status)
  if (statusState !== "running") item.heartbeatState = statusState
  else if (packet.classification === "awaiting-owner") item.heartbeatState = "waiting"
  else if (["active-idle", "completion-candidate", "recovery-required"].includes(packet.classification)) item.heartbeatState = "idle-recovery"
  else item.heartbeatState = "running"
  persistTransport(runRoot)
}

function eventSessionID(event) {
  if (event?.type === "session.created" || event?.type === "session.updated" || event?.type === "session.deleted") {
    return event?.properties?.info?.id
  }
  return event?.properties?.sessionID
}

function markSessionStatus(client, event) {
  const sessionID = eventSessionID(event)
  if (!sessionID) return

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
    for (const [key, item] of runHeartbeats) if (item.sessionID === sessionID) { affected.add(item.run_root); runHeartbeats.delete(key) }
    for (const item of follows.values()) if (item.sessionID === sessionID) { item.orphaned = true; affected.add(item.args?.run_root) }
    for (const runRoot of affected) if (runRoot) persistTransport(runRoot)
    return
  }

  const status = event.type === "session.status" ? event?.properties?.status?.type : undefined
  if (event.type === "session.idle" || status === "idle" || event.type === "session.error") {
    busySessions.delete(sessionID)
    void flushPendingWake(client, sessionID)
    return
  }
  if (event.type === "session.status") busySessions.add(sessionID)
}

function isCoreAttemptCommand(command, subcommand) {
  return new RegExp(`dsd_attempt\\.py["']?\\s+${subcommand}(?:\\s|$)`).test(String(command || ""))
}

function structuredObjects(text) {
  const source = String(text || "")
  const out = []
  let start = -1, depth = 0, quoted = false, escaped = false
  for (let i = 0; i < source.length; i++) {
    const ch = source[i]
    if (quoted) {
      if (escaped) escaped = false
      else if (ch === "\\") escaped = true
      else if (ch === '"') quoted = false
      continue
    }
    if (ch === '"') { quoted = true; continue }
    if (ch === '{') { if (depth === 0) start = i; depth++; continue }
    if (ch === '}' && depth > 0) {
      depth--
      if (depth === 0 && start >= 0) {
        try { const value = JSON.parse(source.slice(start, i + 1)); if (value && typeof value === "object" && !Array.isArray(value)) out.push(value) } catch (_) {}
        start = -1
      }
    }
  }
  return out
}

function launchResultsFromToolOutput(output) {
  return structuredObjects(output?.output).filter((value) =>
    ["started", "preparing"].includes(value?.status) && value?.run_root && value?.phase_id && value?.task_id
  )
}

function backgroundLaunchCommand(command) {
  return String(command || "").replace(/(dsd_attempt\.py["']?\s+launch)(?!\s+--background-prepare)/g, "$1 --background-prepare")
}

function preparationKey(sessionID, item) { return [sessionID,item.run_root,item.phase_id,item.task_id,item.preparation_pid].join("\\u0000") }
function pidAlive(pid) { try { if (!Number.isInteger(pid) || pid <= 0) return false; process.kill(pid, 0); return true } catch (_) { return false } }
function watchPreparation(client, sessionID, item) {
  if (!Number.isInteger(item?.preparation_pid)) return
  const key=preparationKey(sessionID,item)
  if (preparations.has(key)) return
  const entry={sessionID,run_root:item.run_root,phase_id:item.phase_id,task_id:item.task_id,pid:item.preparation_pid,startedAt:Date.now(),timer:null}
  entry.timer=setInterval(() => {
    if (pidAlive(entry.pid)) return
    clearInterval(entry.timer); preparations.delete(key); persistTransport(entry.run_root); queueWake(client,sessionID)
  }, 500)
  entry.timer.unref?.(); preparations.set(key,entry); persistTransport(entry.run_root)
}

function repairObserversFromTick(client, sessionID, root, command, output) {
  const runRoot=commandArg(command,"run-root")
  if (!runRoot) return
  for (const packet of structuredObjects(output?.output)) {
    const live=Array.isArray(packet?.live_attempts) ? packet.live_attempts : []
    for (const item of live) {
      if (!item?.phase_id || !item?.task_id || !item?.event_dir) continue
      try {
        armAttempt(client,sessionID,root,{run_root:runRoot,phase_id:item.phase_id,task_id:item.task_id,event_dir:item.event_dir})
        transportErrors.delete(runRoot)
      } catch (error) {
        transportErrors.set(runRoot,{at:new Date().toISOString(),task_id:item.task_id,event_dir:item.event_dir,error:String(error?.stack || error)})
      }
    }
  }
  persistTransport(runRoot)
}

const followArgs = {
  run_root: tool.schema.string().describe("Absolute T-BAG run root"),
  phase_id: tool.schema.string().describe("Phase id"),
  task_id: tool.schema.string().describe("Task id"),
  event_dir: tool.schema.string().describe("Exact event_dir recorded for the live attempt"),
}

const TBagPlugin = async (ctx) => {
  const root = process.env.TBAG_PROJECT_ROOT || ctx.worktree || ctx.directory
  const completionTimer = setInterval(() => {
    for (const [key, item] of runHeartbeats) {
      if (deletedSessions.has(item.sessionID)) {
        runHeartbeats.delete(key); persistTransport(item.run_root); continue
      }
      const durable = durableHeartbeatState(item.run_root)
      if (durable !== "running") {
        item.heartbeatState = durable; persistTransport(item.run_root); continue
      }
      if (item.heartbeatState !== "running") continue
      const pulse = pulseRun(root, item.run_root)
      item.lastCompletionProbeAt = Date.now()
      item.heartbeatState = pulse.heartbeat_state || "idle-recovery"
      if (pulse.error) {
        transportErrors.set(item.run_root,{at:new Date().toISOString(),error:`completion pulse failed: ${pulse.error}`})
      } else if (pulse.wake_parent === true) {
        transportErrors.delete(item.run_root)
        queueWake(ctx.client,item.sessionID,"completion")
      }
      persistTransport(item.run_root)
    }
  }, COMPLETION_PULSE_MS)
  completionTimer.unref?.()

  const healthTimer = setInterval(() => {
    const stamp=Date.now()
    for (const [key,item] of runHeartbeats) {
      if (deletedSessions.has(item.sessionID)) {
        runHeartbeats.delete(key); persistTransport(item.run_root); continue
      }
      const durable=durableHeartbeatState(item.run_root)
      if (durable !== "running") {
        item.heartbeatState=durable; persistTransport(item.run_root); continue
      }
      if (!["running","idle-recovery"].includes(item.heartbeatState)) continue
      if (stamp-item.lastHealthWakeAt < HEALTH_HEARTBEAT_MS) continue
      item.lastHealthWakeAt=stamp; item.lastQueuedAt=stamp
      persistTransport(item.run_root)
      queueWake(ctx.client,item.sessionID,"health")
    }
  }, COMPLETION_PULSE_MS)
  healthTimer.unref?.()
  return ({
  tool: {
    tbag_follow: tool({
      description: "OpenCode T-BAG optional wake-arm/re-arm primitive. Validate and observe exactly one already-launched recorded attempt, return immediately, and wake this same parent session when the observer exits. Current adapters automatically enroll heartbeat supervision on parent_tick.py tick and auto-arm successful structured launches; call tbag_follow only when a tick requests observer re-arm, after adapter recovery, or for explicit transport diagnosis. Idempotent for an already-armed exact attempt.",
      args: followArgs,
      async execute(args, context) {
        const sessionID = context.sessionID
        const root = context.worktree || context.directory || ctx.worktree || ctx.directory
        deletedSessions.delete(sessionID)
        busySessions.add(sessionID)
        registerRunHeartbeat(sessionID, args)
        const observer = armAttempt(ctx.client, sessionID, root, args)
        return JSON.stringify({ ...observer, heartbeat_registered: true, semantics: "wake transport only; parent tick and durable T-BAG state remain authoritative" })
      },
    }),
  },

  // Completion can race the parent session's current generation. Hold one ephemeral
  // coalesced wake until OpenCode says the session is no longer busy. No polling,
  // durable notification queue, task routing or scheduling lives here.
  event: async ({ event }) => {
    markSessionStatus(ctx.client, event)
  },

  // Direct core launch remains the stable parent operation. Direct core follow is
  // forbidden because it can monopolize the conversational turn. Merely executing
  // the normal parent tick or launch auto-enrolls this session/run in heartbeat
  // supervision; the parent never has to perform a separate heartbeat setup ritual.
  "tool.execute.before": async (input, output) => {
    if (input.tool !== "bash") return
    const original = String(output?.args?.command || "")
    if (isCoreAttemptCommand(original, "follow")) {
      throw new Error("OpenCode T-BAG parents must not foreground dsd_attempt.py follow")
    }
    enrollHeartbeatFromCommand(input.sessionID, original)
    const backgrounded = backgroundLaunchCommand(original)
    if (backgrounded !== original) output.args.command = backgrounded
  },

  // A current adapter auto-arms an observer after a successful structured launch.
  // tbag_follow remains an idempotent explicit re-arm/diagnostic path, not a
  // prerequisite for heartbeat supervision or normal autonomous progress.
  "tool.execute.after": async (input, output) => {
    if (input.tool !== "bash") return
    const command=String(input?.args?.command || "")
    const sessionID=input.sessionID
    const root=ctx.worktree || ctx.directory
    if (isParentTickCommand(command) && sessionID && root) {
      repairObserversFromTick(ctx.client,sessionID,root,command,output)
      syncHeartbeatFromTick(sessionID,command,String(output?.output || ""))
    }
    if (!isCoreAttemptCommand(command,"launch")) return
    const results=launchResultsFromToolOutput(output)
    if (!results.length) {
      const runRoot=commandArg(command,"run-root")
      if (runRoot) { transportErrors.set(runRoot,{at:new Date().toISOString(),error:"launch output contained no structured T-BAG launch/preparation result"}); persistTransport(runRoot) }
      await logError(ctx.client,"T-BAG launch output contained no structured result; heartbeat/tick reconciliation remains authoritative")
      return
    }
    for (const launch of results) {
      if (!sessionID || !root) continue
      deletedSessions.delete(sessionID); busySessions.add(sessionID); registerRunHeartbeat(sessionID,launch)
      if (launch.status === "preparing") { watchPreparation(ctx.client,sessionID,launch); continue }
      try {
        armAttempt(ctx.client,sessionID,root,launch); transportErrors.delete(launch.run_root); persistTransport(launch.run_root)
      } catch (error) {
        transportErrors.set(launch.run_root,{at:new Date().toISOString(),task_id:launch.task_id,event_dir:launch.event_dir,error:String(error?.stack || error)}); persistTransport(launch.run_root)
        await logError(ctx.client,"T-BAG launch observer auto-arm failed; next tick will retry automatically",{task_id:launch.task_id,event_dir:launch.event_dir,error:String(error?.stack || error)})
      }
    }
  },

  "experimental.session.compacting": async (_input, output) => {
    const root = process.env.TBAG_PROJECT_ROOT || ctx.worktree || ctx.directory
    const script = `${root}/TBag/tools/context_checkpoint.py`
    const result = Bun.spawnSync(["python3", script, "--project-root", root, "instruction"], { stdout: "pipe", stderr: "pipe" })
    if (result.exitCode === 4) return
    if (result.exitCode !== 0) {
      const stderr = decode(result.stderr)
      output.context.push(`\n## T-BAG continuity warning\n${stderr}\nDo not assume resume orientation is safe.\n`)
      return
    }
    const text = decode(result.stdout)
    output.context.push(`\n## T-BAG durable continuation\n${text}\nOpenCode invariant: every resume/wake/heartbeat begins with one parent_tick.py tick; that tick auto-enrolls the current session/run in heartbeat supervision. For every new attempt run the normal detached core dsd_attempt.py launch; the adapter auto-arms structured launches. Use tbag_follow only when tick requests re-arm/recovery. Wakes are hints; tick owns monitoring, updates and project-end state. Never poll/wait in the conversational turn.\n`)
  },
  })
}

// Exactly one plugin export. OpenCode loads every function export from a legacy
// plugin module, so exporting the same function under multiple names duplicates hooks.
export default TBagPlugin
