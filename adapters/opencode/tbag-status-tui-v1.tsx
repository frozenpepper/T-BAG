/** @jsxImportSource @opentui/solid */

import type { TuiPlugin, TuiPluginModule } from "@opencode-ai/plugin/tui"
import { For, Show, createSignal, onCleanup } from "solid-js"
import path from "node:path"

const REFRESH_MS = 5000
const ROUTE = "tbag"
const MODE = "tbag.status.v1"

type Snapshot = Record<string, any>

function clampPercent(value: unknown) {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0
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

function statusColor(status: unknown) {
  const value = String(status ?? "unknown").toLowerCase()
  if (value === "active" || value === "completed") return "green"
  if (value === "blocked" || value === "failed" || value === "recovery-required") return "red"
  return "yellow"
}

function SegmentedBar(props: { value: unknown; width?: number }) {
  const width = () => props.width ?? 16
  const filled = () => Math.round((clampPercent(props.value) / 100) * width())
  return (
    <text>
      <For each={Array.from({ length: width() })}>{(_, index) => <span fg={index() < filled() ? "green" : "gray"}>█</span>}</For>
    </text>
  )
}

function TierGlyph(props: { tier: unknown }) {
  return <span fg={props.tier === "analyst" ? "magenta" : "cyan"}>{props.tier === "analyst" ? "◆" : "●"}</span>
}

function workerHealth(worker: any) {
  const processAlive = Boolean(worker?.process?.worker?.alive ?? worker?.process_alive ?? worker?.state === "running")
  if (worker?.attention) return `⚠ ${worker.attention}`
  if (!processAlive) return "process down"
  if (worker?.observer?.known === false) return "process alive"
  if (!worker?.observer?.healthy) return "observer missing"
  return "healthy"
}

function Worker(props: { worker: any }) {
  const w = () => props.worker
  return (
    <box flexDirection="column" marginBottom={1}>
      <text><TierGlyph tier={w().tier} /> {`${w().authority ?? "Worker"} · ${w().role ?? "?"} · ${duration(w().elapsed_seconds)}`}</text>
      <text>{`  ${w().task_id ?? "?"} · ${w().objective ?? ""}`}</text>
      <text>{`  ${String(w().model ?? "unknown model")} · ${shortSession(w().session?.id)} · ${workerHealth(w())}`}</text>
      <Show when={w().deadline?.exceeded || w().deadline_exceeded}>
        <text fg="red">{`  ⚠ deadline exceeded${w().deadline?.overrun_seconds ? ` by ${duration(w().deadline.overrun_seconds)}` : ""}`}</text>
      </Show>
    </box>
  )
}

const tui: TuiPlugin = async (api) => {
  const [snapshots, setSnapshots] = createSignal<Record<string, Snapshot>>({})
  const refreshing = new Set<string>()
  const projectRoot = api.state.path.worktree || api.state.path.directory
  let lastSessionID: string | undefined

  function sessionFromRoute() {
    const route: any = api.route.current
    const value = route?.name === "session" ? route.params?.sessionID : route?.params?.sessionID
    if (value) lastSessionID = value
    return value || lastSessionID
  }

  function readSnapshot(sessionID?: string) {
    if (!projectRoot || !sessionID || refreshing.has(sessionID)) return
    refreshing.add(sessionID)
    try {
      const bun = (globalThis as any).Bun
      if (!bun?.spawnSync) return
      const tool = path.join(projectRoot, "TBag", "tools", "tbag_status.py")
      const result = bun.spawnSync([
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
      // Presentation must never disturb OpenCode or T-BAG control state.
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

  api.slots.register({
    name: "sidebar_content",
    render: (_context: any, props: { session_id?: string }) => {
      const sessionID = props.session_id
      if (sessionID) lastSessionID = sessionID
      const s = snapshot(sessionID)
      if (!s) return <text>T-BAG status unavailable.</text>
      return (
        <box flexDirection="column" marginTop={1}>
          <text>
            T-BAG <span fg={statusColor(s.run?.status)}>{String(s.run?.status ?? "?").toUpperCase()}</span>
            {` · ${s.progress?.registered_percent ?? 0}% · ${s.worker_budget?.live ?? 0}/${s.worker_budget?.max ?? 0}`}
          </text>
          <SegmentedBar value={s.progress?.registered_percent} width={12} />
          <For each={(s.workers ?? []).slice(0, 4)}>{(worker: any) => <text><TierGlyph tier={worker.tier} /> {`${worker.task_id} ${worker.role} ${duration(worker.elapsed_seconds)}`}</text>}</For>
          <Show when={(s.attention?.length ?? 0) > 0}><text fg="red">{`⚠ ${s.attention.length} item${s.attention.length === 1 ? "" : "s"} need attention`}</text></Show>
          <text>/tbag for details</text>
        </box>
      )
    },
  })

  api.route.register([
    {
      name: ROUTE,
      render: () => {
        const popMode = api.mode.push(MODE)
        onCleanup(popMode)
        const sessionID = sessionFromRoute()
        const s = snapshot(sessionID)
        return (
          <box flexDirection="column" padding={1}>
            <Show when={s} fallback={<text>T-BAG status unavailable for this session.</text>}>
              <text>
                T-BAG · <span fg={statusColor(s?.run?.status)}>{String(s?.run?.status ?? "unknown").toUpperCase()}</span>
                {` · ${s?.run?.id ?? "run"}`}
              </text>
              <SegmentedBar value={s?.progress?.registered_percent} width={22} />
              <text>{`${s?.progress?.registered_percent ?? 0}% registered work · ${s?.progress?.registered_done ?? 0}/${s?.progress?.registered_total ?? 0}`}</text>
              <text>{`Phases ${s?.progress?.phases_done ?? 0}/${s?.progress?.phases_total ?? 0} · slots ${s?.worker_budget?.live ?? 0}/${s?.worker_budget?.max ?? 0} · ${s?.run?.parent_loop ?? "no tick yet"}`}</text>
              <text> </text>
              <text>{`ACTIVE SESSIONS · Analysts ${s?.analysts_active?.length ?? 0} · Grunts ${s?.grunts_active?.length ?? 0}`}</text>
              <Show when={(s?.workers?.length ?? 0) > 0} fallback={<text>No active workers.</text>}>
                <For each={s?.workers ?? []}>{(worker: any) => <Worker worker={worker} />}</For>
              </Show>
              <Show when={(s?.attention?.length ?? 0) > 0}>
                <text fg="red">ATTENTION</text>
                <For each={(s?.attention ?? []).slice(0, 8)}>{(item: any) => <text fg="red">{`⚠ ${item.phase_id ?? ""}/${item.task_id ?? ""} · ${item.status ?? "attention"} · ${item.objective ?? ""}`}</text>}</For>
              </Show>
              <text> </text>
              <text>esc back</text>
            </Show>
          </box>
        )
      },
    },
  ])

  api.keymap.registerLayer({
    mode: "base",
    commands: [
      {
        name: "tbag.status.open",
        title: "T-BAG orchestration status",
        category: "T-BAG",
        namespace: "palette",
        slashName: "tbag",
        slashAliases: ["tbag-status"],
        enabled: () => Boolean(sessionFromRoute()),
        run: () => {
          const sessionID = sessionFromRoute()
          if (!sessionID) return
          readSnapshot(sessionID)
          api.route.navigate(ROUTE, { sessionID })
        },
      },
    ],
  })

  api.keymap.registerLayer({
    mode: MODE,
    bindings: [{ key: "escape", cmd: () => api.route.navigate("home"), desc: "Back" }],
  })

  const timer = setInterval(() => readSnapshot(sessionFromRoute()), REFRESH_MS)
  ;(timer as any).unref?.()
  queueMicrotask(() => readSnapshot(sessionFromRoute()))
  api.lifecycle.onDispose(() => clearInterval(timer))
}

export default {
  id: "tbag.status.v1",
  tui,
} satisfies TuiPluginModule
