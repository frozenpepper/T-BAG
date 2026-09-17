import { Plugin } from "@opencode/plugin/tui"
import { For, Show, createSignal } from "solid-js"

declare const Bun: any

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

function truncate(text: unknown, max = 76) {
  const s = String(text ?? "")
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

function statusColor(status: unknown) {
  const s = String(status ?? "").toLowerCase()
  if (s === "active") return "#4ade80"
  if (s === "completed") return "#38bdf8"
  if (s === "human-blocked" || s === "paused-by-user") return "#facc15"
  return "#9ca3af"
}

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
const PULSE = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█", "▇", "▆", "▅", "▄", "▃", "▂"]

function waveBar(pct: number, width: number, frame: number) {
  const filled = Math.round((clampPercent(pct) / 100) * width)
  const head = ((frame % width) + width) % width
  return Array.from({ length: width }, (_, i) => {
    const ch = i < filled ? "█" : "░"
    return <span style={i === head ? { fg: "#a7f3d0" } : undefined}>{ch}</span>
  })
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

function Worker(props: { worker: any; index: number }) {
  const w = () => props.worker
  const glyph = w().tier === "analyst" ? "◆" : "●"
  const glyphColor = w().tier === "analyst" ? "#38bdf8" : "#4ade80"
  return (
    <box flexDirection="column" marginBottom={1}>
      <text>{`[${props.index + 1}] `}<span style={{ fg: glyphColor }}>{glyph}</span>{` ${w().authority ?? "Worker"} · ${w().role ?? "?"} · ${duration(w().elapsed_seconds)}`}</text>
      <text>{`    ${w().task_id ?? "?"} · ${truncate(w().objective, 72)}`}</text>
      <text>{`    ${String(w().model ?? "unknown model")} · ${shortSession(w().session?.id)} · ${workerHealth(w())}`}</text>
      <text>{`    CPU ${w().process?.worker?.cpu_percent ?? "?"}% / ${duration(w().process?.worker?.cpu_seconds)} · log ${duration(w().log_age_seconds)} ago · report ${duration(w().report_age_seconds)} ago`}</text>
      <Show when={w().deadline?.exceeded || w().deadline_exceeded}>
        <text><span style={{ fg: "#f87171" }}>{`    ⚠ role deadline exceeded${w().deadline?.overrun_seconds ? ` by ${duration(w().deadline.overrun_seconds)}` : ""}`}</span></text>
      </Show>
    </box>
  )
}

function Dashboard(props: { snapshot: Snapshot | null; panel: any; frame: number }) {
  // Presentational only. Keymap layers are component-owned; the verified
  // global T-BAG layer is registered from the footer render below, where the
  // host provides keymap context. The panel subtree's provider coverage is not
  // proven, so per-panel f/escape bindings are deliberately not registered here.
  const s = () => props.snapshot
  return (
    <box flexDirection="column" padding={1}>
      <Show when={s()} fallback={<text>T-BAG status unavailable for this session.</text>}>
        <text><span style={{ fg: "#4ade80" }}>{PULSE[props.frame % PULSE.length]}</span>{` T-BAG · ${s()?.run?.id ?? "run"} · `}<span style={{ fg: statusColor(s()?.run?.status) }}>{String(s()?.run?.status ?? "unknown").toUpperCase()}</span></text>
        <text>{waveBar(s()?.progress?.registered_percent ?? 0, 30, props.frame)}{` ${s()?.progress?.registered_percent ?? 0}% (${s()?.progress?.registered_done ?? 0}/${s()?.progress?.registered_total ?? 0})`}</text>
        <text>{`Phases ${s()?.progress?.phases_done ?? 0}/${s()?.progress?.phases_total ?? 0} · slots ${s()?.worker_budget?.live ?? 0}/${s()?.worker_budget?.max ?? 0} · ${s()?.run?.parent_loop ?? "no tick yet"}`}</text>
        <Show when={s()?.current_phase}>
          <text>{`Current: ${s()?.current_phase?.phase_id} · ${s()?.current_phase?.percent ?? 0}% · gate ${s()?.current_phase?.gate?.result ?? "pending"}`}</text>
          <text>{waveBar(s()?.current_phase?.percent ?? 0, 30, props.frame)}{` ${s()?.current_phase?.percent ?? 0}%`}</text>
        </Show>
        <text> </text>
        <text>{`ACTIVE SESSIONS · Analysts ${s()?.analysts_active?.length ?? 0} · Grunts ${s()?.grunts_active?.length ?? 0}`}</text>
        <Show when={(s()?.workers?.length ?? 0) > 0} fallback={<text>  No active workers.</text>}>
          <For each={s()?.workers ?? []}>{(worker, index) => <Worker worker={worker} index={index()} />}</For>
        </Show>
        <Show when={(s()?.attention?.length ?? 0) > 0}>
          <text><span style={{ fg: "#f87171" }}>{`ATTENTION · ${s()?.attention?.length ?? 0}`}</span></text>
          <For each={(s()?.attention ?? []).slice(0, 8)}>{(item: any) => <text><span style={{ fg: "#f87171" }}>{`⚠ ${item.phase_id ?? ""}/${item.task_id ?? ""} · ${item.status ?? "attention"} · ${truncate(item.objective, 64)}`}</span></text>}</For>
        </Show>
        <text> </text>
        <text>PHASES</text>
        <For each={s()?.phases ?? []}>{(phase: any) => <text>{phase.complete ? <span style={{ fg: "#4ade80" }}>{"✓"}</span> : "○"}{` ${phase.phase_id}  ${progressBar(phase.percent, 12)} ${phase.percent}%  gate:${phase.gate?.result ?? "—"}`}</text>}</For>
        <text> </text>
        <text>reopen via palette or /tbag</text>
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
        const tool = `${projectRoot}/TBag/tools/tbag_status.py`
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
    ;(timer as unknown as { unref?: () => void }).unref?.()
    queueMicrotask(refreshCurrent)

    // Animation clock. Slot renders read frame() (footer spinner, panel wave
    // bar and pulse), so every host re-render advances the motion. Cheap:
    // one tiny signal, cleared with everything else on dispose.
    const [frame, setFrame] = createSignal(0)
    const clock = setInterval(() => setFrame((f) => (f + 1) % 100000), 500)
    ;(clock as unknown as { unref?: () => void }).unref?.()

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
        // Keymap layers are owned by the calling component: this render runs
        // under the host's Keymap provider, while setup() does not, so the
        // global command must be layered here. Calling context.keymap.layer
        // in setup() fails plugin load with "Keymap provider is missing".
        // The footer renders on every screen, keeping the command available.
        context.keymap.layer(() => ({
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
        }))
        const sessionID = currentSessionID()
        const s = snapshot(sessionID)
        if (!s) return null
        const f = frame()
        const live = (s.worker_budget?.live ?? 0) > 0
        const spin = live ? SPINNER[f % SPINNER.length] : "●"
        const warn = s.attention?.length ? ` · ⚠${s.attention.length}` : ""
        return <text><span style={{ fg: live ? "#4ade80" : "#9ca3af" }}>{spin}</span>{` T-BAG ${String(s.run?.status ?? "?").toUpperCase()} · ${s.current_phase?.phase_id ?? "—"} · ${progressBar(s.progress?.registered_percent, 8)} ${s.progress?.registered_percent ?? 0}% · A${s.analysts_active?.length ?? 0}/G${s.grunts_active?.length ?? 0}${warn}`}</text>
      },
    }))

    keep(context.ui.slot({
      append: "sidebar.content",
      render: ({ sessionID }: any) => {
        const s = snapshot(sessionID)
        if (!s) return null
        const f = frame()
        const live = (s.worker_budget?.live ?? 0) > 0
        const spin = live ? SPINNER[f % SPINNER.length] : "●"
        return (
          <box flexDirection="column" marginTop={1}>
            <text><span style={{ fg: live ? "#4ade80" : "#9ca3af" }}>{spin}</span>{` T-BAG · ${s.progress?.registered_percent ?? 0}% · ${s.worker_budget?.live ?? 0}/${s.worker_budget?.max ?? 0} workers`}</text>
            <text>{`${progressBar(s.progress?.registered_percent, 14)} ${s.progress?.registered_percent ?? 0}%`}</text>
            <text>{`${s.current_phase?.phase_id ?? "—"} · gate ${s.current_phase?.gate?.result ?? "—"}`}</text>
            <For each={(s.workers ?? []).slice(0, 4)}>{(worker: any) => <text>{`${worker.tier === "analyst" ? "◆" : "●"} ${worker.task_id} ${worker.role} ${duration(worker.elapsed_seconds)}`}</text>}</For>
            <Show when={(s.attention?.length ?? 0) > 0}><text><span style={{ fg: "#f87171" }}>{`⚠ ${s.attention.length} item${s.attention.length === 1 ? "" : "s"} need attention`}</span></text></Show>
            <text>/tbag for details</text>
          </box>
        )
      },
    }))

    keep(context.ui.slot({
      append: "session.panel",
      render: (panel: any) => (
        <Show when={panel.name === "tbag.status"}>
          <Dashboard snapshot={snapshot(panel.sessionID)} panel={panel} frame={frame()} />
        </Show>
      ),
    }))

    return () => {
      clearInterval(timer)
      clearInterval(clock)
      stopEvents?.()
      for (const dispose of disposers.reverse()) dispose()
    }
  },
})
