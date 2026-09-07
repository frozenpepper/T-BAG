import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"

const source = path.resolve(process.argv[2])
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "tbag-opencode-plugin-test-"))
fs.writeFileSync(path.join(tmp, "package.json"), JSON.stringify({ type: "module" }))
const pkg = path.join(tmp, "node_modules", "@opencode-ai", "plugin")
fs.mkdirSync(pkg, { recursive: true })
fs.writeFileSync(path.join(pkg, "package.json"), JSON.stringify({ type: "module", exports: "./index.js" }))
fs.writeFileSync(path.join(pkg, "index.js"), `
const scalar = () => ({ describe(){ return this }, optional(){ return this } })
export const tool = Object.assign((definition) => definition, {
  schema: {
    string: scalar,
    number: scalar,
    boolean: scalar,
    array: () => scalar(),
  },
})
`)
const pluginCopy = path.join(tmp, "tbag.js")
fs.copyFileSync(source, pluginCopy)

const encoder = new TextEncoder()
const syncCalls = []
const spawnCalls = []
const observers = []
let failNextObserverSpawn = false

function deferredObserver(argv) {
  let resolve
  let reject
  const exited = new Promise((res, rej) => { resolve = res; reject = rej })
  const item = { argv: [...argv], exited, resolve, reject }
  observers.push(item)
  return item
}

globalThis.Bun = {
  spawnSync(argv) {
    syncCalls.push([...argv])
    const command = argv[2]
    if (command === "inspect") {
      return { exitCode: 0, stdout: encoder.encode('{"state":"running"}'), stderr: encoder.encode("") }
    }
    if (argv.some((part) => String(part).includes("context_checkpoint.py"))) {
      return { exitCode: 4, stdout: encoder.encode(""), stderr: encoder.encode("") }
    }
    throw new Error(`unexpected spawnSync: ${argv.join(" ")}`)
  },
  spawn(argv) {
    spawnCalls.push([...argv])
    if (failNextObserverSpawn) {
      failNextObserverSpawn = false
      throw new Error("synthetic observer spawn failure")
    }
    return deferredObserver(argv)
  },
}

const prompts = []
const logs = []
const heldPromptSessions = new Map()
const failPromptSessions = new Set()

function holdPromptFor(sessionID) {
  let resolve
  const promise = new Promise((res) => { resolve = res })
  heldPromptSessions.set(sessionID, { promise, resolve })
}
function releaseHeldPrompt(sessionID) {
  const item = heldPromptSessions.get(sessionID)
  heldPromptSessions.delete(sessionID)
  item?.resolve({})
}

const client = {
  session: { prompt: async (request) => {
    prompts.push(request)
    const sessionID = request.path.id
    if (failPromptSessions.delete(sessionID)) throw new Error("synthetic wake submission failure")
    const held = heldPromptSessions.get(sessionID)
    if (held) return held.promise
    return {}
  } },
  app: { log: async (request) => { logs.push(request); return {} } },
}
const ctx = { client, directory: "/project", worktree: "/project" }
const module = await import(pathToFileURL(pluginCopy).href)
assert.deepEqual(Object.keys(module), ["default"], "adapter must export exactly one plugin function")
assert.equal(typeof module.default, "function")
const plugin = await module.default(ctx)
assert.deepEqual(Object.keys(plugin.tool), ["tbag_follow"], "tbag_follow is the only stable custom tool")
const context = { sessionID: "ses-main", directory: "/project", worktree: "/project" }
const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

function launchPayload(task, suffix = task) {
  return {
    status: "started",
    run_root: "/run",
    phase_id: "P",
    task_id: task,
    role: "implementer",
    event_dir: `/run/attempts/${suffix}`,
  }
}
function launchHookInput(sessionID, task) {
  return {
    tool: "bash",
    sessionID,
    callID: `call-${task}`,
    args: { command: `python3 TBag/tools/dsd_attempt.py launch --run-root /run --phase-id P --task-id ${task}` },
  }
}
function toolOutput(payload) {
  return { title: "bash", output: JSON.stringify(payload), metadata: {} }
}

// Current adapter safety hook auto-arms a successful normal core launch.
const first = launchPayload("T1")
await plugin["tool.execute.after"](launchHookInput("ses-main", "T1"), toolOutput(first))
assert.equal(spawnCalls.filter((x) => x[2] === "follow").length, 1)
assert.equal(syncCalls.filter((x) => x[2] === "inspect").length, 1, "safety auto-arm must validate the recorded launch before observing it")
assert.ok(!spawnCalls[0].includes("--timeout"), "adapter must preserve core role-aware timeout")

// Parent always performs the stable explicit follow step. On a current adapter it
// is idempotent and must not spawn/inspect a second observer for the exact tuple.
const explicit = JSON.parse(await plugin.tool.tbag_follow.execute(first, context))
assert.equal(explicit.armed, true)
assert.equal(explicit.already_armed, true)
assert.equal(spawnCalls.filter((x) => x[2] === "follow").length, 1)
assert.equal(syncCalls.filter((x) => x[2] === "inspect").length, 1, "explicit follow should be cheap when exact attempt is already armed")

// Completion while parent is busy stays coalesced until host idle, then wakes once.
observers[0].resolve(0)
await tick()
assert.equal(prompts.length, 0)
await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses-main" } } })
await tick()
assert.equal(prompts.length, 1)
assert.match(prompts[0].body.parts[0].text, /reconcile-run/)
assert.match(prompts[0].body.parts[0].text, /tbag_follow/)
assert.doesNotMatch(prompts[0].body.parts[0].text, /tbag_launch/)

// Follow-only compatibility: without any auto-arm hook, tbag_follow alone validates
// and arms the already-launched attempt. This is the older-adapter common denominator.
const legacy = launchPayload("TLEGACY")
const legacyResult = JSON.parse(await plugin.tool.tbag_follow.execute(legacy, { ...context, sessionID: "ses-legacy" }))
assert.equal(legacyResult.already_armed, false)
assert.equal(syncCalls.filter((x) => x[2] === "inspect").length, 2)
assert.equal(spawnCalls.filter((x) => x[2] === "follow").length, 2)

// Auto-arm failure never turns a successful detached launch into a tool failure;
// the stable explicit tbag_follow step recovers it.
failNextObserverSpawn = true
const partial = launchPayload("T2")
await plugin["tool.execute.after"](launchHookInput("ses-partial", "T2"), toolOutput(partial))
assert.ok(logs.some((x) => String(x?.body?.message || "").includes("auto-arm failed")))
const recovered = JSON.parse(await plugin.tool.tbag_follow.execute(partial, { ...context, sessionID: "ses-partial" }))
assert.equal(recovered.already_armed, false)

// Observer B can finish while observer A's wake-generated parent turn is still in
// flight. Releasing A must flush B without waiting for a third external event.
const chain = launchPayload("TCHAIN")
await plugin["tool.execute.after"](launchHookInput("ses-chain", "TCHAIN"), toolOutput(chain))
const chainObserverA = observers.at(-1)
await plugin.tool.tbag_follow.execute(chain, { ...context, sessionID: "ses-chain" })
chainObserverA.resolve(0)
await tick()
holdPromptFor("ses-chain")
const chainPromptsBefore = prompts.length
await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses-chain" } } })
await tick()
assert.equal(prompts.length, chainPromptsBefore + 1)
const chainRearm = JSON.parse(await plugin.tool.tbag_follow.execute(chain, { ...context, sessionID: "ses-chain" }))
assert.equal(chainRearm.already_armed, false)
const chainObserverB = observers.at(-1)
chainObserverB.resolve(0)
await tick()
await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses-chain" } } })
await tick()
assert.equal(prompts.length, chainPromptsBefore + 1, "second wake stays coalesced while first is in flight")
releaseHeldPrompt("ses-chain")
await tick(); await tick()
assert.equal(prompts.length, chainPromptsBefore + 2, "pending wake flushes after successful first wake releases")

// Wake submission failure must not recursively self-spin. A later host lifecycle
// transition gets one normal retry and durable reconcile remains the fallback.
const wakeFail = launchPayload("TWAKEFAIL")
await plugin.tool.tbag_follow.execute(wakeFail, { ...context, sessionID: "ses-wakefail" })
const wakeFailObserver = observers.at(-1)
wakeFailObserver.resolve(0)
await tick()
failPromptSessions.add("ses-wakefail")
const wakeFailBefore = prompts.length
await plugin.event({ event: { type: "session.idle", properties: { sessionID: "ses-wakefail" } } })
await tick(); await tick()
assert.equal(prompts.length, wakeFailBefore + 1, "failed wake must not immediate-retry-loop")
await plugin.event({ event: { type: "session.status", properties: { sessionID: "ses-wakefail", status: { type: "idle" } } } })
await tick()
assert.equal(prompts.length, wakeFailBefore + 2, "later host transition may retry the disposable wake")

// Current OpenCode session.deleted payload carries the deleted session under info.id.
// Late observer completion must not attempt to wake that deleted parent.
const doomed = launchPayload("TDELETE")
await plugin.tool.tbag_follow.execute(doomed, { ...context, sessionID: "ses-delete" })
const doomedObserver = observers.at(-1)
await plugin.event({ event: { type: "session.deleted", properties: { info: { id: "ses-delete" } } } })
const deletePromptsBefore = prompts.length
doomedObserver.resolve(0)
await tick(); await tick()
assert.equal(prompts.length, deletePromptsBefore)

// Direct normal core launch is legal; only foreground core follow is blocked.
await plugin["tool.execute.before"](
  { tool: "bash", sessionID: "ses-main", callID: "launch-ok" },
  { args: { command: 'python3 "TBag/tools/dsd_attempt.py" launch --run-root /run --phase-id P --task-id T3' } },
)
await assert.rejects(
  () => plugin["tool.execute.before"](
    { tool: "bash", sessionID: "ses-main", callID: "follow-bad" },
    { args: { command: "python3 'TBag/tools/dsd_attempt.py' follow --run-root /run --phase-id P --task-id T1" } },
  ),
  /tbag_follow/,
)

fs.rmSync(tmp, { recursive: true, force: true })
console.log("OPENCODE_PLUGIN_RUNTIME_PASS")
