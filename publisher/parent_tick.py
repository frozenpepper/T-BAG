#!/usr/bin/env python3
"""One deterministic T-BAG parent orchestration tick.

Wake transport is deliberately not orchestration truth. Every owner turn, adapter wake,
resume and periodic heartbeat enters here: collapse deterministic lifecycle transitions,
inspect every live attempt, apply bounded lifecycle supervision, and return one compact
packet telling the parent whether to continue, launch, update the owner, intervene, or
finish the run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import dsd_attempt
import dsd_task

FORMAT = "tbag-parent-loop-v1"
DEFAULT_OWNER_HEARTBEAT_SECONDS = 1800.0
DEFAULT_CHANGED_UPDATE_MIN_SECONDS = 900.0
DEFAULT_REPORT_COMPLETE_GRACE_SECONDS = 30.0
DEFAULT_STALL_CONFIRM_SECONDS = 300.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def epoch(value: Any) -> float | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def loop_file(run: Path) -> Path:
    return run.resolve() / "parent-loop.json"


def load_loop(run: Path) -> dict[str, Any]:
    path = loop_file(run)
    if not path.is_file():
        return {"format": FORMAT, "stall_observations": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"format": FORMAT, "stall_observations": {}}
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return {"format": FORMAT, "stall_observations": {}}
    if not isinstance(data.get("stall_observations"), dict):
        data["stall_observations"] = {}
    return data


def save_loop(run: Path, data: dict[str, Any]) -> None:
    path = loop_file(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def args_for(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(**values)


def reconcile(run: Path, phase_id: str | None, *, sweep: bool = True) -> dict[str, Any]:
    return dsd_task.command_reconcile_run(args_for(run_root=run, phase_id=phase_id, no_sweep=not sweep, details=False))


def inspect_attempt(run: Path, item: dict[str, Any]) -> dict[str, Any]:
    return dsd_attempt.command_inspect(args_for(
        run_root=run,
        phase_id=str(item.get("phase_id") or ""),
        task_id=str(item.get("task_id") or ""),
        event_dir=Path(str(item.get("event_dir") or "")),
        details=False,
        skip_duration_reference=False,
    ))


def retire_attempt(run: Path, item: dict[str, Any], reason: str) -> dict[str, Any]:
    return dsd_attempt.command_retire(args_for(
        run_root=run,
        phase_id=str(item.get("phase_id") or ""),
        task_id=str(item.get("task_id") or ""),
        event_dir=Path(str(item.get("event_dir") or "")),
        reason=reason,
    ))


def completion_candidate(state: dict[str, Any]) -> bool:
    if str(state.get("run_status") or "active") != "active":
        return False
    return not any((
        state.get("first_useful_actions"),
        state.get("live_attempts"),
        state.get("human_blocks"),
        state.get("unresolved_state"),
        int(state.get("backlog_count") or 0),
        int(state.get("waiting_dependency_count") or 0),
    ))


def owner_signature(state: dict[str, Any], monitors: list[dict[str, Any]], classification: str) -> str:
    payload = {
        "run_status": state.get("run_status"),
        "classification": classification,
        "backlog_count": state.get("backlog_count"),
        "waiting_dependency_count": state.get("waiting_dependency_count"),
        "live": sorted((str(x.get("phase_id")), str(x.get("task_id")), str(x.get("role"))) for x in state.get("live_attempts") or []),
        "human": sorted((str(x.get("phase_id")), str(x.get("task_id")), str(x.get("action"))) for x in state.get("human_blocks") or []),
        "attention": sorted((str(x.get("phase_id")), str(x.get("task_id")), str(x.get("attention"))) for x in monitors if x.get("attention")),
        "actions": sorted((str(x.get("phase_id")), str(x.get("task_id")), str(x.get("action"))) for x in state.get("first_useful_actions") or []),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.blake2s(raw, digest_size=12).hexdigest()


def update_due(
    loop: dict[str, Any],
    state: dict[str, Any],
    monitors: list[dict[str, Any]],
    classification: str,
    *,
    heartbeat_seconds: float,
    changed_min_seconds: float,
) -> dict[str, Any]:
    stamp = time.time()
    signature = owner_signature(state, monitors, classification)
    last_at = epoch(loop.get("last_owner_update_at"))
    elapsed = None if last_at is None else max(0.0, stamp - last_at)
    last_signature = str(loop.get("last_owner_update_signature") or "")
    urgent: list[str] = []
    if str(state.get("run_status") or "active") != "active": urgent.append("run-terminal-state")
    if state.get("human_blocks"): urgent.append("owner-decision-required")
    if classification == "completion-candidate": urgent.append("project-end-candidate")
    if any(x.get("retirement_requested") for x in monitors): urgent.append("worker-retired")
    if any(x.get("attention") == "silent-long-running" for x in monitors): urgent.append("worker-stall")
    if urgent:
        due, reasons = True, urgent
    elif last_at is None:
        due, reasons = True, ["initial-status"]
    elif signature != last_signature and elapsed is not None and elapsed >= changed_min_seconds:
        due, reasons = True, ["material-state-change"]
    elif elapsed is not None and elapsed >= heartbeat_seconds:
        due, reasons = True, ["periodic-heartbeat"]
    else:
        due, reasons = False, []
    token = hashlib.blake2s(f"{signature}:{int(stamp)}".encode(), digest_size=10).hexdigest() if due else None
    result: dict[str, Any] = {"due": due, "reasons": reasons, "signature": signature}
    if token: result["token"] = token
    if elapsed is not None: result["seconds_since_last_update"] = round(elapsed, 1)
    return result


def command_tick(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve()
    loop = load_loop(run)
    loop["last_tick_at"] = now()

    advance_result: dict[str, Any] | None = None
    info = dsd_task.load_run(run)
    if str(info.get("status") or "active") == "active":
        advance_result = dsd_task.command_advance(args_for(
            run_root=run,
            phase_id=getattr(args, "phase_id", None),
            max_steps=int(getattr(args, "max_steps", 12) or 12),
        ))

    state = reconcile(run, getattr(args, "phase_id", None), sweep=True)
    monitors: list[dict[str, Any]] = []
    stalls = loop.setdefault("stall_observations", {})
    seen_events: set[str] = set()
    changed_runtime = False
    current_time = time.time()

    for live in list(state.get("live_attempts") or []):
        event = str(live.get("event_dir") or "")
        seen_events.add(event)
        try:
            observed = inspect_attempt(run, live)
        except Exception as exc:
            monitors.append({**live, "monitor_error": str(exc), "attention": "monitor-error"})
            continue
        item = {**live, **observed}
        report_age = observed.get("report_age_seconds")
        if observed.get("state") == "running" and observed.get("report_state") == "present" and isinstance(report_age, (int, float)) and report_age >= float(args.report_complete_grace_seconds):
            try:
                item["retirement_requested"] = retire_attempt(run, live, "report-complete-no-terminal")
                changed_runtime = True
            except Exception as exc:
                item["retirement_error"] = str(exc)
                item["attention"] = "retirement-failed"
            stalls.pop(event, None)
        elif observed.get("state") == "running" and observed.get("attention") == "silent-long-running":
            prior = stalls.get(event) if isinstance(stalls.get(event), dict) else {}
            first_seen = epoch(prior.get("first_seen_at"))
            if first_seen is None:
                first_seen = current_time
                prior = {"first_seen_at": now(), "task_id": live.get("task_id"), "phase_id": live.get("phase_id")}
            prior["last_seen_at"] = now()
            stalls[event] = prior
            stalled_for = max(0.0, current_time - first_seen)
            item["stall_confirmed_seconds"] = round(stalled_for, 1)
            if stalled_for >= float(args.stall_confirm_seconds):
                try:
                    item["retirement_requested"] = retire_attempt(run, live, "confirmed-silent-long-running")
                    changed_runtime = True
                except Exception as exc:
                    item["retirement_error"] = str(exc)
                    item["attention"] = "retirement-failed"
            else:
                item["automatic_intervention_in_seconds"] = round(float(args.stall_confirm_seconds) - stalled_for, 1)
        else:
            stalls.pop(event, None)
        monitors.append(item)

    for event in list(stalls):
        if event not in seen_events:
            stalls.pop(event, None)

    if changed_runtime:
        state = reconcile(run, getattr(args, "phase_id", None), sweep=False)

    run_status = str(state.get("run_status") or "active")
    pending = list(state.get("first_useful_actions") or [])
    live_now = list(state.get("live_attempts") or [])
    if run_status != "active":
        classification = f"run-{run_status}"
        turn = "terminal" if run_status in {"completed", "abandoned"} else "owner"
    elif state.get("human_blocks") and not pending and not live_now:
        classification = "awaiting-owner"
        turn = "owner"
    elif completion_candidate(state):
        classification = "completion-candidate"
        turn = "finish-or-replan"
    elif any(x.get("retirement_error") for x in monitors) or state.get("unresolved_state"):
        classification = "recovery-required"
        turn = "intervene"
    elif pending:
        classification = "actions-ready"
        turn = "continue"
    elif live_now:
        classification = "workers-running"
        turn = "yield"
    else:
        classification = "active-idle"
        turn = "intervene"

    owner = update_due(
        loop,
        state,
        monitors,
        classification,
        heartbeat_seconds=float(args.owner_heartbeat_seconds),
        changed_min_seconds=float(args.changed_update_min_seconds),
    )
    if owner.get("due"):
        try:
            owner["status"] = dsd_task.command_owner_status(args_for(run_root=run, phase_id=getattr(args, "phase_id", None)))
        except Exception as exc:
            owner["status_error"] = str(exc)
        loop["pending_owner_update"] = {"token": owner.get("token"), "signature": owner.get("signature"), "reasons": owner.get("reasons"), "created_at": now()}

    loop["last_classification"] = classification
    loop["last_signature"] = owner.get("signature")
    save_loop(run, loop)

    out: dict[str, Any] = {
        "format": FORMAT,
        "run_id": state.get("run_id"),
        "run_status": run_status,
        "classification": classification,
        "turn": turn,
        "worker_budget": state.get("worker_budget"),
        "owner_update": owner,
    }
    if advance_result: out["advance"] = advance_result
    if pending: out["actions"] = pending
    if live_now: out["live_attempts"] = live_now
    if monitors: out["monitoring"] = monitors
    if state.get("human_blocks"): out["human_blocks"] = state.get("human_blocks")
    if state.get("unresolved_state"): out["unresolved_state"] = state.get("unresolved_state")
    if classification == "completion-candidate":
        out["project_end"] = {"candidate": True, "next": "finish after confirming accepted plan obligations are exhausted; otherwise replan/register remaining work"}
    if classification == "active-idle":
        out["control_error"] = "active run has no live worker, no authorized action, no owner block, and is not mechanically complete; route planning/recovery instead of yielding indefinitely"
    return out


def command_ack_update(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve(); loop = load_loop(run)
    pending = loop.get("pending_owner_update") if isinstance(loop.get("pending_owner_update"), dict) else {}
    if not pending or str(pending.get("token") or "") != str(args.token):
        raise ValueError("owner-update token is missing/stale; run a fresh parent tick")
    loop["last_owner_update_at"] = now()
    loop["last_owner_update_signature"] = pending.get("signature")
    loop["last_owner_update_reasons"] = pending.get("reasons")
    loop.pop("pending_owner_update", None)
    save_loop(run, loop)
    return {"acknowledged": True, "token": args.token, "recorded_at": loop["last_owner_update_at"]}


def command_finish(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve()
    state = reconcile(run, getattr(args, "phase_id", None), sweep=True)
    if not completion_candidate(state):
        raise ValueError("run is not a completion candidate; live/pending/blocked/unresolved registered work remains")
    result = dsd_task.command_set_run_status(args_for(run_root=run, status="completed", reason=args.reason))
    loop = load_loop(run); loop["last_tick_at"] = now(); loop["last_classification"] = "run-completed"; save_loop(run, loop)
    return {"completed": True, "reason": args.reason, "run_status": result}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("tick")
    p.add_argument("--run-root", type=Path, required=True); p.add_argument("--phase-id"); p.add_argument("--max-steps", type=int, default=12)
    p.add_argument("--owner-heartbeat-seconds", type=float, default=DEFAULT_OWNER_HEARTBEAT_SECONDS)
    p.add_argument("--changed-update-min-seconds", type=float, default=DEFAULT_CHANGED_UPDATE_MIN_SECONDS)
    p.add_argument("--report-complete-grace-seconds", type=float, default=DEFAULT_REPORT_COMPLETE_GRACE_SECONDS)
    p.add_argument("--stall-confirm-seconds", type=float, default=DEFAULT_STALL_CONFIRM_SECONDS)
    p = sub.add_parser("ack-update"); p.add_argument("--run-root", type=Path, required=True); p.add_argument("--token", required=True)
    p = sub.add_parser("finish"); p.add_argument("--run-root", type=Path, required=True); p.add_argument("--phase-id"); p.add_argument("--reason", required=True)
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "tick": result = command_tick(args)
        elif args.command == "ack-update": result = command_ack_update(args)
        elif args.command == "finish": result = command_finish(args)
        else: raise ValueError(args.command)
        print(json.dumps(result, sort_keys=True)); return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "command": getattr(args, "command", None)}), file=os.sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
