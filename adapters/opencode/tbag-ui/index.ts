import { Plugin } from "@opencode/plugin"

export default Plugin.define({
  id: "tbag.status.server",
  setup() {
    // Presentation companion only. The existing tbag.js adapter retains all
    // transport/tool hooks; semantic authority remains in the Python control plane.
  },
})
