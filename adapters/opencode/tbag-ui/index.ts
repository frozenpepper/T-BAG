import type { Plugin } from "@opencode/plugin"

// T-BAG OpenCode 2 server-side entry. The import is type-only on purpose: it
// is erased before execution, so the server loader never has to resolve the
// bare "@opencode/plugin" specifier. Plugin.define is an identity helper at
// runtime, so a plain typed object avoids a server-side dependency entirely.
const plugin: Plugin.Plugin = {
  id: "tbag.status.server",
  setup() {
    // Presentation companion only. The existing tbag.js adapter retains all
    // transport/tool hooks; semantic authority remains in the Python control plane.
  },
}

export default plugin
