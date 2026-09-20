import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { pathToFileURL } from "node:url"

const pluginPath = path.resolve(process.argv[2])
assert.ok(pluginPath, "plugin path required")
const scratchRoot = path.join(process.cwd(), "TBag", "scratch")
fs.mkdirSync(scratchRoot, { recursive: true })
const tmp = fs.mkdtempSync(path.join(scratchRoot, "opencode-v2-runtime-"))
const runRoot = path.join(tmp, "run")
fs.mkdirSync(runRoot, { recursive: true })
fs.writeFileSync(path.join(runRoot, "run.json"), JSON.stringify({ status: "active" }))
fs.mkdirSync(path.join(tmp, ".opencode"), { recursive: true })
fs.writeFileSync(path.join(tmp, ".opencode", "tbag-activation.json"), JSON.stringify({ token: "rc63-v2-token", transport_generation: "v2", opencode_major: 2 }))

const encoder = new TextEncoder()
const observers = []
function deferredObserver() {
  let resolveExit
  const exited = new Promise((resolve) => { resolveExit = resolve })
  const item = {
    pid: 424242 + observers.length,
    exitCode: null,
    exited,
    resolve() { this.exitCode = 0; resolveExit(0) },
  }
  observers.push(item)
  return item
}
globalThis.Bun = {
  spawnSync(argv) {
    if (argv[2] === "inspect") return { exitCode: 0, stdout: encoder.encode('{"state":"running"}'), stderr: encoder.encode("") }
    if (argv[2] === "pulse") return { exitCode: 0, stdout: encoder.encode('{"format":"tbag-parent-pulse-v1","heartbeat_state":"running","wake_parent":false}'), stderr: encoder.encode("") }
    if (argv.some((x) => String(x).includes("context_checkpoint.py"))) return { exitCode: 4, stdout: encoder.encode(""), stderr: encoder.encode("") }
    throw new Error(`unexpected spawnSync: ${argv.join(" ")}`)
  },
  spawn() { return deferredObserver() },
}

function eventQueue() {
  const queued = []
  const waiters = []
  let done = false
  return {
    push(value) {
      const waiter = waiters.shift()
      if (waiter) waiter({ value, done: false })
      else queued.push(value)
    },
    close() {
      done = true
      while (waiters.length) waiters.shift()({ value: undefined, done: true })
    },
    stream: {
      [Symbol.asyncIterator]() { return this },
      next() {
        if (queued.length) return Promise.resolve({ value: queued.shift(), done: false })
        if (done) return Promise.resolve({ value: undefined, done: true })
        return new Promise((resolve) => waiters.push(resolve))
      },
    },
  }
}

const events = eventQueue()
const toolHooks = new Map()
const sessionHooks = new Map()
const prompts = []
const ctx = {
  location: { directory: tmp, project: { canonical: tmp } },
  tool: { hook: async (name, fn) => { toolHooks.set(name, fn); return { dispose: async () => {} } } },
  session: {
    hook: async (name, fn) => { sessionHooks.set(name, fn); return { dispose: async () => {} } },
    prompt: async (request) => { prompts.push(request); return {} },
  },
  event: { subscribe() { return events.stream } },
}

const mod = await import(pathToFileURL(pluginPath).href + `?rc61=${Date.now()}`)
const plugin = mod.default
assert.equal(plugin.id, "tbag.transport")
const cleanup = await plugin.setup(ctx)
assert.equal(typeof cleanup, "function")
const activation = JSON.parse(fs.readFileSync(path.join(tmp, "TBag", "harness", "opencode-activation.json"), "utf8"))
assert.equal(activation.token, "rc63-v2-token")
assert.equal(activation.transport_generation, "v2")
assert.equal(activation.opencode_major, 2)
const before = toolHooks.get("execute.before")
const after = toolHooks.get("execute.after")
assert.equal(typeof before, "function")
assert.equal(typeof after, "function")
assert.equal(typeof sessionHooks.get("compaction"), "function")
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

function launchCommand(task) {
  return `python3 TBag/tools/dsd_attempt.py launch --run-root "${runRoot}" --phase-id P --task-id ${task}`
}
function launchResult(task) {
  return { status: "started", run_root: runRoot, phase_id: "P", task_id: task, role: "implementer", event_dir: path.join(runRoot, `event-${task}`) }
}

const tickCommand = `python3 TBag/tools/parent_tick.py tick --run-root "${runRoot}"`
await before({ tool: "bash", sessionID: "ses-wait", input: { command: tickCommand } })
await after({ tool: "bash", sessionID: "ses-wait", status: "completed", input: { command: tickCommand }, result: JSON.stringify({ format: "tbag-parent-loop-v1", run_status: "active", classification: "workers-running" }) })
let transportState = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.ok(transportState.parent_sessions.some((x) => x.session_id === "ses-wait"), "tick must enroll V2 heartbeat")
fs.writeFileSync(path.join(runRoot, "parent-loop.json"), JSON.stringify({ format: "tbag-parent-loop-v1", owner_wait: { open: true, question_id: "q1" } }))
const waitCommand = `python3 TBag/tools/parent_tick.py wait-owner --run-root "${runRoot}" --question-id q1`
await after({ tool: "bash", sessionID: "ses-wait", status: "completed", input: { command: waitCommand }, result: JSON.stringify({ format: "tbag-parent-loop-v1", run_status: "active", classification: "owner-question-open", heartbeat_state: "waiting" }) })
transportState = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.ok(!transportState.parent_sessions.some((x) => x.session_id === "ses-wait"), "wait-owner must immediately unenroll V2 heartbeat")
fs.writeFileSync(path.join(runRoot, "parent-loop.json"), JSON.stringify({ format: "tbag-parent-loop-v1" }))
const resumeCommand = `python3 TBag/tools/parent_tick.py resume-owner --run-root "${runRoot}" --question-id q1`
await after({ tool: "bash", sessionID: "ses-wait", status: "completed", input: { command: resumeCommand }, result: JSON.stringify({ format: "tbag-parent-loop-v1", run_status: "active", classification: "owner-question-closed", heartbeat_state: "running" }) })
transportState = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.ok(transportState.parent_sessions.some((x) => x.session_id === "ses-wait"), "resume-owner must re-enroll V2 heartbeat")

// New launch activity clears stale idle-recovery even if a later tick packet is
// filtered away from the adapter.
await after({ tool: "bash", sessionID: "ses-wait", status: "completed", input: { command: tickCommand }, result: JSON.stringify({ format: "tbag-parent-loop-v1", run_status: "active", classification: "active-idle", heartbeat_state: "idle-recovery" }) })
transportState = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.equal(transportState.parent_sessions.find((x) => x.session_id === "ses-wait")?.heartbeat_state, "idle-recovery")
await before({ tool: "bash", sessionID: "ses-wait", input: { command: launchCommand("PROMOTE") } })
transportState = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.equal(transportState.parent_sessions.find((x) => x.session_id === "ses-wait")?.heartbeat_state, "running", "V2 launch must clear stale idle-recovery")

// Mangled launch output is a degraded acceleration path, not a liveness failure.
const promptsBeforeMangled = prompts.length
await before({ tool: "bash", sessionID: "ses-mangled", input: { command: launchCommand("MANGLED") } })
await after({ tool: "bash", sessionID: "ses-mangled", status: "completed", input: { command: launchCommand("MANGLED") }, result: "human-readable summary without structured launch JSON" })
await tick(); await tick()
assert.equal(prompts.length, promptsBeforeMangled + 1, "V2 mangled launch output must queue one bounded reconciliation wake")
assert.match(prompts.at(-1).text, /health heartbeat/)
prompts.length = 0

// Current V2 lifecycle: execution.started marks busy; completion coalesces until
// execution.succeeded releases the same parent session.
await before({ tool: "bash", sessionID: "ses-v2", input: { command: launchCommand("T1") } })
events.push({ type: "session.execution.started", data: { sessionID: "ses-v2" } })
await tick()
await after({ tool: "bash", sessionID: "ses-v2", status: "completed", input: { command: launchCommand("T1") }, result: JSON.stringify(launchResult("T1")) })
assert.equal(observers.length, 1)
observers[0].resolve()
await tick()
assert.equal(prompts.length, 0)
events.push({ type: "session.execution.succeeded", data: { sessionID: "ses-v2" } })
await tick(); await tick()
assert.equal(prompts.length, 1)
assert.match(prompts[0].text, /T-BAG completion wake/)
assert.match(prompts[0].text, /parent_tick\.py tick/)

// If ctx.event.subscribe silently delivers nothing, T-BAG tool hooks do not
// manufacture a permanent busy bit. Observer completion still wakes the parent.
await before({ tool: "bash", sessionID: "ses-no-events", input: { command: launchCommand("T2") } })
await after({ tool: "bash", sessionID: "ses-no-events", status: "completed", input: { command: launchCommand("T2") }, result: JSON.stringify(launchResult("T2")) })
observers.at(-1).resolve()
await tick(); await tick()
assert.equal(prompts.length, 2, "observer completion must wake when V2 event delivery is silent")

// Durable Human wait suppresses a late wake and removes the run registration.
fs.writeFileSync(path.join(runRoot, "run.json"), JSON.stringify({ status: "active" }))
await before({ tool: "bash", sessionID: "ses-quiet", input: { command: launchCommand("TQ") } })
await after({ tool: "bash", sessionID: "ses-quiet", status: "completed", input: { command: launchCommand("TQ") }, result: JSON.stringify(launchResult("TQ")) })
fs.writeFileSync(path.join(runRoot, "run.json"), JSON.stringify({ status: "human-blocked" }))
const beforeQuiet = prompts.length
observers.at(-1).resolve()
await tick(); await tick()
assert.equal(prompts.length, beforeQuiet)
const registry = JSON.parse(fs.readFileSync(path.join(runRoot, ".transport", "opencode.json"), "utf8"))
assert.ok(!registry.parent_sessions.some((x) => x.session_id === "ses-quiet"), "quiescent run must be unenrolled")

events.close()
cleanup()
fs.rmSync(tmp, { recursive: true, force: true })
console.log("OPENCODE_V2_PLUGIN_RUNTIME_PASS")
