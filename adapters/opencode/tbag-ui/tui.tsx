import { Plugin, usePlugin } from "@opencode/plugin/tui"
import { For, Show, createSignal } from "solid-js"
import path from "node:path"

const REFRESH_MS = 5000

type Snapshot = Record<string, any>

function clampPercent(value: unknown) {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0
}

function progressBar(value: unknown, width = 16) {
  const pct = clampPercent(value)
  const filled = Math.round((pct / 100) * width)
  return `${"█".repeat(filled)}${"░".repeat(Math.max(0, width - filled))}`
}

function shortSession(value: unknown) {
  const text = String(value ?? "")
  return text ? (text.length > 12 ? `${text.slice(0, 9)}…` : text) : "no-session"
}

function duration(seconds: unknown) {
  const raw = Number(seconds ?? 0)
  if (!Number.isFinite(raw) || raw < 0) return "?"
  const whole = Math.floor(raw)
  const h = Math.floor(whole / 3600)
  const m = Math.floor((whole % 3600) / 60)
  const s = whole % 60
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`
}

function workerHealth(worker: any) {
  const processAlive = Boolean(worker?.process?.worker?.alive ?? worker?.process_alive ?? worker?.state === "running")
  const observer = worker?.observer?.healthy
  const attention = worker?.attention
  if (attention) return `⚠ ${attention}`
  if (!processAlive) return "○ process down"
  if (worker?.observer?.known === false) return "● process alive"
  if (!observer) return "◐ observer missing"
  return "● healthy"
}

function Worker(props: { worker: any }) {
  const w = () => props.worker
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>{`${w().tier === "analyst" ? "◆" : "●"} ${w().authority ?? "Worker"} · ${w().role ?? "?"} · ${duration(w().elapsed_seconds)}`}</text>
      <text>{`  ${w().task_id ?? "?"} · ${w().objective ?? ""}`}</text>
      <text>{`  ${String(w().model ?? "unknown model")} · ${shortSession(w().session?.id)} · ${workerHealth(w())}`}</text>
      <text>{`  CPU ${w().process?.worker?.cpu_percent ?? "?"}% / ${duration(w().process?.worker?.cpu_seconds)} · log ${duration(w().log_age_seconds)} ago · report ${duration(w().report_age_seconds)} ago`}</text>
      <Show when={w().deadline?.exceeded || w().deadline_exceeded}>
        <text>{`  ⚠ role deadline exceeded${w().deadline?.overrun_seconds ? ` by ${duration(w().deadline.overrun_seconds)}` : ""}`}</text>
      </Show>
    </box>
  )
}

function Dashboard(props: { snapshot: Snapshot | null; panel: any }) {
  const context = usePlugin()
  context.keymap.layer(() => ({
    commands: [
      { id: "tbag.status.fullscreen", bind: "f", run: props.panel.toggleFullscreen },
      { id: "tbag.status.close", bind: "escape", run: props.panel.close },
    ],
  }))
  const s = () => props.snapshot
  return (
    <box flexDirection="column" padding={1}>
      <Show when={s()} fallback={<text>T-BAG status unavailable for this session.</text>}>
        <text>{`T-BAG · ${s()?.run?.id ?? "run"} · ${String(s()?.run?.status ?? "unknown").toUpperCase()}`}</text>
        <text>{`${progressBar(s()?.progress?.registered_percent, 22)} ${s()?.progress?.registered_percent ?? 0}% registered work · ${s()?.progress?.registered_done ?? 0}/${s()?.progress?.registered_total ?? 0}`}</text>
        <text>{`Phases ${s()?.progress?.phases_done ?? 0}/${s()?.progress?.phases_total ?? 0} · slots ${s()?.worker_budget?.live ?? 0}/${s()?.worker_budget?.max ?? 0} · ${s()?.run?.parent_loop ?? "no tick yet"}`}</text>
        <Show when={s()?.current_phase}>
          <text>{`Current phase: ${s()?.current_phase?.phase_id} · ${s()?.current_phase?.percent ?? 0}% · gate ${s()?.current_phase?.gate?.result ?? "pending"}`}</text>
        </Show>
        <text> </text>
        <text>{`ACTIVE SESSIONS · Analysts ${s()?.analysts_active?.length ?? 0} · Grunts ${s()?.grunts_active?.length ?? 0}`}</text>
        <Show when={(s()?.workers?.length ?? 0) > 0} fallback={<text>  No active workers.</text>}>
          <For each={s()?.workers ?? []}>{(worker) => <Worker worker={worker} />}</For>
        </Show>
        <Show when={(s()?.attention?.length ?? 0) > 0}>
          <text>ATTENTION</text>
          <For each={(s()?.attention ?? []).slice(0, 8)}>{(item: any) => <text>{`⚠ ${item.phase_id ?? ""}/${item.task_id ?? ""} · ${item.status ?? "attention"} · ${item.objective ?? ""}`}</text>}</For>
        </Show>
        <text> </text>
        <text>PHASES</text>
        <For each={s()?.phases ?? []}>{(phase: any) => <text>{`${phase.complete ? "✓" : "○"} ${phase.phase_id}  ${progressBar(phase.percent, 12)} ${phase.percent}%  gate:${phase.gate?.result ?? "—"}`}</text>}</For>
        <text> </text>
        <text>f fullscreen · esc close</text>
      </Show>
    </box>
  )
}

export default Plugin.define({
  id: "tbag.status.tui",
  setup(context) {
    const [snapshots, setSnapshots] = createSignal<Record<string, Snapshot>>({})
    const refreshing = new Set<string>()
    const projectRoot = (context.location ?? context.data.location.default())?.directory

    function currentSessionID() {
      const route: any = context.ui.router.current()
      return route?.type === "session" ? route.sessionID : undefined
    }

    function readSnapshot(sessionID: string) {
      if (!projectRoot || !sessionID || refreshing.has(sessionID)) return
      refreshing.add(sessionID)
      try {
        const tool = path.join(projectRoot, "TBag", "tools", "tbag_status.py")
        const result = Bun.spawnSync([
          "python3", tool,
          "--project-root", projectRoot,
          "--parent-session-id", sessionID,
        ], { stdout: "pipe", stderr: "pipe" })
        if (result.exitCode !== 0) return
        const text = new TextDecoder().decode(result.stdout || new Uint8Array()).trim()
        if (!text) return
        const value = JSON.parse(text)
        if (value?.format !== "tbag-status-v1") return
        setSnapshots((prior) => ({ ...prior, [sessionID]: value }))
      } catch (_) {
        // Presentation must never disturb the OpenCode session or T-BAG control plane.
      } finally {
        refreshing.delete(sessionID)
      }
    }

    function snapshot(sessionID?: string) {
      if (!sessionID) return null
      const current = snapshots()[sessionID] ?? null
      if (!current) queueMicrotask(() => readSnapshot(sessionID))
      return current
    }

    function refreshCurrent() {
      const sessionID = currentSessionID()
      if (sessionID) readSnapshot(sessionID)
    }

    const timer = setInterval(refreshCurrent, REFRESH_MS)
    timer.unref?.()
    queueMicrotask(refreshCurrent)

    const stopEvents = context.data.listen(() => {
      // Server/session events are cheap hints. The Python snapshot remains the only
      // interpretation of T-BAG task state.
      const sessionID = currentSessionID()
      if (sessionID) queueMicrotask(() => readSnapshot(sessionID))
    })

    const disposers: Array<() => void> = []
    const keep = (value: unknown) => { if (typeof value === "function") disposers.push(value as () => void) }

    keep(context.ui.slot({
      append: "prompt.footer.status",
      render: () => {
        const sessionID = currentSessionID()
        const s = snapshot(sessionID)
        if (!s) return null
        const warn = s.attention?.length ? ` · ⚠${s.attention.length}` : ""
        return <text>{`T-BAG ${String(s.run?.status ?? "?").toUpperCase()} · ${s.current_phase?.phase_id ?? "—"} · ${s.progress?.registered_percent ?? 0}% · A${s.analysts_active?.length ?? 0}/G${s.grunts_active?.length ?? 0}${warn}`}</text>
      },
    }))

    keep(context.ui.slot({
      append: "sidebar.content",
      render: ({ sessionID }: any) => {
        const s = snapshot(sessionID)
        if (!s) return null
        return (
          <box flexDirection="column" marginTop={1}>
            <text>{`T-BAG · ${s.progress?.registered_percent ?? 0}% · ${s.worker_budget?.live ?? 0}/${s.worker_budget?.max ?? 0} workers`}</text>
            <For each={(s.workers ?? []).slice(0, 4)}>{(worker: any) => <text>{`${worker.tier === "analyst" ? "◆" : "●"} ${worker.task_id} ${worker.role} ${duration(worker.elapsed_seconds)}`}</text>}</For>
            <Show when={(s.attention?.length ?? 0) > 0}><text>{`⚠ ${s.attention.length} item${s.attention.length === 1 ? "" : "s"} need attention`}</text></Show>
            <text>/tbag for details</text>
          </box>
        )
      },
    }))

    keep(context.ui.slot({
      append: "session.panel",
      render: (panel: any) => (
        <Show when={panel.name === "tbag.status"}>
          <Dashboard snapshot={snapshot(panel.sessionID)} panel={panel} />
        </Show>
      ),
    }))

    keep(context.keymap.layer(() => ({
      mode: "global",
      priority: 10,
      commands: [
        {
          id: "tbag.status",
          title: "T-BAG orchestration status",
          group: "T-BAG",
          palette: true,
          slash: { name: "tbag", aliases: ["tbag-status"] },
          enabled: () => Boolean(currentSessionID()),
          run: () => {
            const sessionID = currentSessionID()
            if (!sessionID) return
            readSnapshot(sessionID)
            context.ui.panel.open("tbag.status")
          },
        },
      ],
    })))

    return () => {
      clearInterval(timer)
      stopEvents?.()
      for (const dispose of disposers.reverse()) dispose()
    }
  },
})
