#!/usr/bin/env python3
"""Read-only T-BAG status snapshot for humans, TUI adapters and diagnostics."""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dsd_attempt
import dsd_task

FORMAT = "tbag-status-v1"
CONTROL_ROLES = {"plan-reviewer", "context-reviewer", "phase-auditor"}


def _epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _transport(run: Path) -> dict[str, Any]:
    path = run / ".transport" / "opencode.json"
    raw = _load_json(path) or {}
    adapter_pid = raw.get("adapter_pid")
    updated = _epoch(raw.get("updated_at"))
    age = None if updated is None else max(0.0, time.time() - updated)
    adapter_alive = _pid_alive(adapter_pid)
    observers = []
    for item in raw.get("observers", []) if isinstance(raw.get("observers"), list) else []:
        if not isinstance(item, dict):
            continue
        observer_pid = item.get("observer_pid")
        observers.append({
            **item,
            "observer_process_alive": _pid_alive(observer_pid),
            "transport_adapter_alive": adapter_alive,
            "healthy": bool(adapter_alive and _pid_alive(observer_pid) and not item.get("done") and not item.get("orphaned")),
        })
    parents = [x for x in raw.get("parent_sessions", []) if isinstance(x, dict)] if isinstance(raw.get("parent_sessions"), list) else []
    return {
        "available": bool(raw),
        "path": str(path),
        "adapter_pid": adapter_pid,
        "adapter_alive": adapter_alive,
        "age_seconds": round(age, 1) if age is not None else None,
        "parent_sessions": parents,
        "observers": observers,
    }


def _run_candidates(project_root: Path) -> list[Path]:
    roots = []
    runs = project_root / "TBag" / "runs"
    if runs.is_dir():
        roots.extend(sorted((p for p in runs.iterdir() if (p / "run.json").is_file()), key=lambda p: p.name))
    if (project_root / "run.json").is_file():
        roots.append(project_root)
    return roots


def _select_run(project_root: Path, run_root: Path | None, parent_session_id: str | None) -> Path:
    if run_root is not None:
        root = run_root.resolve()
        if not (root / "run.json").is_file():
            raise ValueError(f"T-BAG run not found: {root}")
        return root
    candidates = _run_candidates(project_root.resolve())
    if not candidates:
        raise ValueError(f"no T-BAG runs found under {project_root / 'TBag' / 'runs'}")
    ranked = []
    for root in candidates:
        info = _load_json(root / "run.json") or {}
        transport = _transport(root)
        parent_match = bool(parent_session_id and any(str(x.get("session_id") or "") == parent_session_id for x in transport.get("parent_sessions", [])))
        active = str(info.get("status") or "active") == "active"
        try:
            modified = (root / "run.json").stat().st_mtime
        except OSError:
            modified = 0.0
        ranked.append(((1 if parent_match else 0, 1 if active else 0, modified), root))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked[0][1]


def _gate_state(run: Path, phase: str) -> dict[str, Any] | None:
    plan = dsd_task.owner_plan_dir(run)
    gates = sorted(plan.glob(f"PHASE-{phase}-GATE-*.md")) if plan.is_dir() else []
    if not gates:
        return None
    latest = gates[-1]
    lines = latest.read_text(encoding="utf-8", errors="replace").splitlines()[:16]
    result = next((line.split("**Result:**", 1)[1].strip() for line in lines if line.startswith("**Result:**")), "unknown")
    return {"result": result, "report": str(latest)}


def _objective(task: dict[str, Any]) -> str:
    try:
        return dsd_task.task_brief_objective(task, max_chars=180)
    except Exception:
        return str(task.get("task_id") or "task")


def _task_done(run: Path, phase: str, task: dict[str, Any]) -> bool:
    if str(task.get("role") or "") in CONTROL_ROLES:
        return False
    if dsd_task.valid_human_cancellation(task):
        return not dsd_task.open_review_findings(task)
    try:
        return bool(dsd_task.dependency_satisfied(run, phase, str(task.get("task_id") or "")))
    except Exception:
        status = str(task.get("status") or "")
        return status == "integrated" or (status == "accepted" and not task.get("requires_integration"))


def _preparation_worker(run: Path, phase: str, task: dict[str, Any]) -> dict[str, Any] | None:
    marker=dsd_task.task_root(run,phase,str(task.get("task_id") or ""))/"launch-preparation.json"
    data=_load_json(marker)
    if not data: return None
    pid=data.get("pid")
    if not _pid_alive(pid): return None
    role=str(data.get("role") or task.get("role") or "")
    tier=str(dsd_task.DEFAULT_TIER.get(role) or task.get("tier") or "")
    started=_epoch(data.get("started_at"))
    elapsed=max(0.0,time.time()-started) if started is not None else None
    return {
        "phase_id":phase,
        "task_id":task.get("task_id"),
        "objective":_objective(task),
        "authority":"Analyst" if tier=="analyst" else "Grunt",
        "tier":tier,
        "role":role,
        "driver":None,
        "model":"preparing worker context",
        "runtime_profile":"default",
        "state":"preparing",
        "process_alive":True,
        "process":{"worker":{"pid":pid,"alive":True}},
        "elapsed_seconds":round(elapsed,1) if elapsed is not None else None,
        "session":{"id":None,"known":False,"abandoned":False},
        "observer":{"known":False,"healthy":False,"not_applicable":"launch-preparation"},
        "preparation":str(marker),
    }


def _observer_for(transport: dict[str, Any], event_dir: str) -> dict[str, Any] | None:
    target = str(Path(event_dir).resolve()) if event_dir else ""
    matches=[]
    for item in transport.get("observers", []):
        try:
            current = str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError:
            current = str(item.get("event_dir") or "")
        if target and current == target:
            matches.append(item)
    if not matches: return None
    return next((x for x in reversed(matches) if x.get("healthy")),matches[-1])


def _inspect_worker(run: Path, phase: str, task: dict[str, Any], attempt: dict[str, Any], transport: dict[str, Any]) -> dict[str, Any]:
    event = Path(str(attempt.get("event_dir") or ""))
    try:
        observed = dsd_attempt.command_inspect(SimpleNamespace(
            run_root=run,
            phase_id=phase,
            task_id=str(task.get("task_id") or ""),
            event_dir=event,
            details=False,
            skip_duration_reference=False,
        ))
    except Exception as exc:
        observed = {"state": "inspect-error", "attention": "monitor-error", "monitor_error": str(exc)}
    session_id = dsd_attempt.attempt_session_id(attempt)
    abandoned = {str(x) for x in task.get("abandoned_sessions", []) if str(x)} if isinstance(task.get("abandoned_sessions"), list) else set()
    observer = _observer_for(transport, str(event))
    tier = str(attempt.get("tier") or dsd_task.DEFAULT_TIER.get(str(attempt.get("role") or task.get("role") or "")) or "")
    return {
        "phase_id": phase,
        "task_id": task.get("task_id"),
        "objective": _objective(task),
        "authority": "Analyst" if tier == "analyst" else "Grunt",
        "tier": tier,
        "role": attempt.get("role") or task.get("role"),
        "driver": attempt.get("driver"),
        "model": attempt.get("model"),
        "runtime_profile": attempt.get("runtime_profile") or "default",
        "event_dir": str(event),
        "session": {
            "id": session_id,
            "known": bool(session_id),
            "abandoned": bool(session_id and session_id in abandoned),
        },
        "observer": observer or {"healthy": False, "known": False},
        **observed,
    }


def build_snapshot(project_root: Path, *, run_root: Path | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
    run = _select_run(project_root, run_root, parent_session_id)
    info = dsd_task.load_run(run)
    transport = _transport(run)
    phases_root = run / "phases"
    phase_ids = sorted(p.name for p in phases_root.iterdir() if p.is_dir()) if phases_root.is_dir() else []
    phases = []
    workers = []
    recent = []
    attention = []
    registered_total = 0
    registered_done = 0

    for phase in phase_ids:
        task_dir = dsd_task.phase_root(run, phase) / "tasks"
        tasks = []
        if task_dir.is_dir():
            for state_path in sorted(task_dir.glob("*/task.json")):
                try:
                    task = dsd_task.load_json(state_path)
                except Exception:
                    continue
                role = str(task.get("role") or "")
                control = role in CONTROL_ROLES
                obsolete = str(task.get("status") or "") == "superseded"
                countable = not control and not obsolete
                done = _task_done(run, phase, task)
                if countable:
                    registered_total += 1
                    if done:
                        registered_done += 1
                item = {
                    "task_id": task.get("task_id"),
                    "role": role,
                    "status": task.get("status"),
                    "objective": _objective(task),
                    "done": done,
                    "control_conduit": control,
                    "counted_in_progress": countable,
                    "updated_at": task.get("updated_at"),
                }
                tasks.append(item)
                recent.append({"phase_id": phase, **item})
                if task.get("status") in {"blocked", "recovery-required", "needs-analysis"}:
                    attention.append({"phase_id": phase, "task_id": task.get("task_id"), "status": task.get("status"), "objective": item["objective"]})
                attempts = [x for x in task.get("attempts", []) if isinstance(x, dict)]
                live_attempts = [x for x in attempts if dsd_task.attempt_is_live(x)]
                preparation=_preparation_worker(run,phase,task)
                if preparation is not None and not live_attempts:
                    workers.append(preparation)
                for attempt in live_attempts:
                    worker = _inspect_worker(run, phase, task, attempt, transport)
                    workers.append(worker)
                    if worker.get("attention"):
                        attention.append({
                            "phase_id": phase,
                            "task_id": task.get("task_id"),
                            "status": worker.get("attention"),
                            "objective": item["objective"],
                        })
                    if transport.get("available") and not (worker.get("observer") or {}).get("healthy"):
                        attention.append({
                            "phase_id": phase,
                            "task_id": task.get("task_id"),
                            "status": "observer-missing",
                            "objective": item["objective"],
                        })
        counted = [x for x in tasks if x.get("counted_in_progress")]
        phase_done = sum(1 for x in counted if x.get("done"))
        phase_total = len(counted)
        gate = _gate_state(run, phase)
        phases.append({
            "phase_id": phase,
            "done": phase_done,
            "total": phase_total,
            "percent": round(100.0 * phase_done / phase_total, 1) if phase_total else 100.0,
            "gate": gate,
            "complete": bool(phase_total == phase_done and gate and str(gate.get("result") or "").upper() == "PASS"),
        })

    recent.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    workers.sort(key=lambda x: (0 if x.get("tier") == "analyst" else 1, str(x.get("phase_id")), str(x.get("task_id"))))
    current_phase = next((x for x in phases if not x.get("complete")), phases[-1] if phases else None)
    loop = _load_json(run / "parent-loop.json") or {}
    max_workers = int(info.get("max_workers") or 0)
    progress = {
        "registered_done": registered_done,
        "registered_total": registered_total,
        "registered_percent": round(100.0 * registered_done / registered_total, 1) if registered_total else 100.0,
        "phases_done": sum(1 for x in phases if x.get("complete")),
        "phases_total": len(phases),
    }
    return {
        "format": FORMAT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root.resolve()),
        "run_root": str(run),
        "run": {
            "id": info.get("run_id") or run.name,
            "status": info.get("status") or "active",
            "parent_loop": loop.get("last_classification"),
        },
        "progress": progress,
        "current_phase": current_phase,
        "phases": phases,
        "workers": workers,
        "analysts_active": [x for x in workers if x.get("tier") == "analyst"],
        "grunts_active": [x for x in workers if x.get("tier") != "analyst"],
        "worker_budget": {"max": max_workers, "live": len(workers), "free": max(0, max_workers - len(workers))},
        "attention": attention[:16],
        "recent": recent[:10],
        "transport": transport,
    }


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--run-root", type=Path)
    ap.add_argument("--parent-session-id")
    ap.add_argument("--pretty", action="store_true")
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        result = build_snapshot(args.project_root, run_root=args.run_root, parent_session_id=args.parent_session_id)
        print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True, separators=None if args.pretty else (",", ":")))
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
