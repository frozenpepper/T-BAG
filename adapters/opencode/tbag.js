import { tool } from "@opencode-ai/plugin"
import { readFileSync, mkdirSync, writeFileSync, renameSync } from "node:fs"

// OpenCode owns wake delivery; T-BAG durable task/run files own orchestration truth.
// This adapter keeps only disposable per-session/per-attempt transport state.
const follows = new Map()
const runHeartbeats = new Map()
let observerGeneration = 0
const HEARTBEAT_MS = Math.max(60_000, Number(process.env.TBAG_PARENT_HEARTBEAT_MS || 600_000))
const busySessions = new Set()
const pendingWakeSessions = new Set()
const wakeInflightSessions = new Set()
const deletedSessions = new Set()

function transportPath(runRoot) { return `${runRoot}/.transport/opencode.json` }
function persistTransport(runRoot) {
  if (!runRoot) return
  try {
    const parents = [...runHeartbeats.values()]
      .filter((item) => item.run_root === runRoot)
      .map((item) => ({ session_id: item.sessionID, run_root: item.run_root, last_queued_at_ms: item.lastQueuedAt }))
    const observers = [...follows.values()]
      .filter((item) => item.args?.run_root === runRoot)
      .map((item) => ({
        session_id: item.sessionID, phase_id: item.args?.phase_id, task_id: item.args?.task_id, event_dir: item.args?.event_dir,
        observer_pid: item.proc?.pid, generation: item.generation, armed_at_ms: item.armedAt, done: item.done === true, orphaned: item.orphaned === true,
      }))
    const path = transportPath(runRoot); const tmp = `${path}.tmp-${process.pid}`
    mkdirSync(`${runRoot}/.transport`, { recursive: true })
    writeFileSync(tmp, JSON.stringify({ format: "tbag-opencode-transport-v1", adapter_pid: process.pid, updated_at: new Date().toISOString(), parent_sessions: parents, observers }, null, 2) + "\n")
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
function registerRunHeartbeat(sessionID, args) {
  runHeartbeats.set(heartbeatKey(sessionID, args.run_root), {
    sessionID, run_root: args.run_root, lastQueuedAt: Date.now(),
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
  try { return JSON.parse(readFileSync(`${runRoot}/run.json`, "utf8")).status === "active" } catch (_) { return false }
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

async function wakeParent(client, sessionID) {
  await client.session.prompt({
    path: { id: sessionID },
    body: {
      parts: [{
        type: "text",
        text: [
          "[T-BAG lifecycle wake]",
          "One or more per-attempt observers finished while you were yielded.",
          "Run one parent_tick.py tick now. Treat its monitoring/actions/update/project-end packet as the canonical parent turn boundary.",
          "For each new attempt: run the normal detached core dsd_attempt.py launch. The current adapter auto-enrolls the run heartbeat and auto-arms the observer from a structured launch; use tbag_follow only for explicit observer re-arm/recovery. A periodic transport heartbeat will request another tick even if an individual observer wake is lost.",
          "This message grants no semantic authority. Stay silent unless normal owner-communication rules require a reply.",
        ].join("\n"),
      }],
    },
  })
}

async function flushPendingWake(client, sessionID) {
  if (deletedSessions.has(sessionID)) {
    pendingWakeSessions.delete(sessionID)
    return
  }
  if (!pendingWakeSessions.has(sessionID)) return
  if (busySessions.has(sessionID) || wakeInflightSessions.has(sessionID)) return

  pendingWakeSessions.delete(sessionID)
  wakeInflightSessions.add(sessionID)
  let delivered = false
  try {
    await wakeParent(client, sessionID)
    delivered = true
  } catch (error) {
    // Durable task state is authoritative. Preserve only this disposable hint and
    // wait for a later host lifecycle transition; never retry-loop here.
    pendingWakeSessions.add(sessionID)
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

function queueWake(client, sessionID) {
  if (deletedSessions.has(sessionID)) return
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

function launchResultFromToolOutput(output) {
  const text = String(output?.output || "").trim()
  if (!text) return null
  try {
    const value = JSON.parse(text)
    if (value?.status !== "started" || !value?.run_root || !value?.phase_id || !value?.task_id || !value?.event_dir) return null
    return value
  } catch (_) {
    return null
  }
}

const followArgs = {
  run_root: tool.schema.string().describe("Absolute T-BAG run root"),
  phase_id: tool.schema.string().describe("Phase id"),
  task_id: tool.schema.string().describe("Task id"),
  event_dir: tool.schema.string().describe("Exact event_dir recorded for the live attempt"),
}

const TBagPlugin = async (ctx) => {
  const heartbeatTimer = setInterval(() => {
    for (const [key, item] of runHeartbeats) {
      if (deletedSessions.has(item.sessionID) || !runIsActive(item.run_root)) {
        runHeartbeats.delete(key); persistTransport(item.run_root); continue
      }
      if (Date.now() - item.lastQueuedAt < HEARTBEAT_MS) continue
      item.lastQueuedAt = Date.now()
      persistTransport(item.run_root)
      queueWake(ctx.client, item.sessionID)
    }
  }, HEARTBEAT_MS)
  heartbeatTimer.unref?.()
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
    const command = String(output?.args?.command || "")
    if (isCoreAttemptCommand(command, "follow")) {
      throw new Error("OpenCode T-BAG parents must use non-blocking tbag_follow; Bash/Python dsd_attempt.py follow is forbidden")
    }
    enrollHeartbeatFromCommand(input.sessionID, command)
  },

  // A current adapter auto-arms an observer after a successful structured launch.
  // tbag_follow remains an idempotent explicit re-arm/diagnostic path, not a
  // prerequisite for heartbeat supervision or normal autonomous progress.
  "tool.execute.after": async (input, output) => {
    if (input.tool !== "bash" || !isCoreAttemptCommand(input?.args?.command, "launch")) return
    const launch = launchResultFromToolOutput(output)
    if (!launch) {
      await logError(ctx.client, "T-BAG launch completed but adapter could not prove its structured launch result; heartbeat supervision remains enrolled and the next tick can request an explicit tbag_follow re-arm if needed")
      return
    }
    const sessionID = input.sessionID
    const root = ctx.worktree || ctx.directory
    if (!sessionID || !root) return
    deletedSessions.delete(sessionID)
    busySessions.add(sessionID)
    registerRunHeartbeat(sessionID, launch)
    try {
      armAttempt(ctx.client, sessionID, root, launch)
    } catch (error) {
      // Never convert a successful detached launch into a failed tool result.
      // Heartbeat supervision is already enrolled; a later tick may request an
      // explicit tbag_follow re-arm without blocking normal autonomous progress.
      await logError(ctx.client, "T-BAG launch observer auto-arm failed; heartbeat remains active and tick may request tbag_follow re-arm", {
        task_id: launch.task_id,
        event_dir: launch.event_dir,
        error: String(error?.stack || error),
      })
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
