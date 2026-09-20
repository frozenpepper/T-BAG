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
PULSE_FORMAT = "tbag-parent-pulse-v1"
DEFAULT_OWNER_HEARTBEAT_SECONDS = 1800.0
DEFAULT_CHANGED_UPDATE_MIN_SECONDS = 900.0
DEFAULT_REPORT_COMPLETE_GRACE_SECONDS = 30.0
DEFAULT_STALL_CONFIRM_SECONDS = 300.0
DEFAULT_DISK_SAMPLE_SECONDS = 300.0


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


def action_key(item: dict[str, Any]) -> str:
    return json.dumps(item,sort_keys=True,separators=(",",":"),default=str)

def disk_usage_for_tick(run: Path, loop: dict[str, Any], *, sample_seconds: float) -> dict[str, Any]:
    """Return throttled disk telemetry without making every owner turn walk the tree."""
    current=time.time()
    cached=loop.get("disk_usage_sample") if isinstance(loop.get("disk_usage_sample"),dict) else None
    sampled=epoch(cached.get("sampled_at")) if cached else None
    if cached is not None and sampled is not None and current-sampled < max(0.0,sample_seconds):
        return {**cached,"cached":True,"sample_age_seconds":round(max(0.0,current-sampled),1)}
    try:
        import dsd_workspace
        fresh=dsd_workspace.disk_usage_snapshot(run)
    except Exception as exc:
        return {"sampled_at":now(),"error":str(exc)[:800],"cached":False}
    previous_total=int(cached.get("owned_total_bytes") or 0) if cached else None
    if previous_total is not None:
        fresh["delta_since_previous_sample_bytes"]=int(fresh.get("owned_total_bytes") or 0)-previous_total
    loop["disk_usage_sample"]=fresh
    return {**fresh,"cached":False,"sample_age_seconds":0.0}



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


def transport_registry(run:Path)->dict[str,Any]:
    path=run/".transport"/"opencode.json"
    try:
        value=json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value,dict) else {}
    except (OSError,json.JSONDecodeError):
        return {}

def observer_for(registry:dict[str,Any], event_dir:str)->dict[str,Any]|None:
    target=str(Path(event_dir).resolve()) if event_dir else ""
    adapter_pid=registry.get("adapter_pid"); adapter_alive=False
    if isinstance(adapter_pid,int) and adapter_pid>0:
        try: os.kill(adapter_pid,0); adapter_alive=True
        except OSError: pass
    matches=[]
    for item in registry.get("observers",[]) if isinstance(registry.get("observers"),list) else []:
        if not isinstance(item,dict): continue
        try: current=str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError: current=str(item.get("event_dir") or "")
        if current!=target: continue
        pid=item.get("observer_pid"); alive=False
        if isinstance(pid,int) and pid>0:
            try: os.kill(pid,0); alive=True
            except OSError: pass
        matches.append({**item,"process_alive":alive,"adapter_alive":adapter_alive,"healthy":bool(alive and adapter_alive and not item.get("done") and not item.get("orphaned"))})
    if not matches: return None
    return next((x for x in reversed(matches) if x.get("healthy")),matches[-1])


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


def command_pulse(args: argparse.Namespace) -> dict[str, Any]:
    """Cheap read-only transport probe: did a started attempt stop executing?

    This intentionally does *not* reconcile scheduling, readiness, Human blocks,
    recovery policy, or project completion. Those semantics belong to ``tick``.
    """
    run = args.run_root.resolve()
    info = dsd_task.load_run(run)
    status = str(info.get("status") or "active")
    wait=load_loop(run).get("owner_wait")
    base: dict[str, Any] = {
        "format": PULSE_FORMAT,
        "generated_at": now(),
        "run_id": info.get("run_id"),
        "run_status": status,
        "wake_parent": False,
    }
    if isinstance(wait,dict) and wait.get("open"):
        return {**base,"heartbeat_state":"waiting","reason":"owner-question-open","owner_question_id":wait.get("question_id")}
    if status in {"completed", "abandoned"}:
        return {**base, "heartbeat_state": "ended", "reason": f"run-{status}"}
    if status == "paused-by-user":
        return {**base, "heartbeat_state": "paused", "reason": "run-paused-by-user"}
    if status == "human-blocked":
        return {**base, "heartbeat_state": "waiting", "reason": "human-decision-pending"}

    live: list[dict[str, Any]] = []
    stopped: list[dict[str, Any]] = []
    live_preparations: list[dict[str, Any]] = []
    stopped_preparations: list[dict[str, Any]] = []
    for task in dsd_task.iter_run_tasks(run):
        phase = str(task.get("phase_id") or "")
        task_id = str(task.get("task_id") or "")
        if phase and task_id:
            marker = dsd_task.task_root(run, phase, task_id) / "launch-preparation.json"
            if marker.is_file():
                try:
                    preparation = dsd_task.load_json(marker)
                except Exception:
                    preparation = {}
                pid = preparation.get("pid")
                item = {
                    "phase_id": phase,
                    "task_id": task_id,
                    "preparation_pid": pid,
                    "preparation": str(marker),
                    "role": preparation.get("role"),
                }
                if isinstance(pid, int) and pid > 0 and dsd_attempt.pid_alive(pid):
                    live_preparations.append(item)
                else:
                    stopped_preparations.append(item)

        attempts = [item for item in task.get("attempts", []) if isinstance(item, dict)]
        if not attempts:
            continue
        attempt = attempts[-1]
        if str(attempt.get("status") or "") != "started":
            continue
        event = Path(str(attempt.get("event_dir") or ""))
        terminal = bool(event.is_dir() and (event / "terminal.json").is_file())
        item = {
            "phase_id": task.get("phase_id"),
            "task_id": task.get("task_id"),
            "event_dir": attempt.get("event_dir"),
            "terminal_present": terminal,
        }
        if terminal or not dsd_task.attempt_is_live(attempt):
            stopped.append(item)
        else:
            live.append(item)

    if stopped or stopped_preparations:
        reason = "attempt-stopped" if stopped and not stopped_preparations else "preparation-stopped" if stopped_preparations and not stopped else "attempt-or-preparation-stopped"
        return {
            **base,
            "heartbeat_state": "running",
            "wake_parent": True,
            "reason": reason,
            "stopped_attempts": stopped,
            "stopped_preparations": stopped_preparations,
            "live_attempts": live,
            "live_preparations": live_preparations,
        }
    if live or live_preparations:
        reason = "workers-still-running" if live else "launch-preparation-running"
        return {
            **base,
            "heartbeat_state": "running",
            "reason": reason,
            "live_count": len(live),
            "preparation_count": len(live_preparations),
            "live_attempts": live,
            "live_preparations": live_preparations,
        }
    return {
        **base,
        "heartbeat_state": "idle-recovery",
        "reason": "no-started-attempt-is-running",
        "live_attempts": [],
        "live_preparations": [],
    }


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
    """Classify owner communication as an acknowledged edge, not a level alarm."""
    stamp = time.time()
    signature = owner_signature(state, monitors, classification)
    last_at = epoch(loop.get("last_owner_update_at"))
    elapsed = None if last_at is None else max(0.0, stamp - last_at)
    last_signature = str(loop.get("last_owner_update_signature") or "")
    last_reasons = sorted(str(x) for x in (loop.get("last_owner_update_reasons") or []) if str(x))
    urgent: list[str] = []
    durable_status = str(state.get("run_status") or "active")
    if durable_status in {"completed", "abandoned"}: urgent.append("run-terminal-state")
    elif durable_status == "paused-by-user": urgent.append("run-paused")
    if state.get("human_blocks") or durable_status == "human-blocked": urgent.append("owner-decision-required")
    if classification == "completion-candidate": urgent.append("project-end-candidate")
    if any(x.get("retirement_requested") for x in monitors): urgent.append("worker-retired")
    if any(x.get("attention") == "silent-long-running" for x in monitors): urgent.append("worker-stall")
    if classification == "recovery-required": urgent.append("control-recovery-required")
    same_acknowledged_condition = signature == last_signature and sorted(urgent) == last_reasons
    if urgent and (last_at is None or not same_acknowledged_condition):
        due, reasons = True, urgent
    elif last_at is None:
        due, reasons = True, ["initial-status"]
    elif urgent and elapsed is not None and elapsed >= heartbeat_seconds:
        due, reasons = True, urgent
    elif signature != last_signature and elapsed is not None and elapsed >= changed_min_seconds:
        due, reasons = True, ["material-state-change"]
    elif elapsed is not None and elapsed >= heartbeat_seconds:
        due, reasons = True, ["periodic-heartbeat"]
    else:
        due, reasons = False, []

    token = None
    if due:
        pending = loop.get("pending_owner_update") if isinstance(loop.get("pending_owner_update"),dict) else {}
        pending_reasons = sorted(str(x) for x in (pending.get("reasons") or []) if str(x))
        if str(pending.get("signature") or "") == signature and pending_reasons == sorted(reasons) and pending.get("token"):
            token = str(pending["token"])
        else:
            token = hashlib.blake2s(f"{signature}:{int(stamp)}".encode(), digest_size=10).hexdigest()
    result: dict[str, Any] = {"due": due, "reasons": reasons, "signature": signature}
    if token: result["token"] = token
    if elapsed is not None: result["seconds_since_last_update"] = round(elapsed, 1)
    return result


def owner_questions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return durable Human blockers as native-question payloads, de-duplicated."""
    found=[]; seen=set()
    for block in state.get("human_blocks") or []:
        if not isinstance(block,dict): continue
        question=block.get("owner_question")
        if not isinstance(question,dict) or not question.get("blocking"): continue
        key=str(question.get("id") or f"{block.get('phase_id')}:{block.get('task_id')}")
        if key in seen: continue
        seen.add(key); found.append(question)
    return found


def runtime_config_questions(run: Path, blocked_actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Turn only missing owner-supplied runtime authority into native questions."""
    found=[]; seen=set()
    for item in blocked_actions:
        if not isinstance(item,dict): continue
        reason=str(item.get("reason") or item.get("error") or "")
        if "MISSING_RUNTIME_CONFIG:" not in reason: continue
        phase=str(item.get("phase_id") or ""); tid=str(item.get("task_id") or "")
        try: task=dsd_task.load_task(run,phase,tid)
        except Exception: task={}
        tier=str(task.get("tier") or "worker")
        key=f"runtime-config:{tier}"
        if key in seen: continue
        seen.add(key)
        found.append({
            "id":key,
            "kind":"runtime-config",
            "blocking":True,
            "required_interface":"native-question",
            "header":"T-BAG needs runtime configuration",
            "question":f"{reason}\n\nProvide the exact {tier} worker driver and model T-BAG should use. Do not guess or infer a model name.",
            "options":[],
            "custom_answer":True,
            "fallback_banner":"╔═ T-BAG — ACTION REQUIRED ═╗",
            "tier":tier,
            "affected_task":{"phase_id":phase,"task_id":tid},
            "decision_command":"set-runtime",
        })
    return found


def owner_notice(owner: dict[str, Any]) -> dict[str, Any] | None:
    if not owner.get("due"): return None
    return {
        "kind":"owner-notice",
        "blocking":False,
        "banner":"━━ T-BAG UPDATE ━━",
        "render":"decorated-chat",
        "ack_token":owner.get("token"),
        "reasons":owner.get("reasons") or [],
        "status":owner.get("status"),
    }


def compact_advance(result: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep deterministic transition receipts, not a duplicate reconciliation tree."""
    if not isinstance(result,dict):
        return None
    applied=list(result.get("applied") or [])
    blocked=list(result.get("blocked_actions") or [])
    stopped=str(result.get("stopped") or "")
    if not applied and not blocked and stopped in {"", "quiescent", "semantic-or-launch-boundary"}:
        return None
    out={"stopped":stopped}
    if applied: out["applied"]=applied
    if blocked: out["blocked_actions"]=blocked
    if result.get("reason"): out["reason"]=result["reason"]
    return out



_LAUNCH_ACTION_ROLES={
    "launch-recovery":"recovery",
    "launch-analyst-discovery":"discovery",
    "launch-fixer":"fixer",
    "launch-fresh-reviewer":"reviewer",
    "launch-or-reuse-fresh-plan-reviewer":"plan-reviewer",
}

def _launch_action_blocker(run:Path, action:dict[str,Any])->str|None:
    name=str(action.get("action") or "")
    if name not in set(_LAUNCH_ACTION_ROLES)|{"launch-ready-task","resume-recorded-session"}:
        return None
    phase=str(action.get("phase_id") or ""); tid=str(action.get("task_id") or "")
    if not phase or not tid: return "launch action is missing phase/task identity"
    if name=="launch-ready-task":
        try: role=str(dsd_task.load_task(run,phase,tid).get("role") or "")
        except Exception as exc: return str(exc)
    elif name=="resume-recorded-session":
        role=str(action.get("role") or "")
        if not role:
            try: role=str(dsd_task.load_task(run,phase,tid).get("role") or "")
            except Exception as exc: return str(exc)
    else:
        role=_LAUNCH_ACTION_ROLES[name]
    return dsd_attempt.launch_blocker(run,phase,tid,role,continuing=name=="resume-recorded-session")

def command_tick(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve()
    loop = load_loop(run)
    loop["last_tick_at"] = now()

    advance_result: dict[str, Any] | None = None
    info = dsd_task.load_run(run)
    poison_result: dict[str, Any] | None = None
    if str(info.get("status") or "active") == "active":
        advance_result = dsd_task.command_advance(args_for(
            run_root=run,
            phase_id=getattr(args, "phase_id", None),
            max_steps=int(getattr(args, "max_steps", 12) or 12),
        ))
        poison_result = dsd_task.command_poison_scan(args_for(run_root=run,phase_id=getattr(args,"phase_id",None)))

    state = reconcile(run, getattr(args, "phase_id", None), sweep=True)
    monitors: list[dict[str, Any]] = []
    stalls = loop.setdefault("stall_observations", {})
    seen_events: set[str] = set()
    changed_runtime = False
    current_time = time.time()
    transport=transport_registry(run)
    observer_rearm=[]

    for live in list(state.get("live_attempts") or []):
        event = str(live.get("event_dir") or "")
        seen_events.add(event)
        try:
            observed = inspect_attempt(run, live)
        except Exception as exc:
            monitors.append({**live, "monitor_error": str(exc), "attention": "monitor-error"})
            continue
        item = {**live, **observed}
        deadline = observed.get("deadline") if isinstance(observed.get("deadline"),dict) else {}
        deadline_exceeded = bool(deadline.get("exceeded"))
        observer=observer_for(transport,event) if transport else None
        if transport:
            item["observer"]=observer or {"healthy":False,"known":False}
            if observer is None or not observer.get("healthy"):
                if observed.get("state") == "running" and not deadline_exceeded:
                    item["observer_attention"]="observer-missing"
                    observer_rearm.append({"run_root":str(run),"phase_id":live.get("phase_id"),"task_id":live.get("task_id"),"event_dir":event})
                elif deadline_exceeded:
                    item["observer_attention"]="observer-not-rearmed-after-attempt-deadline"
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
            cpu_now=((observed.get("process") or {}).get("worker") or {}).get("cpu_seconds")
            if first_seen is None:
                first_seen = current_time
                prior = {"first_seen_at": now(), "task_id": live.get("task_id"), "phase_id": live.get("phase_id"), "cpu_seconds_at_first_seen":cpu_now}
            prior["last_seen_at"] = now(); prior["last_cpu_seconds"]=cpu_now
            stalls[event] = prior
            stalled_for = max(0.0, current_time - first_seen)
            item["stall_confirmed_seconds"] = round(stalled_for, 1)
            cpu_start=prior.get("cpu_seconds_at_first_seen"); cpu_delta=None
            if isinstance(cpu_now,(int,float)) and isinstance(cpu_start,(int,float)):
                cpu_delta=max(0.0,float(cpu_now)-float(cpu_start)); item["stall_cpu_delta_seconds"]=round(cpu_delta,2)
            cpu_quiet=cpu_delta is None or cpu_delta<=2.0
            if stalled_for >= float(args.stall_confirm_seconds) and (cpu_quiet or deadline_exceeded):
                try:
                    reason="confirmed-silent-after-attempt-deadline" if deadline_exceeded else "confirmed-silent-long-running"
                    item["retirement_requested"] = retire_attempt(run, live, reason)
                    changed_runtime = True
                except Exception as exc:
                    item["retirement_error"] = str(exc)
                    item["attention"] = "retirement-failed"
            elif stalled_for >= float(args.stall_confirm_seconds):
                item["automatic_intervention_deferred"]="worker-cpu-still-changing"
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
    blocked_actions=list(advance_result.get("blocked_actions") or []) if isinstance(advance_result,dict) else []
    blocked_keys={str(item.get("key") or "") for item in blocked_actions if isinstance(item,dict)}
    pending_all=list(state.get("first_useful_actions") or [])
    pending=[item for item in pending_all if action_key(item) not in blocked_keys]
    launchable=[]
    for item in pending:
        blocker=_launch_action_blocker(run,item)
        if blocker:
            blocked_actions.append({**item,"key":action_key(item),"reason":blocker,"waiting_on":"launch-precondition"})
        else:
            launchable.append(item)
    pending=launchable
    live_now = list(state.get("live_attempts") or [])
    durable_questions=owner_questions(state)
    questions=durable_questions+runtime_config_questions(run,blocked_actions)
    if run_status != "active":
        classification = f"run-{run_status}"
        turn = "terminal" if run_status in {"completed", "abandoned"} else "owner"
    elif completion_candidate(state):
        classification = "completion-candidate"
        turn = "finish-or-replan"
    elif any(x.get("retirement_error") for x in monitors) or state.get("unresolved_state") or (blocked_actions and not pending):
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

    loop_suspected=None
    repeated_actions=None
    if not questions and classification=="actions-ready" and pending:
        signature="|".join(action_key(item) for item in pending)
        prior=loop.get("action_repeat") if isinstance(loop.get("action_repeat"),dict) else {}
        same=str(prior.get("signature") or "")==signature
        count=int(prior.get("count") or 0)+1 if same else 1
        record={
            "signature":signature,
            "count":count,
            "first_seen_at":prior.get("first_seen_at") if same else now(),
            "last_seen_at":now(),
        }
        loop["action_repeat"]=record
        if count>=3:
            repeated_actions=list(pending)
            pending=[]
            loop_suspected={
                "count":count,
                "since":record.get("first_seen_at"),
                "actions":repeated_actions,
                "next":"Do not issue the same launch/resume suggestion again. Diagnose why durable state did not change; use Analyst/recovery for semantic uncertainty rather than repeating the loop.",
            }
            classification="loop-suspected"
            turn="intervene"
    else:
        loop.pop("action_repeat",None)

    # Human blockers are an interaction boundary, not a status footnote. Independent
    # work may still be launched first, but the parent turn must end in the harness's
    # native question UI rather than an ordinary chat message or silent yield.
    if questions and run_status not in {"completed","abandoned","paused-by-user"}:
        classification = "owner-question-required"
        turn = "ask-owner"

    run_status_transition = None
    if durable_questions and run_status == "active" and not pending and not live_now:
        run_status_transition = dsd_task.command_set_run_status(args_for(
            run_root=run,
            status="human-blocked",
            reason="awaiting native Human question response",
        ))
        run_status = "human-blocked"
        state["run_status"] = run_status

    disk_usage=disk_usage_for_tick(run,loop,sample_seconds=float(getattr(args,"disk_sample_seconds",DEFAULT_DISK_SAMPLE_SECONDS)))
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
            owner["status"] = dsd_task.command_owner_status(args_for(run_root=run, phase_id=getattr(args, "phase_id", None), disk_usage=disk_usage))
        except Exception as exc:
            owner["status_error"] = str(exc)
        if questions:
            owner["covered_by_native_question"]=True
        else:
            loop["pending_owner_update"] = {"token": owner.get("token"), "signature": owner.get("signature"), "reasons": owner.get("reasons"), "created_at": now()}

    notice=None if questions else owner_notice(owner)
    loop["last_classification"] = classification
    loop["last_signature"] = owner.get("signature")
    save_loop(run, loop)

    out: dict[str, Any] = {
        "format": FORMAT,
        "generated_at": now(),
        "run_id": state.get("run_id"),
        "run_status": run_status,
        "classification": classification,
        "turn": turn,
        "worker_budget": state.get("worker_budget"),
        "owner_update": owner,
        "disk_usage": disk_usage,
    }
    if questions:
        out["owner_question_required"]=True
        out["owner_questions"]=questions
        out["question_contract"]="Run actions_before_question first. Then call parent_tick.py wait-owner --question-id <id>, invoke the harness-native question UI, and end the turn. Plain chat/status output is not a substitute. After recording/applying the Human answer, call parent_tick.py resume-owner --question-id <id> before the next tick."
        out["heartbeat_contract"]="While owner_wait is open, both completion pulse and health heartbeat are suspended even if detached workers continue; their durable results reconcile after resume."
        if pending: out["actions_before_question"]=pending
    elif notice is not None:
        out["owner_notice"]=notice
    if run_status_transition: out["run_status_transition"] = run_status_transition
    advance_packet=compact_advance(advance_result)
    if advance_packet: out["advance"] = advance_packet
    if poison_result and poison_result.get("count"): out["poisoned_sessions_routed"] = poison_result
    if blocked_actions: out["blocked_actions"] = blocked_actions
    if loop_suspected: out["loop_suspected"] = loop_suspected
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


def command_wait_owner(args: argparse.Namespace) -> dict[str, Any]:
    """Suspend autonomous heartbeat transport while a native Human question is open."""
    run=args.run_root.resolve(); dsd_task.load_run(run)
    question_id=str(args.question_id).strip()
    if not question_id: raise ValueError("question_id is required")
    loop=load_loop(run)
    current=loop.get("owner_wait") if isinstance(loop.get("owner_wait"),dict) else None
    if current and current.get("open") and str(current.get("question_id"))!=question_id:
        raise ValueError(f"another owner question is already open: {current.get('question_id')}")
    loop["owner_wait"]={
        "open":True,
        "question_id":question_id,
        "opened_at":current.get("opened_at") if current else now(),
        "updated_at":now(),
    }
    save_loop(run,loop)
    info=dsd_task.load_run(run)
    return {
        "format":FORMAT,"generated_at":now(),"run_id":info.get("run_id"),"run_status":info.get("status"),
        "classification":"owner-question-open","turn":"ask-owner","heartbeat_state":"waiting",
        "owner_question_id":question_id,"heartbeat_suspended":True,
    }


def command_resume_owner(args: argparse.Namespace) -> dict[str, Any]:
    """Resume autonomous heartbeat transport after the Human answer was durably handled."""
    run=args.run_root.resolve(); info=dsd_task.load_run(run); loop=load_loop(run)
    current=loop.get("owner_wait") if isinstance(loop.get("owner_wait"),dict) else None
    if not current or not current.get("open"):
        return {
            "format":FORMAT,"generated_at":now(),"run_id":info.get("run_id"),"run_status":info.get("status"),
            "classification":"owner-question-closed","turn":"continue","heartbeat_state":"running",
            "owner_question_id":getattr(args,"question_id",None),"heartbeat_resumed":False,"already_resumed":True,
        }
    expected=str(current.get("question_id") or "")
    supplied=str(getattr(args,"question_id",None) or "")
    if supplied and supplied!=expected:
        raise ValueError(f"owner question mismatch: open={expected!r} supplied={supplied!r}")
    loop["last_owner_wait"]={**current,"open":False,"closed_at":now()}
    loop.pop("owner_wait",None); save_loop(run,loop)
    return {
        "format":FORMAT,"generated_at":now(),"run_id":info.get("run_id"),"run_status":info.get("status"),
        "classification":"owner-question-closed","turn":"continue","heartbeat_state":"running",
        "owner_question_id":expected,"heartbeat_resumed":True,
    }


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
    p.add_argument("--disk-sample-seconds", type=float, default=DEFAULT_DISK_SAMPLE_SECONDS)
    p = sub.add_parser("pulse"); p.add_argument("--run-root", type=Path, required=True); p.add_argument("--phase-id")
    p = sub.add_parser("ack-update"); p.add_argument("--run-root", type=Path, required=True); p.add_argument("--token", required=True)
    p = sub.add_parser("wait-owner"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--question-id",required=True)
    p = sub.add_parser("resume-owner"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--question-id")
    p = sub.add_parser("finish"); p.add_argument("--run-root", type=Path, required=True); p.add_argument("--phase-id"); p.add_argument("--reason", required=True)
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "tick": result = command_tick(args)
        elif args.command == "pulse": result = command_pulse(args)
        elif args.command == "ack-update": result = command_ack_update(args)
        elif args.command == "wait-owner": result = command_wait_owner(args)
        elif args.command == "resume-owner": result = command_resume_owner(args)
        elif args.command == "finish": result = command_finish(args)
        else: raise ValueError(args.command)
        print(json.dumps(result, sort_keys=True)); return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc), "command": getattr(args, "command", None)}), file=os.sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
