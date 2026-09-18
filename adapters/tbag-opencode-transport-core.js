import { readFileSync } from "node:fs"

export const COMPLETION_PULSE_MS = Math.max(60_000, Number(process.env.TBAG_COMPLETION_PULSE_MS || 60_000))
export const HEALTH_HEARTBEAT_MS = Math.max(
  COMPLETION_PULSE_MS,
  Number(process.env.TBAG_PARENT_HEALTH_HEARTBEAT_MS || process.env.TBAG_PARENT_HEARTBEAT_MS || 900_000),
)

export function decode(value) {
  return new TextDecoder().decode(value || new Uint8Array()).trim()
}

export function commandArg(command, name) {
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

export function isCoreAttemptCommand(command, subcommand) {
  return new RegExp(`dsd_attempt\\.py["']?\\s+${subcommand}(?:\\s|$)`).test(String(command || ""))
}

export function isParentTickCommand(command) {
  return /parent_tick\.py["']?\s+tick(?:\s|$)/.test(String(command || ""))
}

export function backgroundLaunchCommand(command) {
  return String(command || "").replace(/(dsd_attempt\.py["']?\s+launch)(?!\s+--background-prepare)/g, "$1 --background-prepare")
}

export function structuredObjects(text) {
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
    if (ch === "{") { if (depth === 0) start = i; depth++; continue }
    if (ch === "}" && depth > 0) {
      depth--
      if (depth === 0 && start >= 0) {
        try {
          const value = JSON.parse(source.slice(start, i + 1))
          if (value && typeof value === "object" && !Array.isArray(value)) out.push(value)
        } catch (_) {}
        start = -1
      }
    }
  }
  return out
}

export function wakeText(kind = "completion") {
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

export function createHeartbeatRegistry({
  runHeartbeats,
  pendingWakeSessions,
  pendingWakeKinds,
  persistTransport,
}) {
  const heartbeatKey = (sessionID, runRoot) => `${sessionID}\u0000${runRoot}`

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
      return "missing"
    }
  }

  function removeRunHeartbeat(sessionID, runRoot) {
    const removed = runHeartbeats.delete(heartbeatKey(sessionID, runRoot))
    if (!removed) return false
    if (![...runHeartbeats.values()].some((item) => item.sessionID === sessionID)) {
      pendingWakeSessions.delete(sessionID)
      pendingWakeKinds.delete(sessionID)
    }
    persistTransport(runRoot)
    return true
  }

  function registerRunHeartbeat(sessionID, args) {
    if (!sessionID || !args?.run_root) return false
    const state = durableHeartbeatState(args.run_root)
    if (state !== "running") {
      removeRunHeartbeat(sessionID, args.run_root)
      return false
    }
    const key = heartbeatKey(sessionID, args.run_root)
    const prior = runHeartbeats.get(key)
    const stamp = Date.now()
    runHeartbeats.set(key, {
      sessionID,
      run_root: args.run_root,
      lastQueuedAt: stamp,
      lastCompletionProbeAt: prior?.lastCompletionProbeAt || 0,
      lastHealthWakeAt: prior?.lastHealthWakeAt || stamp,
      heartbeatState: prior?.heartbeatState === "idle-recovery" ? "idle-recovery" : "running",
    })
    persistTransport(args.run_root)
    return true
  }

  function sessionHasRunnableHeartbeat(sessionID) {
    return [...runHeartbeats.values()].some((item) =>
      item.sessionID === sessionID
      && ["running", "idle-recovery"].includes(item.heartbeatState)
      && durableHeartbeatState(item.run_root) === "running"
    )
  }

  function pruneQuiescentHeartbeats(sessionID) {
    for (const item of [...runHeartbeats.values()]) {
      if (item.sessionID !== sessionID) continue
      if (durableHeartbeatState(item.run_root) !== "running") {
        removeRunHeartbeat(sessionID, item.run_root)
      }
    }
  }

  function syncHeartbeatFromTick(sessionID, command, text) {
    const runRoot = commandArg(command, "run-root")
    if (!runRoot || !sessionID) return
    const item = runHeartbeats.get(heartbeatKey(sessionID, runRoot))
    if (!item) return
    const packet = structuredObjects(text).find((value) => value?.format === "tbag-parent-loop-v1")
    if (!packet) return
    const statusState = heartbeatStateForStatus(packet.run_status)
    if (statusState !== "running" || packet.classification === "awaiting-owner" || packet.classification === "run-human-blocked") {
      removeRunHeartbeat(sessionID, runRoot)
      return
    }
    if (["active-idle", "completion-candidate", "recovery-required"].includes(packet.classification)) item.heartbeatState = "idle-recovery"
    else item.heartbeatState = "running"
    persistTransport(runRoot)
  }

  return {
    durableHeartbeatState,
    registerRunHeartbeat,
    removeRunHeartbeat,
    sessionHasRunnableHeartbeat,
    pruneQuiescentHeartbeats,
    syncHeartbeatFromTick,
  }
}

export function createWakeQueue({
  pendingWakeSessions,
  pendingWakeKinds,
  wakeInflightSessions,
  deletedSessions,
  busySessions,
  pruneQuiescentHeartbeats,
  sessionHasRunnableHeartbeat,
  wakeParent,
  logError,
}) {
  async function flushPendingWake(host, sessionID) {
    if (deletedSessions.has(sessionID)) {
      pendingWakeSessions.delete(sessionID)
      pendingWakeKinds.delete(sessionID)
      return
    }
    if (!pendingWakeSessions.has(sessionID)) return
    if (busySessions.has(sessionID) || wakeInflightSessions.has(sessionID)) return
    pruneQuiescentHeartbeats(sessionID)
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
      await wakeParent(host, sessionID, kind)
      delivered = true
    } catch (error) {
      pendingWakeSessions.add(sessionID)
      if (!pendingWakeKinds.has(sessionID)) pendingWakeKinds.set(sessionID, kind)
      try {
        await logError(host, "T-BAG parent wake failed; durable task state will reconcile on the next owner turn", {
          session_id: sessionID,
          error: String(error?.stack || error),
        })
      } catch (_) {}
    } finally {
      wakeInflightSessions.delete(sessionID)
      if (delivered && pendingWakeSessions.has(sessionID) && !busySessions.has(sessionID) && !deletedSessions.has(sessionID)) {
        void flushPendingWake(host, sessionID)
      }
    }
  }

  function queueWake(host, sessionID, kind = "completion") {
    if (!sessionID || deletedSessions.has(sessionID)) return
    const prior = pendingWakeKinds.get(sessionID)
    if (kind === "completion" || !prior) pendingWakeKinds.set(sessionID, kind)
    pendingWakeSessions.add(sessionID)
    void flushPendingWake(host, sessionID)
  }

  return { flushPendingWake, queueWake }
}

export function startHeartbeatTimers({
  host,
  runHeartbeats,
  deletedSessions,
  durableHeartbeatState,
  removeRunHeartbeat,
  pulseRun,
  persistTransport,
  transportErrors,
  queueWake,
}) {
  const completionTimer = setInterval(() => {
    for (const item of [...runHeartbeats.values()]) {
      if (deletedSessions.has(item.sessionID)) {
        removeRunHeartbeat(item.sessionID, item.run_root)
        continue
      }
      const durable = durableHeartbeatState(item.run_root)
      if (durable !== "running") {
        removeRunHeartbeat(item.sessionID, item.run_root)
        continue
      }
      if (item.heartbeatState !== "running") continue
      const pulse = pulseRun(item.run_root)
      item.lastCompletionProbeAt = Date.now()
      item.heartbeatState = pulse.heartbeat_state || "idle-recovery"
      if (pulse.error) {
        transportErrors.set(item.run_root, { at: new Date().toISOString(), error: `completion pulse failed: ${pulse.error}` })
      } else if (pulse.wake_parent === true) {
        transportErrors.delete(item.run_root)
        queueWake(host, item.sessionID, "completion")
      }
      persistTransport(item.run_root)
    }
  }, COMPLETION_PULSE_MS)
  completionTimer.unref?.()

  const healthTimer = setInterval(() => {
    const stamp = Date.now()
    for (const item of [...runHeartbeats.values()]) {
      if (deletedSessions.has(item.sessionID)) {
        removeRunHeartbeat(item.sessionID, item.run_root)
        continue
      }
      const durable = durableHeartbeatState(item.run_root)
      if (durable !== "running") {
        removeRunHeartbeat(item.sessionID, item.run_root)
        continue
      }
      if (!["running", "idle-recovery"].includes(item.heartbeatState)) continue
      if (stamp - item.lastHealthWakeAt < HEALTH_HEARTBEAT_MS) continue
      item.lastHealthWakeAt = stamp
      item.lastQueuedAt = stamp
      persistTransport(item.run_root)
      queueWake(host, item.sessionID, "health")
    }
  }, COMPLETION_PULSE_MS)
  healthTimer.unref?.()

  return {
    stop() {
      clearInterval(completionTimer)
      clearInterval(healthTimer)
    },
  }
}
