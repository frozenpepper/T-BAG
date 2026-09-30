import assert from "node:assert/strict"
import path from "node:path"
import { pathToFileURL } from "node:url"

const corePath = path.resolve(process.argv[2])
const core = await import(pathToFileURL(corePath).href + `?async-heartbeat=${Date.now()}`)

const originalSetInterval = globalThis.setInterval
const originalClearInterval = globalThis.clearInterval
const timers = []
globalThis.setInterval = (fn, ms) => {
  const timer = { fn, ms, unref() {} }
  timers.push(timer)
  return timer
}
globalThis.clearInterval = () => {}

const key = "ses\u0000/run"
const item = {
  sessionID: "ses",
  run_root: "/run",
  lastQueuedAt: 0,
  lastCompletionProbeAt: 0,
  lastHealthWakeAt: Date.now(),
  heartbeatState: "running",
}
const runHeartbeats = new Map([[key, item]])
const deletedSessions = new Set()
const transportErrors = new Map()
const wakeCalls = []
let persistCalls = 0
let pulseCalls = 0
const resolvers = []

try {
  const handle = core.startHeartbeatTimers({
    host: {},
    runHeartbeats,
    deletedSessions,
    durableHeartbeatState: () => "running",
    removeRunHeartbeat: () => false,
    pulseRun: async () => {
      pulseCalls += 1
      return await new Promise((resolve) => resolvers.push(resolve))
    },
    persistTransport: () => { persistCalls += 1 },
    transportErrors,
    queueWake: (_host, sessionID, kind) => wakeCalls.push([sessionID, kind]),
    onPulse: () => {},
  })

  assert.equal(timers.length, 2)
  const completion = timers[0]

  completion.fn()
  completion.fn()
  await Promise.resolve()
  assert.equal(pulseCalls, 1, "overlapping timer callbacks must coalesce one in-flight pulse")

  resolvers.shift()({ heartbeat_state: "running", wake_parent: true })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(wakeCalls.length, 1)
  assert.deepEqual(wakeCalls[0], ["ses", "completion"])
  assert.equal(persistCalls, 1)

  completion.fn()
  await Promise.resolve()
  assert.equal(pulseCalls, 2, "a later timer may probe again after the first pulse settles")
  resolvers.shift()({ heartbeat_state: "running", wake_parent: false })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(persistCalls, 2)

  handle.stop()
} finally {
  globalThis.setInterval = originalSetInterval
  globalThis.clearInterval = originalClearInterval
}

console.log("OPENCODE_ASYNC_HEARTBEAT_PASS")
