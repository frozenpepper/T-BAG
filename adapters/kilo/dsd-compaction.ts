import type { Plugin } from "@kilocode/plugin"
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"

function markActivation(root: string) {
  try {
    const request=JSON.parse(readFileSync(`${root}/.kilo/tbag-activation.json`,"utf8"))
    if (!request?.token) return
    const dir=`${root}/TBag/harness`; const path=`${dir}/kilo-activation.json`; const tmp=`${path}.tmp-${process.pid}`
    mkdirSync(dir,{recursive:true})
    writeFileSync(tmp,JSON.stringify({format:"tbag-kilo-activation-v1",token:request.token,adapter_pid:process.pid,activated_at:new Date().toISOString()},null,2)+"\n")
    renameSync(tmp,path)
  } catch (_) {}
}

const server: Plugin = async (ctx) => {
  const root = process.env.TBAG_PROJECT_ROOT || ctx.worktree || ctx.directory
  markActivation(root)
  return ({
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
}

export default { id: "t-bag-compaction", server }
