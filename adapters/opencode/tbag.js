import { tool } from "@opencode-ai/plugin"

// OpenCode owns wake delivery; T-BAG durable task/run files own orchestration truth.
// This adapter keeps only disposable per-session/per-attempt transport state.
const follows = new Set()
const busySessions = new Set()
const pendingWakeSessions = new Set()
const wakeInflightSessions = new Set()
const deletedSessions = new Set()

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
  checkedSync(attemptCli(root, args, "inspect"), "Refusing invalid T-BAG attempt target")
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
          "Run reconcile-run now, process only authorized lifecycle actions, refill free slots, and call tbag_follow for every live attempt before yielding again.",
          "For each new attempt: run the normal detached core dsd_attempt.py launch, immediately call tbag_follow with the exact returned run_root/phase_id/task_id/event_dir, then yield when no immediate lifecycle action remains.",
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
  if (follows.has(key)) {
    return { armed: true, already_armed: true, task_id: args.task_id, event_dir: args.event_dir }
  }
  if (validate) validateAttempt(root, args)

  const proc = spawnObserver(root, args)
  follows.add(key)
  void (async () => {
    try {
      await proc.exited
    } catch (error) {
      await logError(client, "T-BAG attempt observer failed; waking parent to reconcile", {
        task_id: args.task_id,
        event_dir: args.event_dir,
        error: String(error?.stack || error),
      })
    } finally {
      // Delete before waking so a deadline/error wake can re-arm the same still-live
      // attempt during the resumed parent turn.
      follows.delete(key)
      queueWake(client, sessionID)
    }
  })()

  return { armed: true, already_armed: false, task_id: args.task_id, event_dir: args.event_dir }
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

const TBagPlugin = async (ctx) => ({
  tool: {
    tbag_follow: tool({
      description: "OpenCode T-BAG wake-arm primitive. Validate and observe exactly one already-launched recorded attempt, return immediately, and wake this same parent session when the observer exits. After every detached core launch, call this immediately with the exact returned run_root, phase_id, task_id, and event_dir; call it again to re-arm live attempts after resume/deadline/plugin restart. Idempotent for an already-armed exact attempt.",
      args: followArgs,
      async execute(args, context) {
        const sessionID = context.sessionID
        const root = context.worktree || context.directory || ctx.worktree || ctx.directory
        deletedSessions.delete(sessionID)
        busySessions.add(sessionID)
        const observer = armAttempt(ctx.client, sessionID, root, args)
        return JSON.stringify({ ...observer, semantics: "per-attempt wake observation only; durable T-BAG state remains authoritative" })
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
  // forbidden because it can monopolize the conversational turn; tbag_follow runs
  // that same observer detached from the parent tool call.
  "tool.execute.before": async (input, output) => {
    if (input.tool !== "bash") return
    const command = String(output?.args?.command || "")
    if (isCoreAttemptCommand(command, "follow")) {
      throw new Error("OpenCode T-BAG parents must use non-blocking tbag_follow; Bash/Python dsd_attempt.py follow is forbidden")
    }
  },

  // Safety net only: a current adapter auto-arms an observer after a successful
  // direct core launch. The documented parent protocol STILL calls tbag_follow
  // immediately; that call is idempotent and keeps older follow-only adapters safe.
  "tool.execute.after": async (input, output) => {
    if (input.tool !== "bash" || !isCoreAttemptCommand(input?.args?.command, "launch")) return
    const launch = launchResultFromToolOutput(output)
    if (!launch) {
      await logError(ctx.client, "T-BAG launch completed but adapter could not prove its structured launch result; parent must call tbag_follow from the returned launch fields")
      return
    }
    const sessionID = input.sessionID
    const root = ctx.worktree || ctx.directory
    if (!sessionID || !root) return
    deletedSessions.delete(sessionID)
    busySessions.add(sessionID)
    try {
      armAttempt(ctx.client, sessionID, root, launch)
    } catch (error) {
      // Never convert a successful detached launch into a failed tool result. The
      // stable parent protocol's immediate tbag_follow call is the recovery path.
      await logError(ctx.client, "T-BAG launch observer safety auto-arm failed; parent tbag_follow remains required", {
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
    output.context.push(`\n## T-BAG durable continuation\n${text}\nOpenCode invariant: for every new attempt run the normal detached core dsd_attempt.py launch, immediately call tbag_follow with the exact returned run_root/phase_id/task_id/event_dir, and use the same tbag_follow call to re-arm every live attempt after resume/wake. Never run core follow or wait/poll in the conversational turn. Once every live attempt is observed and no immediate lifecycle action remains, end the routine turn so lifecycle wakes can resume orchestration.\n`)
  },
})

// Exactly one plugin export. OpenCode loads every function export from a legacy
// plugin module, so exporting the same function under multiple names duplicates hooks.
export default TBagPlugin
