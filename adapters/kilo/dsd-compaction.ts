import type { Plugin } from "@kilocode/plugin"

const server: Plugin = async (ctx) => ({
  "experimental.session.compacting": async (_input, output) => {
    const root = process.env.TBAG_PROJECT_ROOT || ctx.worktree || ctx.directory
    const script = `${root}/TBag/tools/context_checkpoint.py`
    const result = Bun.spawnSync(["python3", script, "--project-root", root, "instruction"], { stdout: "pipe", stderr: "pipe" })
    if (result.exitCode === 4) return
    if (result.exitCode !== 0) {
      const stderr = new TextDecoder().decode(result.stderr).trim()
      output.context.push(`\n## T-BAG continuity warning\n${stderr}\nDo not assume resume orientation is safe.\n`)
      return
    }
    const text = new TextDecoder().decode(result.stdout).trim()
    output.context.push(`\n## T-BAG durable continuation\n${text}\n`)
  },
})

export default { id: "t-bag-compaction", server }
