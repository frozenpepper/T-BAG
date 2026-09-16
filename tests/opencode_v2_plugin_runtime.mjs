import assert from "node:assert/strict"
import { pathToFileURL } from "node:url"

const pluginPath = process.argv[2]
assert.ok(pluginPath, "plugin path required")
const mod = await import(pathToFileURL(pluginPath).href + `?rc56=${Date.now()}`)
const plugin = mod.default
assert.equal(plugin.id, "tbag.transport")
assert.equal(typeof plugin.setup, "function")

const toolHooks = new Map()
const sessionHooks = new Map()
let subscribed = false
const registration = { dispose: async () => {} }
const ctx = {
  location: { directory: process.cwd(), project: { canonical: process.cwd() } },
  tool: {
    hook: async (name, fn) => { toolHooks.set(name, fn); return registration },
  },
  session: {
    hook: async (name, fn) => { sessionHooks.set(name, fn); return registration },
    prompt: async () => ({}),
  },
  event: {
    subscribe() {
      subscribed = true
      return { async *[Symbol.asyncIterator]() {} }
    },
  },
}
const cleanup = await plugin.setup(ctx)
assert.equal(typeof cleanup, "function")
assert.equal(typeof toolHooks.get("execute.before"), "function")
assert.equal(typeof toolHooks.get("execute.after"), "function")
assert.equal(typeof sessionHooks.get("compaction"), "function")
await toolHooks.get("execute.before")({ tool: "read", sessionID: "ses-test", input: {} })
await toolHooks.get("execute.after")({ tool: "read", sessionID: "ses-test", status: "completed", input: {}, result: { content: "ok" } })
await new Promise((resolve) => setImmediate(resolve))
assert.equal(subscribed, true)
cleanup()
console.log("OPENCODE_V2_PLUGIN_RUNTIME_PASS")
