#!/usr/bin/env python3
"""Task-local control plane for T-BAG runs.

Each task owns its brief, state, attempts, workspace and review loop so independent
work can progress without one mutable global control record.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from _roles import DEFAULT_TIER, ESCALATION_LADDER, ROLE_NAMES
from _contract import allowed_source_changes, declared_worker_skill_tags, has_explicit_write_restriction, required_worktree_fixtures, role_writes_project
from _rules_snapshot import rules_revisions, verify_snapshot

FORMAT = "dsd-task-state-v2.1"
PLAN_FORMAT = "dsd-task-plan-v2.1"
RUN_FORMAT = "dsd-run-v2.2"
CONTROL_DIR = "TBag"
CACHE_DIR = "t-bag"
SUPPORTED_WORKER_DRIVERS = {"opencode", "codex"}
RUN_STATUSES = {"active", "completed", "human-blocked", "paused-by-user", "abandoned"}
STATUSES = {
    "planned", "ready", "active", "awaiting-review", "needs-fix", "needs-analysis",
    "blocked", "review-passed", "accepted", "integrated", "superseded", "recovery-required",
}
ATTEMPT_STATUSES = {
    "started", "gated", "report-recovery", "report-resume", "mutating-report-resume",
    "mutating-report-recovery", "integrity-failed", "stale-unresolved",
}
KINDS = {"analysis", "implementation", "verification"}
TIERS = {"analyst", "grunt"}
BASE_ROLES_BY_KIND = {
    "analysis": {"goal-planner", "plan-reviewer", "context-reviewer", "planner", "discovery", "phase-surveyor", "recovery", "phase-auditor"},
    "implementation": {"implementer"},
    "verification": {"verification", "evidence-clerk"},
}
ANALYST_ONLY_BASE_ROLES = {"goal-planner", "plan-reviewer", "context-reviewer", "planner", "discovery", "phase-surveyor", "recovery", "phase-auditor"}
CONTEXT_AUTHOR_ROLES = {"goal-planner", "planner", "discovery", "phase-surveyor", "recovery"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-.")
    if not value: raise ValueError("empty/unsafe identifier")
    return value


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise ValueError(f"expected JSON object: {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


@contextlib.contextmanager
def file_lock(path: Path, *, shared: bool = False):
    """Advisory run/task lock. Shared locks are used only for primary snapshots;
    integration takes the exclusive form so snapshots cannot observe a half-apply.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def run_file(run: Path) -> Path: return run / "run.json"
def phase_root(run: Path, phase: str) -> Path:
    name=slug(phase); phases=run/"phases"
    if phases.is_dir():
        for child in phases.iterdir():
            if child.is_dir() and child.name.casefold()==name.casefold() and child.name!=name:
                raise ValueError(f"phase id {name!r} collides with existing phase {child.name!r} on case-insensitive filesystems")
    return phases/name
def task_root(run: Path, phase: str, task: str) -> Path: return phase_root(run, phase) / "tasks" / slug(task)
def task_file(run: Path, phase: str, task: str) -> Path: return task_root(run, phase, task) / "task.json"


def load_run(run: Path) -> dict[str, Any]:
    path = run_file(run)
    if not path.is_file(): raise ValueError(f"run not initialized: {path}")
    data = load_json(path)
    if data.get("format") != RUN_FORMAT: raise ValueError(f"unsupported run format: {data.get('format')!r}")
    return data


def load_task(run: Path, phase: str, task: str) -> dict[str, Any]:
    path = task_file(run, phase, task)
    if not path.is_file(): raise ValueError(f"task not registered: {phase}/{task}")
    data = load_json(path)
    if data.get("format") != FORMAT: raise ValueError(f"unsupported task format: {data.get('format')!r}")
    return data


def dependency_satisfied(run: Path, phase: str, task_id: str, _seen: set[str] | None = None) -> bool:
    """Return whether one dependency obligation has been discharged.

    Supersession preserves the obligation: a predecessor is satisfied only when every
    recorded successor is itself satisfied. A superseded task without a successor is
    deliberately not green; that represents an abandoned obligation, not completion.
    """
    tid = slug(task_id)
    seen = set() if _seen is None else set(_seen)
    if tid in seen:
        return False
    seen.add(tid)
    dep = load_task(run, phase, tid)
    if dep.get("status") == "superseded":
        raw = dep.get("superseded_by")
        successors = [raw] if isinstance(raw, str) and raw.strip() else list(raw) if isinstance(raw, list) else []
        successors = [slug(str(item)) for item in successors if str(item).strip()]
        return bool(successors) and all(dependency_satisfied(run, phase, successor, seen) for successor in successors)
    if dep.get("requires_integration"):
        return dep.get("status") == "integrated"
    return dep.get("status") in {"accepted", "integrated"}




def superseded_workspace_retention(run: Path, phase: str, task: dict[str, Any]) -> dict[str, Any]:
    """Describe whether a superseded mutable workspace still protects successor work.

    Cleanup may reclaim a predecessor only after every recorded successor has integrated
    or one successor has durably captured the predecessor delta through ``carry_from``.
    This is deliberately derived from durable task records rather than a new retention
    state machine.
    """
    tid=slug(str(task.get("task_id") or ""))
    if str(task.get("status") or "")!="superseded":
        return {"retain":False,"successors":[],"integrated":[],"carry_captured_by":[]}
    raw=task.get("superseded_by")
    successors=[raw] if isinstance(raw,str) and raw.strip() else list(raw) if isinstance(raw,list) else []
    successors=[slug(str(x)) for x in successors if str(x).strip()]
    integrated=[]; captured=[]; missing=[]
    for sid in successors:
        try: successor=load_task(run,phase,sid)
        except ValueError:
            missing.append(sid); continue
        if successor.get("status")=="integrated": integrated.append(sid)
        if successor.get("carry_from")==tid:
            patch=Path(str(successor.get("carry_forward_patch") or ""))
            if patch.is_file(): captured.append(sid)
    all_integrated=bool(successors) and not missing and len(integrated)==len(successors)
    # A bare supersede with no recorded successor is explicit retirement/abandonment;
    # there is no successor carry-forward relation for cleanup to protect.
    safe=not successors or bool(captured) or all_integrated
    return {
        "retain":not safe,
        "successors":successors,
        "integrated":integrated,
        "carry_captured_by":captured,
        "missing_successors":missing,
        "reason":"no-recorded-successor" if not successors else "carry-forward-captured" if captured else "successors-integrated" if all_integrated else "successor-still-needs-workspace-or-carry-forward",
    }

def readiness(run: Path, phase: str, task: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = []
    for dep in task.get("dependencies", []):
        try:
            if not dependency_satisfied(run, phase, dep): missing.append(dep)
        except ValueError:
            missing.append(dep)
    return (not missing, missing)


def pid_alive(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0); return True
    except OSError:
        return False


def attempt_pids(attempt: dict[str, Any]) -> set[int]:
    pids={attempt.get(k) for k in ("worker_pid","monitor_pid","launcher_pid") if isinstance(attempt.get(k),int) and attempt.get(k)>0}
    event=Path(str(attempt.get("event_dir") or ""))
    detail=event/"attempt.json"
    if detail.is_file():
        try:
            data=load_json(detail)
            pids.update(data.get(k) for k in ("worker_pid","launcher_pid") if isinstance(data.get(k),int) and data.get(k)>0)
        except (OSError,ValueError,json.JSONDecodeError):
            pass
    return {int(pid) for pid in pids}

def attempt_is_live(attempt: dict[str, Any]) -> bool:
    event=Path(str(attempt.get("event_dir") or ""))
    if event.is_dir() and (event/"terminal.json").is_file(): return False
    return any(pid_alive(pid) for pid in attempt_pids(attempt))

def attempt_is_unresolved(attempt: dict[str, Any]) -> bool:
    # sweep-stale is an explicit durable disposition for a dead launcher/process.
    # The missing terminal stays as evidence, but must not poison every later launch.
    if attempt.get("status") == "stale-unresolved":
        return False
    event=Path(str(attempt.get("event_dir") or ""))
    return event.is_dir() and not (event/"terminal.json").is_file()

def task_has_live_attempt(task: dict[str, Any]) -> bool:
    return any(isinstance(attempt,dict) and attempt_is_live(attempt) for attempt in task.get("attempts",[]))

def task_has_unresolved_attempt(task: dict[str, Any]) -> bool:
    return any(isinstance(attempt,dict) and attempt_is_unresolved(attempt) for attempt in task.get("attempts",[]))


def validate_analyst_plan_source(run: Path, phase: str, graph_path: Path) -> dict[str, Any]:
    try:
        rel = graph_path.resolve().relative_to(run.resolve())
    except ValueError as exc:
        raise ValueError("registered task plans must come from a gated Analyst attempt under this run") from exc
    parts = rel.parts
    # phases/<phase>/tasks/<source>/attempts/<attempt>/plan/task-graph.json
    if len(parts) != 8 or parts[0] != "phases" or parts[1] != phase or parts[2] != "tasks" or parts[4] != "attempts" or parts[6] != "plan" or parts[7] != "task-graph.json":
        raise ValueError("task plan must be <run>/phases/<phase>/tasks/<source-task>/attempts/<analyst-attempt>/plan/task-graph.json")
    source_id = parts[3]; event = run / Path(*parts[:6])
    source = load_task(run, phase, source_id)
    attempt = next((a for a in source.get("attempts", []) if isinstance(a, dict) and Path(str(a.get("event_dir") or "")).resolve() == event.resolve()), None)
    if attempt is None or attempt.get("status") != "gated" or attempt.get("tier") != "analyst" or attempt.get("role") not in {"planner", "discovery", "phase-surveyor", "recovery"}:
        raise ValueError("task plan source must be a gated Analyst Planner/Discovery/Phase-Surveyor/Recovery attempt")
    report = event / "report.md"
    if not report.is_file(): raise ValueError("Analyst plan source report is missing")
    report_resolved = str(report.resolve())
    accepted = source.get("status") in {"accepted", "integrated"} and str(source.get("accepted_report") or "") == report_resolved
    analysis = source.get("last_analysis") if isinstance(source.get("last_analysis"), dict) else {}
    approved_replan = analysis.get("outcome") in {"replan","replan-resume"} and str(analysis.get("report") or "") == report_resolved
    if not (accepted or approved_replan):
        raise ValueError("Analyst task graph is mechanically gated but has not been approved: accept the Analyst result, or record analysis-result --outcome replan/replan-resume for a replacement plan")
    return {"source_task_id": source_id, "source_attempt": str(event), "source_report": report_resolved}


def validate_task_shape(kind: str, role: str, tier: str, requires_integration: bool) -> None:
    allowed = BASE_ROLES_BY_KIND.get(kind, set())
    if role not in allowed:
        raise ValueError(f"{kind} task cannot use base role {role!r}; allowed roles: {sorted(allowed)}")
    if role in ANALYST_ONLY_BASE_ROLES and tier != "analyst":
        raise ValueError(f"{role} tasks require Analyst tier")
    if role in {"verification", "evidence-clerk"} and tier != "grunt":
        raise ValueError(f"{role} tasks use the Grunt tier; substantial reasoning belongs in Analyst Discovery/Phase Audit")
    if kind == "implementation" and tier != "grunt":
        raise ValueError("implementation tasks use the Grunt tier; unresolved/architectural work belongs in a separate Analyst task")
    if kind == "implementation" and not requires_integration:
        raise ValueError("implementation tasks must require integration and fresh Review")
    if kind in {"analysis", "verification"} and requires_integration:
        raise ValueError(f"{kind} tasks are result-producing tasks and must not integrate project changes; use an implementation task for durable project mutation")


def normalize_task_spec(item: dict[str, Any], graph_dir: Path) -> dict[str, Any]:
    if not isinstance(item, dict): raise ValueError("each task plan entry must be an object")
    task_id = slug(str(item.get("task_id") or ""))
    kind = str(item.get("kind") or "").lower()
    if kind not in KINDS: raise ValueError(f"{task_id}: kind must be one of {sorted(KINDS)}")
    default_role = "implementer" if kind == "implementation" else "verification" if kind == "verification" else "discovery"
    role = str(item.get("role") or default_role).lower()
    if role not in ROLE_NAMES: raise ValueError(f"{task_id}: unknown role {role!r}")
    if role in {"goal-planner","plan-reviewer","context-reviewer"}:
        raise ValueError(f"{task_id}: role {role!r} is a control-plane bootstrap/review role and cannot appear in an ordinary phase task graph")
    tier = str(item.get("tier") or DEFAULT_TIER[role]).lower()
    if tier not in TIERS: raise ValueError(f"{task_id}: tier must be analyst or grunt")
    brief_raw = item.get("brief")
    if not isinstance(brief_raw, str) or not brief_raw.strip(): raise ValueError(f"{task_id}: brief is required")
    brief_rel = Path(brief_raw)
    if brief_rel.is_absolute(): raise ValueError(f"{task_id}: plan brief must be relative to the Analyst plan directory")
    brief = (graph_dir / brief_rel).resolve()
    try: brief.relative_to(graph_dir.resolve())
    except ValueError as exc: raise ValueError(f"{task_id}: plan brief escapes the Analyst plan directory: {brief_raw}") from exc
    if not brief.is_file(): raise ValueError(f"{task_id}: brief missing: {brief}")
    deps_raw = item.get("dependencies", [])
    if not isinstance(deps_raw, list): raise ValueError(f"{task_id}: dependencies must be an array")
    deps = [slug(str(x)) for x in deps_raw]
    if task_id in deps: raise ValueError(f"{task_id}: task cannot depend on itself")
    requires_integration = bool(item.get("requires_integration", kind == "implementation"))
    validate_task_shape(kind, role, tier, requires_integration)
    supersedes_raw=item.get("supersedes", [])
    if not isinstance(supersedes_raw,list): raise ValueError(f"{task_id}: supersedes must be an array")
    supersedes=list(dict.fromkeys(slug(str(x)) for x in supersedes_raw))
    carry_raw=item.get("carry_from")
    carry_from=slug(str(carry_raw)) if carry_raw not in {None,""} else None
    return {
        "task_id": task_id, "kind": kind, "role": role, "tier": tier, "brief": brief,
        "dependencies": list(dict.fromkeys(deps)), "requires_integration": requires_integration,
        "supersedes": supersedes, "carry_from": carry_from,
    }


def assert_acyclic(existing: dict[str, list[str]], proposed: dict[str, list[str]]) -> None:
    graph = {**existing, **proposed}
    seen: set[str] = set(); active: set[str] = set()
    def visit(node: str):
        if node in active: raise ValueError(f"dependency cycle includes {node}")
        if node in seen: return
        active.add(node)
        for dep in graph.get(node, []):
            if dep in graph: visit(dep)
        active.remove(node); seen.add(node)
    for node in graph: visit(node)


def _runtime_spec(driver: str | None, model: str | None) -> dict[str, Any] | None:
    driver=(driver or "").strip(); model=(model or "").strip()
    if bool(driver) != bool(model):
        raise ValueError("worker runtime requires both driver and model, or neither")
    if not driver: return None
    return {"driver": driver, "model": model, "options": {}}


def runtime_config(run_info: dict[str, Any], tier: str) -> dict[str, Any] | None:
    runtimes=run_info.get("worker_runtimes") if isinstance(run_info.get("worker_runtimes"),dict) else {}
    value=runtimes.get(tier)
    return value if isinstance(value,dict) and value.get("driver") and value.get("model") else None


def missing_runtime_tiers(run_info: dict[str, Any]) -> list[str]:
    return [tier for tier in ("analyst","grunt") if runtime_config(run_info,tier) is None]


def escalation_enabled(run_info: dict[str, Any]) -> bool:
    """Whether automatic Grunt→Analyst→Human escalation routing is enabled."""
    return bool(run_info.get("escalation_enabled", True))


def require_escalation_enabled(run: Path) -> None:
    if not escalation_enabled(load_run(run)):
        raise ValueError(
            "ESCALATION_DISABLED: this run does not auto-route ESCALATE outcomes; "
            "enable escalation or handle the blocked work explicitly"
        )


def _default_runtime_root(project: Path, run_id: str) -> Path:
    project_key = slug(str(project).replace(os.sep, "__"))
    return (Path.home() / ".cache" / CACHE_DIR / "projects" / project_key / slug(run_id)).resolve()


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    project = args.project_root.resolve(); run = args.run_root.resolve()
    if not project.is_dir(): raise ValueError(f"project root missing: {project}")
    try: run.relative_to(project / CONTROL_DIR)
    except ValueError as exc: raise ValueError(f"run root must live under PROJECT/{CONTROL_DIR}") from exc
    run.mkdir(parents=True, exist_ok=True)
    path = run_file(run)
    if path.exists():
        data = load_run(run)
        if Path(str(data.get("project_root") or "")).resolve()!=project or data.get("run_id")!=slug(args.run_id):
            raise ValueError("existing run identity does not match supplied project/run-id")
        runtime=Path(str(data["runtime_root"])).resolve()
        # Legacy runs predate runtime ownership markers. Auto-backfill only when the
        # durable runtime path is exactly T-BAG's canonical per-project/per-run path;
        # never convert an arbitrary historical custom directory into purge authority.
        marker=runtime/".tbag-run-owner.json"
        if not marker.exists() and runtime==_default_runtime_root(project,data["run_id"]):
            runtime.mkdir(parents=True,exist_ok=True)
            write_json(marker, {"format":"tbag-runtime-owner-v1","run_root":str(run),"project_root":str(project),"run_id":data["run_id"]})
        return {**data, "missing_runtime_config": missing_runtime_tiers(data)}
    runtime = Path(args.runtime_root).expanduser().resolve() if args.runtime_root else _default_runtime_root(project,args.run_id)
    owner_marker=runtime/".tbag-run-owner.json"
    if runtime.exists() and any(runtime.iterdir()):
        if not owner_marker.is_file():
            raise ValueError(f"runtime_root already contains data but has no T-BAG ownership marker; use a dedicated empty run directory: {runtime}")
        owner=load_json(owner_marker)
        if owner.get("format")!="tbag-runtime-owner-v1" or owner.get("run_id")!=slug(args.run_id) or Path(str(owner.get("project_root") or "")).resolve()!=project or Path(str(owner.get("run_root") or "")).resolve()!=run:
            raise ValueError(f"runtime_root is owned by a different run/project: {runtime}")
    if args.max_workers < 1: raise ValueError("--max-workers must be >= 1")
    worker_runtimes = {
        "grunt": _runtime_spec(getattr(args,"grunt_driver",None),getattr(args,"grunt_model",None)),
        "analyst": _runtime_spec(getattr(args,"analyst_driver",None),getattr(args,"analyst_model",None)),
    }
    for tier, spec in worker_runtimes.items():
        if spec is not None and spec["driver"] not in SUPPORTED_WORKER_DRIVERS:
            raise ValueError(
                f"worker driver {spec['driver']!r} configured for {tier} is not wired; "
                f"supported technical-worker drivers: {sorted(SUPPORTED_WORKER_DRIVERS)}"
            )
    data = {
        "format": RUN_FORMAT, "run_id": slug(args.run_id), "project_root": str(project),
        "runtime_root": str(runtime), "created_at": now(), "status": "active",
        "max_workers": args.max_workers,
        "escalation_enabled": getattr(args, "escalation", "on") == "on",
        "worker_runtimes": worker_runtimes,
    }
    runtime.mkdir(parents=True, exist_ok=True)
    write_json(owner_marker, {
        "format":"tbag-runtime-owner-v1","run_root":str(run),"project_root":str(project),"run_id":data["run_id"]
    })
    write_json(path, data); return {**data, "missing_runtime_config": missing_runtime_tiers(data)}


def command_runtime_status(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); info=load_run(run)
    return {
        "run_id":info["run_id"],
        "status":info.get("status","active"),
        "escalation_enabled":escalation_enabled(info),
        "worker_runtimes":info.get("worker_runtimes",{}),
        "missing_runtime_config":missing_runtime_tiers(info),
        "supported_worker_drivers":sorted(SUPPORTED_WORKER_DRIVERS),
    }


def command_set_runtime(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); path=run_file(run)
    with file_lock(run/".run.lock"):
        info=load_run(run); spec=_runtime_spec(args.driver,args.model)
        assert spec is not None
        if args.driver not in SUPPORTED_WORKER_DRIVERS and not args.allow_unwired_driver:
            raise ValueError(f"worker driver {args.driver!r} is not wired; supported technical-worker drivers: {sorted(SUPPORTED_WORKER_DRIVERS)}")
        runtimes=info.get("worker_runtimes") if isinstance(info.get("worker_runtimes"),dict) else {}
        runtimes=dict(runtimes); runtimes[args.tier]=spec; info["worker_runtimes"]=runtimes; info["updated_at"]=now(); write_json(path,info)
    return {"tier":args.tier,"runtime":spec,"missing_runtime_config":missing_runtime_tiers(info)}


def command_set_escalation(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); path=run_file(run)
    with file_lock(run/".run.lock"):
        info=load_run(run); info["escalation_enabled"]=args.mode=="on"; info["updated_at"]=now(); write_json(path,info)
    return {"run_id":info["run_id"],"escalation_enabled":info["escalation_enabled"]}


def iter_run_tasks(run: Path):
    phases=run/"phases"
    if not phases.is_dir(): return
    for path in phases.glob("*/tasks/*/task.json"):
        try: yield load_json(path)
        except (OSError,ValueError,json.JSONDecodeError): continue


def task_can_advance_without_human(run: Path, task: dict[str, Any]) -> bool:
    status=str(task.get("status") or "")
    if status in {"integrated","superseded"}: return False
    if status=="accepted": return bool(task.get("requires_integration"))
    if status=="blocked": return False
    if status in {"planned","ready"}:
        try:
            ok,_=readiness(run,str(task.get("phase_id") or ""),task)
            return ok
        except ValueError:
            return False
    return True


def command_set_run_status(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); path=run_file(run)
    with file_lock(run/".run.lock"):
        info=load_run(run)
        if args.status not in RUN_STATUSES: raise ValueError(f"unsupported run status: {args.status}")
        if args.status!="active":
            live=[t.get("task_id") for t in iter_run_tasks(run) if task_has_live_attempt(t)]
            if live: raise ValueError(f"cannot set run status {args.status!r} while worker attempts are live: {live[:5]}")
        if args.status=="human-blocked":
            tasks=list(iter_run_tasks(run))
            blocked=any(
                t.get("status")=="blocked" and isinstance(t.get("last_escalation"),dict) and t["last_escalation"].get("target")=="human"
                for t in tasks
            )
            if not blocked: raise ValueError("human-blocked run status requires at least one Human-targeted blocked task")
            advancing=[str(t.get("task_id")) for t in tasks if task_can_advance_without_human(run,t)]
            if advancing:
                raise ValueError(f"run still has authorized work that can advance without the Human decision: {advancing[:5]}")
        info["status"]=args.status; info["updated_at"]=now()
        if getattr(args,"reason",None): info["status_reason"]=args.reason
        else: info.pop("status_reason",None)
        write_json(path,info)
    return {"run_id":info["run_id"],"status":info["status"],"reason":info.get("status_reason")}



def _command_register_direct_unlocked(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); load_run(run); phase=slug(args.phase_id); tid=slug(args.task_id)
    state_path=task_file(run,phase,tid)
    if state_path.exists(): raise ValueError(f"task already exists: {phase}/{tid}")
    task_dir=task_root(run,phase,tid)
    if task_dir.exists():
        raise ValueError(f"task directory already exists without registered state: {task_dir}; do not pre-create T-BAG task directories—keep the source brief outside the run task directory")
    brief=args.brief.resolve()
    if not brief.is_file(): raise ValueError(f"brief missing: {brief}")
    # Direct registration has no task-graph preflight, so still validate every
    # mechanically parsed contract section before freezing the brief read-only.
    brief_text=brief.read_text(encoding="utf-8",errors="replace")
    allowed_source_changes(brief_text); declared_worker_skill_tags(brief_text); required_worktree_fixtures(brief_text)
    kind=args.kind; default_role="implementer" if kind=="implementation" else "verification" if kind=="verification" else "discovery"; role=args.role or default_role
    if role not in ROLE_NAMES: raise ValueError(f"unknown role: {role}")
    tier=args.tier or DEFAULT_TIER[role]
    deps=[slug(x) for x in (args.dependency or [])]
    for dep in deps:
        if not task_file(run,phase,dep).is_file(): raise ValueError(f"unknown dependency: {dep}")
    requires_integration = args.requires_integration if args.requires_integration is not None else (kind=="implementation")
    validate_task_shape(kind, role, tier, requires_integration)
    owner_authority_raw=getattr(args,"owner_authority",None)
    owner_authority=Path(owner_authority_raw).resolve() if owner_authority_raw else None
    if owner_authority is not None and not owner_authority.is_file():
        raise ValueError(f"owner authority missing: {owner_authority}")
    direct_implementation = kind=="implementation" and role=="implementer" and tier=="grunt" and requires_integration
    direct_analysis = kind=="analysis" and tier=="analyst" and role in BASE_ROLES_BY_KIND["analysis"]
    if direct_implementation and owner_authority is None:
        raise ValueError("direct implementation requires --owner-authority with the explicit owner decision; otherwise obtain an Analyst task graph")
    if not (direct_analysis or direct_implementation):
        raise ValueError("register-direct permits Analyst analysis/control tasks or explicit owner-authorized Implementer tasks; verification and inferred implementation must come from an approved Analyst task graph")
    if direct_analysis and owner_authority is not None:
        raise ValueError("--owner-authority is reserved for explicit owner-directed implementation registration")
    reviews_task = slug(args.reviews_task) if getattr(args, "reviews_task", None) else None
    if role == "plan-reviewer":
        if phase != "bootstrap":
            raise ValueError("Plan Reviewer is only valid in the mechanical bootstrap phase; outside bootstrap, accept the Analyst result and use preflight-plan/register-plan for its emitted graph")
        if not reviews_task:
            raise ValueError("Plan Reviewer requires --reviews-task pointing to the Goal-Planner task")
        target = load_task(run, phase, reviews_task)
        if target.get("role") != "goal-planner" or target.get("kind") != "analysis":
            raise ValueError("Plan Reviewer --reviews-task must identify a Goal-Planner analysis task")
    elif role == "context-reviewer":
        if not reviews_task:
            raise ValueError("Context Reviewer requires --reviews-task pointing to the Analyst context-authoring task")
        target=load_task(run,phase,reviews_task)
        if target.get("kind")!="analysis" or target.get("role") not in CONTEXT_AUTHOR_ROLES:
            raise ValueError("Context Reviewer --reviews-task must identify a Goal-Planner/Planner/Discovery/Phase-Surveyor/Recovery Analyst task")
    elif reviews_task:
        raise ValueError("--reviews-task is only valid for Plan Reviewer/Context Reviewer tasks")
    if role in {"plan-reviewer","context-reviewer"}:
        tasks_dir=phase_root(run,phase)/"tasks"
        if tasks_dir.is_dir():
            for existing in tasks_dir.glob("*/task.json"):
                data=load_json(existing)
                if data.get("role")==role and data.get("reviews_task")==reviews_task:
                    raise ValueError(f"task {reviews_task!r} already has {role} task {data.get('task_id')!r}; reuse that task with fresh attempts")
    if role == "goal-planner" and phase != "bootstrap":
        raise ValueError("Goal Planner is only valid in the mechanical bootstrap phase")
    root=task_dir; root.mkdir(parents=True,exist_ok=False); copy=root/"brief.md"; shutil.copyfile(brief,copy); copy.chmod(0o444)
    task={"format":FORMAT,"phase_id":phase,"task_id":tid,"kind":kind,"role":role,"tier":tier,"brief":str(copy),"plan_source":None,"dependencies":deps,"requires_integration":requires_integration,"status":"planned","attempts":[],"review_rounds":0,"review_history":[],"created_at":now()}
    if reviews_task: task["reviews_task"] = reviews_task
    if direct_implementation and owner_authority is not None:
        authority_copy=root/"authority"/"owner-direct.md"; authority_copy.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(owner_authority,authority_copy); authority_copy.chmod(0o444); task["direct_owner_authority"]=str(authority_copy)
    write_json(state_path,task); result={"phase_id":phase,"registered":[tid],"direct":True}
    if task.get("direct_owner_authority"): result["owner_authority"]=task["direct_owner_authority"]
    return result

def command_register_direct(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id)
    with file_lock(phase_root(run,phase)/".tasks.lock"):
        return _command_register_direct_unlocked(args)


def _path_within_prefix(path: str, prefix: str) -> bool:
    path=path.replace("\\","/").strip("/"); prefix=prefix.replace("\\","/").strip("/")
    return path==prefix or path.startswith(prefix+"/")


def _carry_workspace(run: Path, phase: str, source_task: str) -> dict[str, Any]:
    path=task_root(run,phase,source_task)/"workspace.json"
    if not path.is_file():
        raise ValueError(f"carry_from source {source_task} has no workspace to preserve")
    ws=load_json(path)
    if ws.get("mode","isolated-worktree")!="isolated-worktree":
        raise ValueError(f"carry_from source {source_task} must own an isolated mutable worktree")
    worktree=Path(str(ws.get("worktree") or ""))
    baseline=str(ws.get("baseline_branch") or "")
    if not worktree.is_dir() or not baseline:
        raise ValueError(f"carry_from source {source_task} workspace is incomplete or already reclaimed")
    return ws


def snapshot_carry_delta(run: Path, phase: str, source_task: str, destination: Path) -> dict[str, Any]:
    """Freeze only predecessor movement since its task baseline without touching its real index."""
    delta=inspect_carry_delta(run,phase,source_task)
    destination.parent.mkdir(parents=True,exist_ok=True); destination.write_bytes(delta["patch_bytes"])
    return {
        "source_task":source_task,"source_baseline":delta["source_baseline"],
        "changed_paths":delta["changed_paths"],"patch":str(destination.resolve()),"captured_at":now(),
    }


def inspect_carry_delta(run: Path, phase: str, source_task: str) -> dict[str, Any]:
    """Inspect predecessor movement since its task baseline without mutating durable state."""
    ws=_carry_workspace(run,phase,source_task); worktree=Path(ws["worktree"]).resolve(); baseline=str(ws["baseline_branch"])
    with tempfile.TemporaryDirectory(prefix="carry-index-") as tmp:
        index=Path(tmp)/"index"; env=os.environ.copy(); env["GIT_INDEX_FILE"]=str(index)
        def git_bytes(*argv: str, check: bool=True) -> subprocess.CompletedProcess[bytes]:
            cp=subprocess.run(["git",*argv],cwd=worktree,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
            if check and cp.returncode:
                raise ValueError(f"cannot snapshot carry_from {source_task}: git {' '.join(argv)} failed: {cp.stderr.decode(errors='replace')[:500]}")
            return cp
        git_bytes("read-tree",baseline)
        git_bytes("add","-A","--",".")
        patch=git_bytes("diff","--cached","--binary",baseline,"--",".").stdout
        raw=git_bytes("diff","--cached","--name-only","-z","--no-renames",baseline,"--",".").stdout
    changed=[item.decode("utf-8",errors="surrogateescape") for item in raw.split(b"\0") if item]
    if not patch and not changed:
        raise ValueError(f"carry_from source {source_task} has no durable project delta beyond its task baseline; use supersedes without carry_from")
    return {"source_task":source_task,"source_baseline":baseline,"changed_paths":changed,"patch_bytes":patch}


def _plan_authoring_context(run: Path, phase: str, graph_path: Path) -> dict[str, Any] | None:
    """Identify the live Analyst attempt authoring this graph, when mechanically provable.

    Preflight is intentionally callable before the Analyst exits. That authoring
    read-only attempt must not block supersession/carry checks against its own task,
    while every other live/unresolved attempt remains a blocker.
    """
    try: rel=graph_path.resolve().relative_to(run.resolve())
    except ValueError: return None
    parts=rel.parts
    if len(parts)!=8 or parts[0]!="phases" or parts[1]!=phase or parts[2]!="tasks" or parts[4]!="attempts" or parts[6]!="plan" or parts[7]!="task-graph.json":
        return None
    source_id=parts[3]; event=run/Path(*parts[:6])
    try: source=load_task(run,phase,source_id)
    except ValueError: return None
    attempt=next((a for a in source.get("attempts",[]) if isinstance(a,dict) and Path(str(a.get("event_dir") or "")).resolve()==event.resolve()),None)
    if attempt is None or attempt_tier(attempt)!="analyst" or str(attempt.get("role") or "") not in {"planner","discovery","phase-surveyor","recovery","phase-auditor"}:
        return None
    return {"task_id":source_id,"event_dir":event.resolve(),"attempt":attempt}


def _attempt_is_authoring_graph(attempt: dict[str, Any], authoring: dict[str, Any] | None, task_id: str) -> bool:
    if not authoring or authoring.get("task_id")!=task_id: return False
    event=Path(str(attempt.get("event_dir") or ""))
    try: return event.resolve()==Path(authoring["event_dir"]).resolve()
    except Exception: return False


def preflight_plan_contents(run: Path, phase: str, graph_path: Path) -> list[dict[str, Any]]:
    graph_path=graph_path.resolve(); graph=load_json(graph_path); authoring=_plan_authoring_context(run,phase,graph_path)
    if graph.get("format") != PLAN_FORMAT: raise ValueError(f"plan format must be {PLAN_FORMAT}")
    raw_tasks = graph.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks: raise ValueError("plan tasks must be a non-empty array")
    rederive_raw=graph.get("rederive_from_primary",[])
    if not isinstance(rederive_raw,list): raise ValueError("plan rederive_from_primary must be an array when present")
    rederive_from_primary=list(dict.fromkeys(slug(str(x)) for x in rederive_raw))
    specs=[]; errors=[]
    for index,item in enumerate(raw_tasks):
        try:
            specs.append(normalize_task_spec(item, graph_path.parent))
        except (ValueError,TypeError,KeyError) as exc:
            raw_id=str(item.get("task_id") or "?") if isinstance(item,dict) else "?"
            errors.append(f"tasks[{index}] {raw_id}: {exc}")
    ids = [x["task_id"] for x in specs]
    if len(ids) != len(set(ids)): errors.append("plan contains duplicate task IDs")
    folded=[x.casefold() for x in ids]
    if len(folded) != len(set(folded)): errors.append("plan contains task IDs that collide on case-insensitive filesystems")
    carry_sources: dict[str,list[str]]={}
    supersession_sources: dict[str,list[str]]={}
    for spec in specs:
        overlap=set(spec["dependencies"]) & set(spec["supersedes"])
        if overlap: errors.append(f"{spec['task_id']}: replacement task cannot depend on task(s) it supersedes: {sorted(overlap)}")
        for source in spec["supersedes"]: supersession_sources.setdefault(source,[]).append(spec["task_id"])
        carry=spec.get("carry_from")
        if carry:
            carry_sources.setdefault(carry,[]).append(spec["task_id"])
            if spec["kind"]!="implementation": errors.append(f"{spec['task_id']}: carry_from is only valid for implementation tasks")
            if carry not in spec["supersedes"]: errors.append(f"{spec['task_id']}: carry_from {carry} must also appear in supersedes")
    for source,new_ids in carry_sources.items():
        if len(new_ids)>1: errors.append(f"carry_from source {source} is claimed by multiple replacements {new_ids}; split/refactor explicitly instead of duplicating one mutable delta")
    unknown_rederive=[source for source in rederive_from_primary if source not in supersession_sources]
    if unknown_rederive:
        errors.append(f"rederive_from_primary names predecessor(s) not superseded by this graph: {unknown_rederive}")
    both=sorted(set(rederive_from_primary) & set(carry_sources))
    if both:
        errors.append(f"predecessor delta disposition is contradictory; choose carry_from or rederive_from_primary, not both: {both}")
    existing_deps: dict[str, list[str]] = {}
    tasks_dir = phase_root(run, phase) / "tasks"
    if tasks_dir.is_dir():
        for path in tasks_dir.glob("*/task.json"):
            t = load_json(path); existing_deps[str(t.get("task_id"))] = list(t.get("dependencies", []))
    existing_ids=set(existing_deps)
    existing_folded={x.casefold():x for x in existing_ids}
    for tid in ids:
        collision=existing_folded.get(tid.casefold())
        if collision is not None and collision != tid:
            errors.append(f"task id {tid!r} collides with existing task {collision!r} on case-insensitive filesystems")
    all_known = existing_ids | set(ids)
    for spec in specs:
        unknown = [d for d in spec["dependencies"] if d not in all_known]
        if unknown: errors.append(f"{spec['task_id']}: unknown dependencies {unknown}")
    try:
        assert_acyclic(existing_deps, {x["task_id"]: x["dependencies"] for x in specs})
    except ValueError as exc:
        errors.append(str(exc))
    project_root=Path(load_run(run)["project_root"]).resolve()
    frozen_skill_ids: set[str] | None = None
    revisions = rules_revisions(run)
    if revisions:
        frozen_skill_ids = set(verify_snapshot(revisions[-1]).get("worker_skills", {}))
    for spec in specs:
        if task_file(run, phase, spec["task_id"]).exists():
            errors.append(f"task already exists: {phase}/{spec['task_id']}; revise by creating a new task ID and superseding the old one")
        try:
            brief_text=Path(spec["brief"]).read_text(encoding="utf-8",errors="replace")
            allowed_source_changes(brief_text)
            requested_skills = declared_worker_skill_tags(brief_text)
            if frozen_skill_ids is not None:
                unknown_skills = sorted(set(requested_skills) - frozen_skill_ids)
                if unknown_skills:
                    role_confusions = [name for name in unknown_skills if name.removeprefix("dsd-") in ROLE_NAMES or name in ROLE_NAMES]
                    hint = f"; role name(s) used as worker skill: {role_confusions}" if role_confusions else ""
                    errors.append(f"{spec['task_id']}: unknown worker skill(s) for current worker-rules revision: {unknown_skills}{hint}")
            for rel in required_worktree_fixtures(brief_text):
                src=project_root/rel
                if not src.exists() and not src.is_symlink():
                    errors.append(f"{spec['task_id']}: required worktree fixture is absent from primary checkout: {rel}")
                    continue
                ignored=subprocess.run(["git","check-ignore","-q","--",rel],cwd=project_root,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,check=False).returncode==0
                if not ignored:
                    errors.append(f"{spec['task_id']}: Required worktree fixtures must name Git-ignored inputs absent from normal worktrees; {rel} is not ignored")
        except (OSError,ValueError) as exc:
            errors.append(f"{spec['task_id']}: brief mechanical validation failed: {exc}")
        for old in spec["supersedes"]:
            old_path = task_file(run, phase, old)
            if not old_path.is_file():
                errors.append(f"{spec['task_id']}: cannot supersede unknown task {old}")
                continue
            old_state = load_json(old_path)
            if old_state.get("status") == "integrated":
                errors.append(f"{spec['task_id']}: cannot supersede already-integrated task {old}; create an amending task that depends on the integrated result")
            blocking_live=[a for a in old_state.get("attempts",[]) if isinstance(a,dict) and attempt_is_live(a) and not _attempt_is_authoring_graph(a,authoring,old)]
            if blocking_live:
                errors.append(f"{spec['task_id']}: cannot supersede live task {old}")
            if spec.get("carry_from")==old:
                if old_state.get("status") == "superseded":
                    raw_successors=old_state.get("superseded_by")
                    recorded=[raw_successors] if isinstance(raw_successors,str) and raw_successors.strip() else list(raw_successors) if isinstance(raw_successors,list) else []
                    recorded=[slug(str(x)) for x in recorded if str(x).strip()]
                    if spec["task_id"] not in recorded:
                        errors.append(f"{spec['task_id']}: already-superseded predecessor {old} names different successor(s) {recorded}; only its recorded successor may capture the still-retained delta")
                    retention=superseded_workspace_retention(run,phase,old_state)
                    if retention.get("carry_captured_by"):
                        errors.append(f"{spec['task_id']}: predecessor {old} carry-forward is already captured by {retention['carry_captured_by']}")
                blocking_unresolved=[a for a in old_state.get("attempts",[]) if isinstance(a,dict) and attempt_is_unresolved(a) and not _attempt_is_authoring_graph(a,authoring,old)]
                if blocking_unresolved:
                    errors.append(f"{spec['task_id']}: cannot carry_from unresolved predecessor attempt {old}; reconcile/recover it first")
                try: _carry_workspace(run,phase,old)
                except ValueError as exc: errors.append(f"{spec['task_id']}: {exc}")
    # A replacement graph must never silently drop retained implementation work.
    # If a superseded implementation owns (or may own) an unintegrated delta, the
    # graph must choose exactly one disposition: carry it into one successor, or
    # explicitly re-derive the replacement work from current primary.
    for old,new_ids in supersession_sources.items():
        if old in carry_sources or old in rederive_from_primary:
            continue
        old_path=task_file(run,phase,old)
        if not old_path.is_file():
            continue  # the ordinary unknown-task validation above owns this failure
        old_state=load_json(old_path)
        if old_state.get("kind")!="implementation" or not old_state.get("requires_integration"):
            continue
        workspace_file=task_root(run,phase,old)/"workspace.json"
        if not workspace_file.is_file():
            writer_attempts=[a for a in old_state.get("attempts",[]) if isinstance(a,dict) and str(a.get("role") or "") in {"implementer","fixer"}]
            if not writer_attempts:
                continue  # no mutating worker ever owned a workspace/delta
        try:
            delta=inspect_carry_delta(run,phase,old)
        except ValueError as exc:
            text=str(exc)
            if "has no durable project delta beyond its task baseline" in text:
                continue
            errors.append(
                f"replacement(s) {new_ids} supersede {old}, but T-BAG cannot prove the predecessor has no retained delta ({text}). "
                f"Choose carry_from: {old} on exactly one replacement, or add {old} to graph-level rederive_from_primary to explicitly start clean."
            )
            continue
        preview=delta.get("changed_paths",[])[:6]
        errors.append(
            f"replacement(s) {new_ids} supersede {old}, which retains an unintegrated delta ({len(delta.get('changed_paths',[]))} path(s), e.g. {preview}). "
            f"Choose carry_from: {old} on exactly one replacement, or add {old} to graph-level rederive_from_primary to explicitly re-derive from current primary."
        )
    if errors:
        raise ValueError("plan preflight failed:\n- " + "\n- ".join(errors))

    return specs


def command_preflight_plan(args: argparse.Namespace) -> dict[str, Any]:
    """Validate an Analyst-authored graph/brief set without registering anything.

    Graph-authoring workers run this themselves before final handoff so mechanical
    selector/path/fixture errors return to the authoring session rather than becoming
    parent-side patch work.
    """
    run=args.run_root.resolve(); load_run(run); phase=slug(args.phase_id); graph_path=args.plan.resolve()
    specs=preflight_plan_contents(run,phase,graph_path)
    return {"valid":True,"phase_id":phase,"plan":str(graph_path),"task_count":len(specs),"task_ids":[x["task_id"] for x in specs]}


def _command_register_plan_unlocked(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve(); load_run(run); phase = slug(args.phase_id)
    graph_path = args.plan.resolve(); source = validate_analyst_plan_source(run, phase, graph_path)
    specs = preflight_plan_contents(run, phase, graph_path)

    # Freeze explicit predecessor carryover before changing predecessor lifecycle state.
    # The snapshot lives under the replacement task record, so later predecessor cleanup
    # cannot erase the authority-approved delta the replacement is meant to continue.
    carry_snapshots: dict[str,dict[str,Any]]={}
    staging_parent=phase_root(run,phase); staging_parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".carry-staging-",dir=str(staging_parent)) as staging_raw:
        staging=Path(staging_raw)
        for spec in specs:
            carry=spec.get("carry_from")
            if not carry: continue
            meta=snapshot_carry_delta(run,phase,carry,staging/f"{spec['task_id']}.patch")
            brief_text=Path(spec["brief"]).read_text(encoding="utf-8",errors="replace")
            if has_explicit_write_restriction(brief_text):
                allowed=allowed_source_changes(brief_text)
                outside=[path for path in meta["changed_paths"] if not any(_path_within_prefix(path,prefix) for prefix in allowed)]
                if outside:
                    raise ValueError(f"{spec['task_id']}: carry_from {carry} changes paths outside this replacement's explicit Allowed source changes: {outside}")
            carry_snapshots[spec["task_id"]]=meta

        registered = []
        replacements: dict[str, list[str]] = {}
        for spec in specs:
            root = task_root(run, phase, spec["task_id"]); state_path = root / "task.json"
            root.mkdir(parents=True, exist_ok=False)
            brief_copy = root / "brief.md"; shutil.copyfile(spec["brief"], brief_copy); brief_copy.chmod(0o444)
            task = {
                "format": FORMAT, "phase_id": phase, "task_id": spec["task_id"], "kind": spec["kind"],
                "role": spec["role"], "tier": spec["tier"], "brief": str(brief_copy),
                "plan_source": str(graph_path), "plan_source_task": source["source_task_id"], "plan_source_attempt": source["source_attempt"], "plan_source_report": source["source_report"], "dependencies": spec["dependencies"],
                "requires_integration": spec["requires_integration"], "status": "planned",
                "attempts": [], "review_rounds": 0, "review_history": [], "created_at": now(),
            }
            carry=spec.get("carry_from")
            if carry:
                carry_dir=root/"carry-forward"; carry_dir.mkdir(parents=True)
                patch_copy=carry_dir/"predecessor.patch"; shutil.copyfile(Path(carry_snapshots[spec["task_id"]]["patch"]),patch_copy); patch_copy.chmod(0o444)
                meta={**carry_snapshots[spec["task_id"]],"patch":str(patch_copy.resolve())}
                meta_path=carry_dir/"metadata.json"; write_json(meta_path,meta); meta_path.chmod(0o444)
                task["carry_from"]=carry; task["carry_forward_patch"]=str(patch_copy.resolve()); task["carry_forward_metadata"]=str(meta_path.resolve())
            write_json(state_path, task); registered.append(spec["task_id"])
            for old in spec["supersedes"]:
                replacements.setdefault(old, []).append(spec["task_id"])
    # One old task may legitimately split into several semantic replacement tasks, but
    # only one may explicitly inherit its mutable delta (enforced in preflight).
    for old, new_ids in replacements.items():
        old_path = task_file(run, phase, old)
        with file_lock(old_path.with_suffix(".lock")):
            old_state = load_json(old_path)
            prior=old_state.get("superseded_by")
            prior_ids=[prior] if isinstance(prior,str) and prior.strip() else list(prior) if isinstance(prior,list) else []
            merged=list(dict.fromkeys([slug(str(x)) for x in prior_ids if str(x).strip()]+new_ids))
            old_state["status"] = "superseded"; old_state["superseded_by"] = merged; old_state["updated_at"] = now(); write_json(old_path, old_state)

    # A standalone Analyst control task whose approved result was *this* graph has
    # finished once registration succeeds. Reuse the existing non-integration
    # ``accepted`` terminal state instead of inventing a separate consumed/closed
    # lifecycle state. Implementation/verification tasks stay in their explicit
    # replan lane because their own obligation may still need resume/supersession.
    source_closed=False
    source_path=task_file(run,phase,source["source_task_id"])
    with file_lock(source_path.with_suffix(".lock")):
        source_state=load_json(source_path)
        analysis=source_state.get("last_analysis") if isinstance(source_state.get("last_analysis"),dict) else {}
        same_report=str(analysis.get("report") or "")==source["source_report"]
        if source_state.get("kind")=="analysis" and source_state.get("status") not in {"accepted","integrated","superseded"} and analysis.get("outcome")=="replan" and same_report:
            source_state["status"]="accepted"; source_state["accepted_at"]=now(); source_state["accepted_report"]=source["source_report"]
            source_state["graph_consumed_at"]=now(); source_state["updated_at"]=now(); write_json(source_path,source_state); source_closed=True

    ready_registered=[]
    for task_id in registered:
        task=load_task(run,phase,task_id)
        if task.get("status") not in {"planned","ready"}: continue
        ok,missing=readiness(run,phase,task)
        if ok:
            ready_registered.append({"task_id":task_id,"role":task.get("role"),"tier":task.get("tier")})
    return {"phase_id": phase, "registered": registered, "ready_registered":ready_registered, "source_closed":source_closed, "plan_source": str(graph_path), "carry_forward": {tid:meta["source_task"] for tid,meta in carry_snapshots.items()}}


def command_register_plan(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id)
    with file_lock(phase_root(run,phase)/".tasks.lock"):
        return _command_register_plan_unlocked(args)


def command_ready(args: argparse.Namespace) -> dict[str, Any]:
    run = args.run_root.resolve(); load_run(run); phase = slug(args.phase_id)
    out=[]; root = phase_root(run, phase) / "tasks"
    for path in sorted(root.glob("*/task.json")) if root.is_dir() else []:
        task=load_json(path); status=task.get("status")
        if status in {"planned", "ready"}:
            ok, missing=readiness(run, phase, task)
            out.append({"task_id":task["task_id"],"ready":ok,"blocked_by":missing,"tier":task["tier"],"role":task["role"],"kind":task["kind"]})
    return {"phase_id":phase,"tasks":out}


def command_show(args: argparse.Namespace) -> dict[str, Any]:
    return load_task(args.run_root.resolve(), slug(args.phase_id), slug(args.task_id))


def task_brief_label(task: dict[str, Any]) -> str:
    """Return a bounded display label from the registered brief without interpreting it."""
    fallback=str(task.get("task_id") or "task")
    path=Path(str(task.get("brief") or ""))
    if not path.is_file(): return fallback
    try:
        for raw in path.read_text(encoding="utf-8",errors="replace").splitlines()[:40]:
            line=raw.strip()
            if line.startswith("#"):
                label=line.lstrip("#").strip()
                return label[:180] if label else fallback
    except OSError:
        return fallback
    return fallback


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); load_run(run)
    phases=[]
    if getattr(args,"phase_id",None):
        phases=[slug(args.phase_id)]
    else:
        root=run/"phases"
        phases=sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    rows=[]
    wanted=getattr(args,"status",None)
    for phase in phases:
        tasks_dir=phase_root(run,phase)/"tasks"
        for path in sorted(tasks_dir.glob("*/task.json")) if tasks_dir.is_dir() else []:
            task=load_json(path); status=str(task.get("status") or "")
            if wanted and status!=wanted: continue
            attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
            latest=attempts[-1] if attempts else {}
            ready=False; blocked_by=[]
            if status in {"planned","ready"}:
                ready,blocked_by=readiness(run,phase,task)
            rows.append({
                "phase_id":phase,"task_id":task.get("task_id"),"status":status,
                "kind":task.get("kind"),"role":task.get("role"),"tier":task.get("tier"),
                "ready":ready,"blocked_by":blocked_by,"attempts":len(attempts),
                "latest_attempt_role":latest.get("role"),"latest_attempt_status":latest.get("status"),
                "live":task_has_live_attempt(task),"unresolved":task_has_unresolved_attempt(task),
            })
    return {"tasks":rows,"count":len(rows)}


def _stale_attempt_scope_disposition(attempt: dict[str, Any]) -> dict[str, Any]:
    """Classify a dead attempt from durable launch evidence, not from its missing terminal.

    Recovery is reserved for unexplained/forbidden residual state. If the current
    project view can still be compared to the attempt checkpoint and its movement is
    mechanically admissible for that role, a fresh same-role retry may safely inherit
    the workspace. The later Reviewer still judges the complete task delta.
    """
    event=Path(str(attempt.get("event_dir") or ""))
    reservation_path=event/"launch-reservation.json"
    if not reservation_path.is_file():
        return {"safe_retry":False,"reason":"launch-reservation-missing","changed_paths":[]}
    try:
        reservation=load_json(reservation_path)
        root=Path(str(reservation.get("project_root") or "")).resolve()
        baseline_path=Path(str(reservation.get("scope_baseline") or "")).resolve()
        task_path=Path(str(reservation.get("task_contract") or "")).resolve()
        if not root.is_dir() or not baseline_path.is_file() or not task_path.is_file():
            return {"safe_retry":False,"reason":"stale-scope-evidence-missing","changed_paths":[]}
        from scope_snapshot import compare
        scope=compare(root,load_json(baseline_path))
        changed=[str(x) for x in scope.get("changed_since_attempt_baseline",[]) if str(x)]
        role=str(reservation.get("role") or attempt.get("role") or "")
        task_text=task_path.read_text(encoding="utf-8",errors="replace")
        writes=bool(reservation.get("writes_project")) if "writes_project" in reservation else role_writes_project(role,task_text)
        forbidden=[path for path in changed if path==CONTROL_DIR or path.startswith(CONTROL_DIR+"/")]
        if forbidden:
            return {"safe_retry":False,"reason":"control-tree-changed","changed_paths":changed}
        if not writes and changed:
            return {"safe_retry":False,"reason":"read-only-attempt-changed-project","changed_paths":changed}
        if writes and has_explicit_write_restriction(task_text):
            allowed=allowed_source_changes(task_text)
            outside=[path for path in changed if not any(_path_within_prefix(path,prefix) for prefix in allowed)]
            if outside:
                return {"safe_retry":False,"reason":"changes-outside-authorized-scope","changed_paths":changed,"outside_paths":outside}
        return {"safe_retry":True,"reason":"residual-state-mechanically-admissible","changed_paths":changed}
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        return {"safe_retry":False,"reason":"stale-scope-unprovable","changed_paths":[],"error":str(exc)[:500]}


def _stale_retry_status(task: dict[str, Any], attempt: dict[str, Any]) -> str:
    prior=str(attempt.get("prior_task_status") or "")
    if prior in STATUSES and prior not in {"active","accepted","integrated","superseded","blocked"}:
        return prior
    role=str(attempt.get("role") or "")
    base=str(task.get("role") or "")
    if role=="reviewer": return "awaiting-review"
    if role=="fixer": return "needs-fix"
    if role=="recovery": return "recovery-required"
    if role=="discovery" and role!=base: return "needs-analysis"
    # Base-role and bootstrap/reviewer-control retries can restart from the retained
    # durable workspace/report authority; no Analyst is needed merely because a
    # process disappeared. Readiness will be recomputed at launch.
    return "planned"


def command_sweep_stale(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); load_run(run)
    phases=[slug(args.phase_id)] if getattr(args,"phase_id",None) else sorted(p.name for p in (run/"phases").iterdir() if p.is_dir()) if (run/"phases").is_dir() else []
    marked=[]
    for phase in phases:
        tasks_dir=phase_root(run,phase)/"tasks"
        for state_path in sorted(tasks_dir.glob("*/task.json")) if tasks_dir.is_dir() else []:
            with file_lock(state_path.with_suffix(".lock")):
                task=load_json(state_path)
                if task.get("status") in {"accepted","integrated","superseded"}: continue
                changed=False; dispositions=[]
                for attempt in task.get("attempts",[]):
                    if not isinstance(attempt,dict) or not attempt_is_unresolved(attempt) or attempt_is_live(attempt): continue
                    disposition=_stale_attempt_scope_disposition(attempt); dispositions.append((attempt,disposition))
                    attempt["status"]="stale-unresolved"
                    attempt["stale_disposition"]="safe-retry" if disposition.get("safe_retry") else "recovery-required"
                    attempt["stale_reason"]=disposition.get("reason")
                    attempt["stale_changed_paths"]=disposition.get("changed_paths",[])
                    changed=True
                    marked.append({"phase_id":phase,"task_id":task.get("task_id"),"event_dir":attempt.get("event_dir"),"disposition":attempt["stale_disposition"],"reason":attempt["stale_reason"],"changed_count":len(attempt["stale_changed_paths"])})
                if dispositions:
                    unsafe=[item for item,disp in dispositions if not disp.get("safe_retry")]
                    target="recovery-required" if unsafe else _stale_retry_status(task,dispositions[-1][0])
                    if task.get("status")!=target:
                        task["status"]=target; changed=True
                if changed:
                    task["updated_at"]=now(); write_json(state_path,task)
    return {"marked":marked,"count":len(marked)}




def _latest_rules_revision(run: Path) -> str | None:
    root=run/"worker-rules"
    if not root.is_dir(): return None
    names=[]
    for child in root.iterdir():
        if child.is_dir() and re.fullmatch(r"r\d{4}",child.name): names.append(child.name)
    return max(names) if names else None


def _workspace_cleanup_candidate(run: Path, phase: str, task: dict[str, Any]) -> bool:
    ws_path=task_root(run,phase,str(task.get("task_id")))/"workspace.json"
    if not ws_path.is_file(): return False
    try: ws=load_json(ws_path)
    except Exception: return False
    if ws.get("mode")=="analysis-view": return False
    status=str(task.get("status") or "")
    if status=="superseded" and superseded_workspace_retention(run,phase,task).get("retain"):
        return False
    return status in {"integrated","superseded"} or (status=="accepted" and not task.get("requires_integration"))


def _reconcile_action(run: Path, phase: str, task: dict[str, Any]) -> dict[str, Any] | None:
    tid=str(task.get("task_id") or ""); status=str(task.get("status") or ""); attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]; latest=attempts[-1] if attempts else {}
    event=Path(str(latest.get("event_dir") or "")) if latest else Path()
    terminal=(event/"terminal.json").is_file() if event and str(event) not in {".",""} else False
    attempt_status=str(latest.get("status") or "")
    role=str(latest.get("role") or task.get("role") or "")
    base={"phase_id":phase,"task_id":tid,"task_status":status}
    if latest and attempt_status=="started" and terminal:
        return {**base,"action":"gate-finished-attempt","event_dir":str(event)}
    # A live attempt already owns this task transition. Never advertise another
    # launch for the same task (Reviewer/Fixer/Recovery/base role) while it runs.
    # A live attempt already owns the transition; do not advertise duplicate launches.
    if any(attempt_is_live(a) for a in attempts):
        return None
    if attempt_status in {"report-recovery","report-resume","mutating-report-resume"}:
        session=latest.get("session_id") or latest.get("resume_session")
        return {**base,"action":"resume-recorded-session" if session else "retry-same-role-retained-workspace","role":role,"event_dir":str(event),**({"session_id":session} if session else {})}
    if status=="recovery-required": return {**base,"action":"launch-recovery"}
    if status=="needs-analysis": return {**base,"action":"launch-analyst-discovery"}
    if status=="needs-fix": return {**base,"action":"launch-fixer"}
    if status=="awaiting-review":
        if latest and latest.get("role")=="reviewer" and latest.get("status")=="gated":
            return {**base,"action":"record-review-outcome","report":str(event/"report.md")}
        return {**base,"action":"launch-fresh-reviewer"}
    if status=="review-passed": return {**base,"action":"accept-reviewed-task"}
    if status=="accepted" and task.get("requires_integration"): return {**base,"action":"integrate-accepted-task"}
    if status=="blocked": return {**base,"action":"await-human-decision","escalation":task.get("last_escalation")}
    if status in {"planned","ready"}:
        ok,missing=readiness(run,phase,task)
        if ok: return {**base,"action":"launch-ready-task","role":task.get("role"),"tier":task.get("tier")}
        return {**base,"action":"waiting-dependencies","blocked_by":missing}
    if status=="active" and latest and latest.get("status")=="gated":
        if role=="goal-planner": return {**base,"action":"launch-or-reuse-fresh-plan-reviewer","report":str(event/"report.md")}
        if role=="plan-reviewer":
            recorded=task.get("last_plan_review") if isinstance(task.get("last_plan_review"),dict) else {}
            if str(recorded.get("reviewer_attempt") or "") == str(event): return None
            return {**base,"action":"record-plan-review-outcome","report":str(event/"report.md")}
        if role=="context-reviewer":
            recorded=task.get("last_context_review") if isinstance(task.get("last_context_review"),dict) else {}
            if str(recorded.get("reviewer_attempt") or "") == str(event): return None
            return {**base,"action":"record-context-review-outcome","report":str(event/"report.md")}
        if role in {"discovery","planner","phase-surveyor","recovery","phase-auditor"} and task.get("kind") in {"implementation","verification"}:
            return {**base,"action":"record-analyst-disposition","report":str(event/"report.md")}
        if task.get("kind") in {"analysis","verification"}: return {**base,"action":"accept-specialist-result","report":str(event/"report.md")}
    return None


def _quiescent_reusable_review_conduit(task: dict[str, Any]) -> bool:
    """Whether a reusable Plan/Context Reviewer has no unrecorded semantic outcome.

    These control-plane tasks intentionally remain ``active`` so a later fresh review
    can reuse the task identity.  Once the latest gated attempt has been recorded,
    that active status is quiescent capacity, not unresolved work/backlog.
    """
    if str(task.get("status") or "") != "active": return False
    attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
    if not attempts: return False
    latest=attempts[-1]
    if str(latest.get("status") or "") != "gated": return False
    role=str(latest.get("role") or task.get("role") or "")
    field="last_plan_review" if role=="plan-reviewer" else "last_context_review" if role=="context-reviewer" else ""
    if not field: return False
    recorded=task.get(field) if isinstance(task.get(field),dict) else {}
    return str(recorded.get("reviewer_attempt") or "") == str(latest.get("event_dir") or "")


def command_reconcile_run(args: argparse.Namespace) -> dict[str, Any]:
    """Mechanically summarize resume state without repository archaeology.

    This command intentionally knows lifecycle state only. It does not inspect source
    implementation, reinterpret worker reports, or invent technical priorities.
    """
    run=args.run_root.resolve(); info=load_run(run)
    if not getattr(args,"no_sweep",False):
        class S: pass
        sweep=S(); sweep.run_root=run; sweep.phase_id=getattr(args,"phase_id",None)
        swept=command_sweep_stale(sweep)
    else: swept={"marked":[],"count":0}
    phases=[slug(args.phase_id)] if getattr(args,"phase_id",None) else sorted(p.name for p in (run/"phases").iterdir() if p.is_dir()) if (run/"phases").is_dir() else []
    tasks=[]; actions=[]; live=[]; human=[]; cleanup=[]
    for phase in phases:
        tasks_dir=phase_root(run,phase)/"tasks"
        for state_path in sorted(tasks_dir.glob("*/task.json")) if tasks_dir.is_dir() else []:
            task=load_json(state_path); tid=str(task.get("task_id") or state_path.parent.name)
            attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
            current_live=[a for a in attempts if attempt_is_live(a)]
            if current_live:
                for attempt in current_live: live.append({"phase_id":phase,"task_id":tid,"role":attempt.get("role"),"event_dir":attempt.get("event_dir")})
            action=_reconcile_action(run,phase,task)
            if action:
                actions.append(action)
                if action.get("action")=="await-human-decision": human.append(action)
            if _workspace_cleanup_candidate(run,phase,task): cleanup.append({"phase_id":phase,"task_id":tid})
            tasks.append({"phase_id":phase,"task_id":tid,"status":task.get("status"),"role":task.get("role"),"tier":task.get("tier"),"live":bool(current_live),"quiescent_conduit":_quiescent_reusable_review_conduit(task),"brief":task.get("brief"),"label":task_brief_label(task),"requires_integration":bool(task.get("requires_integration"))})
    limit=int(info.get("max_workers") or 1); slots=max(0,limit-len(live))
    ignored={"waiting-dependencies","await-human-decision"}
    launch_actions={"launch-ready-task","launch-recovery","launch-analyst-discovery","launch-fixer","launch-fresh-reviewer","launch-or-reuse-fresh-plan-reviewer","resume-recorded-session"}
    nonlaunch=[a for a in actions if a.get("action") not in ignored|launch_actions]
    launches=[a for a in actions if a.get("action") in launch_actions]
    first_useful=nonlaunch+launches[:slots]
    classified={(a.get("phase_id"),a.get("task_id")) for a in actions}
    unresolved_state=[t for t in tasks if not t.get("live") and not t.get("quiescent_conduit") and str(t.get("status") or "") not in {"accepted","integrated","superseded"} and (t.get("phase_id"),t.get("task_id")) not in classified]
    status_counts: dict[str,int] = {}
    for row in tasks:
        key=str(row.get("status") or "unknown"); status_counts[key]=status_counts.get(key,0)+1
    backlog=[]
    action_by_task={(str(a.get("phase_id")),str(a.get("task_id"))):a for a in actions}
    for row in tasks:
        status=str(row.get("status") or "")
        closed=status in {"integrated","superseded"} or (status=="accepted" and not row.get("requires_integration")) or bool(row.get("quiescent_conduit"))
        if closed: continue
        item=dict(row); action=action_by_task.get((str(row.get("phase_id")),str(row.get("task_id"))))
        if action: item["next_action"]=action.get("action"); item["blocked_by"]=action.get("blocked_by")
        backlog.append(item)
    # Cleanup is deliberately omitted from first useful actions: it should not delay
    # valid task transitions/delegation unless disk pressure itself blocks execution.
    compact_actions=[a for a in actions if a.get("action")!="waiting-dependencies"]
    waiting_count=sum(1 for a in actions if a.get("action")=="waiting-dependencies")
    # Default reconciliation is a routing packet, not a status report. Keep only
    # fields that can change the next control decision; verbose inventories and
    # stable configuration belong behind --details.
    result={
        "run_id":info.get("run_id"),"run_status":info.get("status"),
        "worker_budget":{"max":limit,"live":len(live),"free":slots},
        "backlog_count":len(backlog),"waiting_dependency_count":waiting_count,
    }
    if first_useful: result["first_useful_actions"]=first_useful
    if len(live)==0 and any(a.get("action") in launch_actions for a in first_useful):
        result["scheduler_warning"]="READY work exists while no workers are live; launch useful work before routine housekeeping or ending the turn"
    if live: result["live_attempts"]=live
    if human: result["human_blocks"]=human
    if unresolved_state: result["unresolved_state"]=unresolved_state
    if swept.get("count"): result["swept_stale"]=swept
    if getattr(args,"details",False):
        result.update({
            "worker_runtimes":info.get("worker_runtimes"),"escalation":info.get("escalation"),"latest_worker_rules":_latest_rules_revision(run),
            "swept_stale":swept,"live_attempts":live,"actions":actions,"first_useful_actions":first_useful,
            "human_blocks":human,"unresolved_state":unresolved_state,"task_count":len(tasks),"status_counts":status_counts,
            "cleanup_candidates":cleanup,"backlog":backlog,
        })
    return result

def command_idle_check(args: argparse.Namespace) -> dict[str, Any]:
    """Turn-boundary guard: say mechanically whether routine orchestration may stop."""
    class R: pass
    probe=R(); probe.run_root=args.run_root; probe.phase_id=getattr(args,"phase_id",None); probe.no_sweep=True
    state=command_reconcile_run(probe); pending=list(state.get("first_useful_actions") or [])
    status=str(state.get("run_status") or "active")
    if status!="active": safe=True; reason=f"run-{status}"
    elif pending: safe=False; reason="authorized-action-remains"
    elif state.get("live_attempts"): safe=True; reason="workers-live"
    elif state.get("human_blocks"): safe=True; reason="human-blocked-with-no-independent-action"
    elif state.get("unresolved_state"): safe=False; reason="unresolved-durable-state-needs-analyst-routing"
    else: safe=True; reason="no-authorized-action-remains"
    if status=="human-blocked": routine_user_update="human-decision"
    elif status!="active": routine_user_update="terminal-summary"
    elif state.get("human_blocks") and not pending: routine_user_update="human-decision"
    else: routine_user_update="suppress"
    result={
        "run_status":status,"safe_to_end_routine_turn":safe,"reason":reason,
        "worker_budget":state.get("worker_budget"),"routine_user_update":routine_user_update,
    }
    if pending: result["required_actions"]=pending
    if state.get("live_attempts"):
        result["live_attempts"]=state.get("live_attempts"); result["observer_required"]=True
    if state.get("human_blocks"): result["human_blocks"]=state.get("human_blocks")
    if state.get("unresolved_state"): result["unresolved_state"]=state.get("unresolved_state")
    return result


def command_record_attempt(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); entry=load_json(args.attempt_json.resolve())
        if str(entry.get("task_id")) != tid: raise ValueError("attempt task_id mismatch")
        attempts=task.setdefault("attempts", [])
        event_dir=str(entry.get("event_dir") or "")
        if any(str(x.get("event_dir"))==event_dir for x in attempts if isinstance(x,dict)): raise ValueError("attempt already recorded")
        entry.setdefault("prior_task_status",task.get("status"))
        attempts.append(entry)
        # A Reviewer runs inside the existing awaiting-review stage; do not erase
        # that semantic routing state merely because another process started.
        if entry.get("role")!="reviewer": task["status"]="active"
        task["updated_at"]=now(); write_json(path,task)
    return {"task_id":tid,"status":task["status"],"attempts":len(task["attempts"])}


def command_update_attempt(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); event=str(args.event_dir.resolve()); found=None
        for entry in task.get("attempts",[]):
            if isinstance(entry,dict) and str(Path(str(entry.get("event_dir"))).resolve())==event:
                found=entry; break
        if found is None: raise ValueError("attempt not recorded")
        if args.status:
            if args.status not in ATTEMPT_STATUSES: raise ValueError(f"unsupported attempt status: {args.status}")
            found["status"]=args.status
        if args.gate: found["gate"]=str(args.gate.resolve())
        if args.session_id: found["session_id"]=args.session_id
        if args.status=="integrity-failed":
            task["status"]="recovery-required"
        elif args.status=="mutating-report-recovery":
            # Backward-compatible reading of older gate output. New gates classify
            # admissible retained mutation as mutating-report-resume instead.
            task["status"]="recovery-required"
        elif args.status in {"report-recovery", "report-resume", "mutating-report-resume"}:
            # No-change report recovery and substantive in-progress reports are
            # intentionally resumable. Preserve routing instead of forcing an
            # expensive cold Analyst recovery for a transport hiccup.
            pass
        elif found.get("role") in {"implementer","fixer"} and args.status in {"gated", "process-exited"}:
            task["status"]="awaiting-review"
        task["updated_at"]=now(); write_json(path,task)
    return {"task_id":tid,"task_status":task["status"],"attempt_status":found.get("status")}



def matching_gated_attempt(task: dict[str, Any], roles: str | set[str], report: Path) -> dict[str, Any] | None:
    target = report.resolve(); allowed={roles} if isinstance(roles,str) else set(roles)
    for attempt in reversed(task.get("attempts", [])):
        if not isinstance(attempt, dict) or attempt.get("role") not in allowed or attempt.get("status") != "gated":
            continue
        event = Path(str(attempt.get("event_dir") or ""))
        if (event / "report.md").resolve() == target:
            return attempt
    return None

def matching_any_gated_attempt(task: dict[str, Any], report: Path) -> dict[str, Any] | None:
    target=report.resolve()
    for attempt in reversed(task.get("attempts", [])):
        if not isinstance(attempt,dict) or attempt.get("status")!="gated": continue
        event=Path(str(attempt.get("event_dir") or ""))
        if (event/"report.md").resolve()==target: return attempt
    return None


def require_current_attempt(task: dict[str, Any], attempt: dict[str, Any], *, reason: str) -> None:
    attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
    if not attempts:
        raise ValueError(f"{reason}: task has no recorded attempts")
    current=attempts[-1]
    if Path(str(current.get("event_dir") or "")).resolve()!=Path(str(attempt.get("event_dir") or "")).resolve():
        raise ValueError(f"{reason}: report is stale because a newer task attempt exists")


def attempt_tier(attempt: dict[str, Any]) -> str:
    role=str(attempt.get("role") or "")
    tier=str(DEFAULT_TIER.get(role) or "").lower()
    if tier not in ESCALATION_LADDER:
        raise ValueError(f"cannot determine escalation tier for worker role {role!r}")
    recorded=str(attempt.get("tier") or "").lower()
    if recorded and recorded != tier:
        raise ValueError(
            f"worker attempt tier {recorded!r} conflicts with role {role!r}; "
            f"{role} is fixed to {tier}"
        )
    return tier


def record_escalation(run: Path, task: dict[str, Any], attempt: dict[str, Any], report: Path, *, source: str) -> dict[str, Any]:
    require_escalation_enabled(run)
    from_tier=attempt_tier(attempt)
    target=ESCALATION_LADDER[from_tier]
    event=str(attempt.get("event_dir") or "")
    record={
        "source": source, "from_tier": from_tier, "target": target,
        "role": str(attempt.get("role") or ""), "report": str(report.resolve()),
        "attempt": event, "recorded_at": now(),
    }
    task.setdefault("escalation_history", []).append(record)
    task["last_escalation"]=record
    # Central ladder policy: Grunt escalation is always adjudicated by an Analyst;
    # only an Analyst escalation reaches the Human authority boundary.
    task["status"]="needs-analysis" if target=="analyst" else "blocked"
    return record


def analyst_goal_plan(attempt: dict[str, Any]) -> Path:
    return Path(str(attempt.get("event_dir") or "")) / "plan" / "PLAN.md"

def require_analyst_goal_plan(attempt: dict[str, Any], *, reason: str) -> Path:
    event=Path(str(attempt.get("event_dir") or ""))
    plan=event / "plan" / "PLAN.md"
    if plan.is_symlink() or plan.parent.is_symlink():
        raise ValueError(f"{reason} requires an attempt-local regular PLAN.md, not a symlink: {plan}")
    try:
        plan.resolve().relative_to(event.resolve())
    except ValueError as exc:
        raise ValueError(f"{reason} requires PLAN.md to remain inside the Goal-Planner attempt: {plan}") from exc
    if not plan.is_file() or not plan.read_text(encoding="utf-8", errors="replace").strip():
        raise ValueError(f"{reason} requires a non-empty Analyst-authored plan before acceptance: {plan}")
    return plan


def latest_gated_attempt(task: dict[str, Any], role: str) -> dict[str, Any] | None:
    for attempt in reversed(task.get("attempts", [])):
        if isinstance(attempt, dict) and attempt.get("role") == role and attempt.get("status") == "gated":
            return attempt
    return None

def same_file_content(left: Path, right: Path) -> bool:
    return left.is_file() and right.is_file() and left.read_bytes() == right.read_bytes()

def require_frozen_plan_snapshot(plan: Path, snapshot: Path, *, reason: str) -> None:
    if snapshot.is_symlink() or snapshot.parent.is_symlink() or not snapshot.is_file():
        raise ValueError(f"{reason}: reviewed PLAN.md must be a regular frozen copy, not a symlink")
    try:
        if plan.samefile(snapshot):
            raise ValueError(f"{reason}: reviewed PLAN.md must be an independent copy, not the live plan/hardlink")
    except FileNotFoundError:
        raise ValueError(f"{reason}: reviewed PLAN.md snapshot is missing")
    if not same_file_content(plan, snapshot):
        raise ValueError(f"{reason}: Goal-Planner plan differs from the immutable copy reviewed by the fresh Reviewer")

def require_goal_plan_review(task: dict[str, Any], attempt: dict[str, Any], plan: Path) -> dict[str, Any]:
    review = task.get("last_plan_review") if isinstance(task.get("last_plan_review"), dict) else {}
    if review.get("outcome") != "pass":
        raise ValueError("Goal-Planner acceptance requires an explicit fresh Plan-Reviewer PASS for this exact planner attempt")
    if Path(str(review.get("planner_attempt") or "")).resolve() != Path(str(attempt.get("event_dir") or "")).resolve():
        raise ValueError("Plan-Reviewer PASS is stale: it does not review the Goal-Planner attempt being accepted")
    if Path(str(review.get("plan") or "")).resolve() != plan.resolve():
        raise ValueError("Plan-Reviewer PASS is stale: it does not review the plan being accepted")
    snapshot = Path(str(review.get("plan_snapshot") or ""))
    require_frozen_plan_snapshot(plan, snapshot, reason="Plan-Reviewer PASS is stale")
    review_report = Path(str(review.get("report") or ""))
    if not review_report.is_file():
        raise ValueError("Plan-Reviewer PASS report is missing")
    return review

def analyst_plan_graph(attempt: dict[str, Any]) -> Path:
    return Path(str(attempt.get("event_dir") or "")) / "plan" / "task-graph.json"

def require_analyst_plan_graph(attempt: dict[str, Any], *, reason: str) -> Path:
    graph=analyst_plan_graph(attempt)
    if not graph.is_file():
        raise ValueError(f"{reason} requires the Analyst-authored replacement plan to exist before routing: {graph}")
    data=load_json(graph)
    if data.get("format")!=PLAN_FORMAT or not isinstance(data.get("tasks"),list) or not data.get("tasks"):
        raise ValueError(f"{reason} requires a non-empty {PLAN_FORMAT} task graph: {graph}")
    return graph



def proposed_context_files(event: Path) -> dict[str, Path]:
    """Return every attempt-local file that would become reusable worker context."""
    event=event.resolve(); out: dict[str,Path]={}
    protocol=event/"project-protocol"/"PROJECT-PROTOCOL.md"
    if protocol.exists():
        if protocol.is_symlink() or not protocol.is_file():
            raise ValueError(f"proposed Project Protocol must be a regular file: {protocol}")
        out["project-protocol/PROJECT-PROTOCOL.md"]=protocol
    skills=event/"worker-skills"
    if skills.exists():
        if skills.is_symlink() or not skills.is_dir():
            raise ValueError(f"proposed worker-skills must be a regular directory: {skills}")
        for entry in sorted(skills.rglob("*")):
            if entry.is_symlink(): raise ValueError(f"proposed worker skill bundle must not contain symlinks: {entry}")
            if entry.is_file():
                rel=entry.relative_to(event).as_posix()
                out[rel]=entry
        for skill_md in skills.glob("*/SKILL.md"):
            skill_id=skill_md.parent.name
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}",skill_id):
                raise ValueError(f"unsafe proposed worker skill id: {skill_id!r}")
        stray=[x for x in skills.iterdir() if x.is_file()]
        if stray: raise ValueError(f"worker-skills root may contain only skill directories: {stray[0]}")
    return out


def has_proposed_context(attempt: dict[str, Any]) -> bool:
    event=Path(str(attempt.get("event_dir") or ""))
    return bool(proposed_context_files(event)) if event.is_dir() else False


def require_frozen_context_snapshot(source_event: Path, snapshot_root: Path, *, reason: str) -> None:
    source_event=source_event.resolve(); snapshot_root=snapshot_root.resolve()
    if snapshot_root.is_symlink() or not snapshot_root.is_dir():
        raise ValueError(f"{reason}: reviewed context snapshot must be a regular directory")
    source=proposed_context_files(source_event)
    snap: dict[str,Path]={}
    for entry in sorted(snapshot_root.rglob("*")):
        if entry.is_symlink(): raise ValueError(f"{reason}: reviewed context snapshot contains symlink: {entry}")
        if entry.is_file(): snap[entry.relative_to(snapshot_root).as_posix()]=entry
    if set(source)!=set(snap):
        raise ValueError(f"{reason}: proposed reusable context file set differs from reviewed snapshot")
    if not source:
        raise ValueError(f"{reason}: source attempt contains no reusable context proposal")
    for rel,left in source.items():
        right=snap[rel]
        try:
            if left.samefile(right): raise ValueError(f"{reason}: reviewed context must be an independent copy, not a hardlink: {rel}")
        except FileNotFoundError:
            raise ValueError(f"{reason}: reviewed context file is missing: {rel}")
        if left.read_bytes()!=right.read_bytes():
            raise ValueError(f"{reason}: proposed reusable context changed after review: {rel}")


def require_context_review(task: dict[str, Any], attempt: dict[str, Any], *, reason: str) -> dict[str, Any] | None:
    event=Path(str(attempt.get("event_dir") or "")).resolve()
    if not proposed_context_files(event): return None
    review=task.get("last_context_review") if isinstance(task.get("last_context_review"),dict) else {}
    if review.get("outcome")!="pass":
        raise ValueError(f"{reason} requires a fresh Context-Reviewer PASS for reusable context proposed by this Analyst attempt")
    if Path(str(review.get("source_attempt") or "")).resolve()!=event:
        raise ValueError(f"{reason}: Context-Reviewer PASS is stale for a different Analyst attempt")
    snapshot=Path(str(review.get("context_snapshot") or ""))
    require_frozen_context_snapshot(event,snapshot,reason=f"{reason}: Context-Reviewer PASS is stale")
    report=Path(str(review.get("report") or ""))
    if not report.is_file(): raise ValueError(f"{reason}: Context-Reviewer PASS report is missing")
    return review

def command_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); report=args.report.resolve()
        if not report.is_file(): raise ValueError(f"review report missing: {report}")
        attempt=matching_gated_attempt(task,"reviewer",report)
        if attempt is None: raise ValueError("review outcome must refer to a gated Reviewer attempt for this task")
        require_current_attempt(task,attempt,reason="review outcome")
        attempt_path=str(attempt.get("event_dir"))
        history=task.setdefault("review_history", [])
        if any(isinstance(x,dict) and str(x.get("attempt") or "")==attempt_path for x in history):
            raise ValueError("this Reviewer attempt already has a recorded semantic outcome")
        if task.get("status")!="awaiting-review": raise ValueError(f"review outcome requires task status awaiting-review; current status is {task.get('status')!r}")
        rounds=int(task.get("review_rounds") or 0)+1; task["review_rounds"]=rounds
        recorded={"outcome":outcome,"report":str(report),"recorded_at":now(),"round":rounds,"attempt":attempt_path,"checkpoint_ref":attempt.get("checkpoint_ref")}
        history.append(recorded); task["last_review"]=recorded
        if outcome=="pass": task["status"]="review-passed"
        elif outcome=="fail": task["status"]="needs-fix"
        else: record_escalation(run,task,attempt,report,source="review")
        task["updated_at"]=now(); write_json(path,task)
    result={"task_id":tid,"outcome":outcome,"review_rounds":rounds,"status":task["status"]}
    if outcome=="escalate": result["escalation_target"]=(task.get("last_escalation") or {}).get("target")
    return result



def _review_conduit_start(path: Path, *, role: str, report: Path, target_key: str, label: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    task=load_json(path)
    if task.get("role")!=role or task.get("kind")!="analysis":
        raise ValueError(f"{label} is only valid for a {role} analysis task")
    if not report.is_file():
        raise ValueError(f"{label} report missing: {report}")
    attempt=matching_gated_attempt(task,role,report)
    if attempt is None:
        raise ValueError(f"{label} outcome must refer to a gated {role} attempt")
    require_current_attempt(task,attempt,reason=f"{label} outcome")
    target=attempt.get(target_key) if isinstance(attempt.get(target_key),dict) else {}
    target_id=str(target.get("task_id") or "")
    if not target_id or target_id!=str(task.get("reviews_task") or ""):
        raise ValueError(f"{label} attempt is not bound to its declared review target")
    return task,attempt,target,target_id


def _record_review_conduit(task: dict[str, Any], recorded: dict[str, Any], *, history_key: str, last_key: str) -> None:
    task.setdefault(history_key,[]).append(recorded)
    task[last_key]=recorded
    task["status"]="active"
    task["updated_at"]=now()

def command_plan_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve()
        review_task,attempt,target,target_id=_review_conduit_start(
            path,role="plan-reviewer",report=report,target_key="plan_review_target",label="plan-review"
        )
        planner_attempt=Path(str(target.get("attempt") or ""))
        plan=Path(str(target.get("source_plan") or target.get("plan") or ""))
        plan_snapshot=Path(str(target.get("plan_snapshot") or ""))
        if not planner_attempt.is_dir() or not plan.is_file() or not plan_snapshot.is_file():
            raise ValueError("Plan-Reviewer target attempt/source/snapshot no longer exists")
        require_frozen_plan_snapshot(plan, plan_snapshot, reason="Plan review is stale")
        target_path=task_file(run,phase,target_id)
        with file_lock(target_path.with_suffix(".lock")):
            goal=load_json(target_path)
            if goal.get("status") in {"accepted","integrated","superseded"}:
                raise ValueError(f"cannot record another Plan Review after Goal-Planner task is {goal.get('status')!r}")
            gated=latest_gated_attempt(goal,"goal-planner")
            if gated is None or Path(str(gated.get("event_dir") or "")).resolve()!=planner_attempt.resolve():
                raise ValueError("Plan review is stale: the Goal Planner has a newer gated attempt")
            role_attempts=[a for a in goal.get("attempts",[]) if isinstance(a,dict) and a.get("role")=="goal-planner"]
            if not role_attempts or Path(str(role_attempts[-1].get("event_dir") or "")).resolve()!=planner_attempt.resolve():
                raise ValueError("Plan review is stale: the Goal Planner has a newer unresolved attempt")
            if analyst_goal_plan(gated).resolve()!=plan.resolve():
                raise ValueError("Plan review target does not match the Goal-Planner plan path")
            history=goal.setdefault("plan_review_history",[])
            review_event=str(attempt.get("event_dir") or "")
            if any(isinstance(x,dict) and str(x.get("reviewer_attempt") or "")==review_event for x in history):
                raise ValueError("this Plan-Reviewer attempt already has a recorded outcome")
            recorded={"outcome":outcome,"report":str(report),"reviewer_attempt":review_event,"planner_attempt":str(planner_attempt.resolve()),"plan":str(plan.resolve()),"plan_snapshot":str(plan_snapshot.resolve()),"recorded_at":now()}
            history.append(recorded); goal["last_plan_review"]=recorded
            if outcome=="pass": goal["status"]="review-passed"
            elif outcome=="fail": goal["status"]="planned"
            else:
                record_escalation(run,goal,attempt,report,source="plan-review")
            goal["updated_at"]=now(); write_json(target_path,goal)
        _record_review_conduit(review_task,recorded,history_key="plan_review_history",last_key="last_plan_review")
        write_json(path,review_task)
    release_read_only_runtime(run,phase,tid)
    return {"task_id":tid,"reviews_task":target_id,"outcome":outcome,"goal_planner_status":goal["status"]}


def command_context_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid); outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve()
        review_task,attempt,target,target_id=_review_conduit_start(
            path,role="context-reviewer",report=report,target_key="context_review_target",label="context-review"
        )
        source_attempt=Path(str(target.get("attempt") or "")).resolve(); snapshot=Path(str(target.get("context_snapshot") or ""))
        if not source_attempt.is_dir() or not snapshot.is_dir(): raise ValueError("Context-Reviewer source/snapshot no longer exists")
        require_frozen_context_snapshot(source_attempt,snapshot,reason="Context review is stale")
        source_path=task_file(run,phase,target_id)
        with file_lock(source_path.with_suffix(".lock")):
            source=load_json(source_path)
            source_record=next((a for a in source.get("attempts",[]) if isinstance(a,dict) and Path(str(a.get("event_dir") or "")).resolve()==source_attempt),None)
            if source_record is None or source_record.get("status")!="gated" or source_record.get("tier")!="analyst" or source_record.get("role") not in CONTEXT_AUTHOR_ROLES:
                raise ValueError("Context review source is no longer a gated context-authoring Analyst attempt")
            author_attempts=[a for a in source.get("attempts",[]) if isinstance(a,dict) and a.get("role") in CONTEXT_AUTHOR_ROLES]
            if not author_attempts or Path(str(author_attempts[-1].get("event_dir") or "")).resolve()!=source_attempt:
                raise ValueError("Context review is stale: source Analyst has a newer attempt")
            history=source.setdefault("context_review_history",[]); review_event=str(attempt.get("event_dir") or "")
            if any(isinstance(x,dict) and str(x.get("reviewer_attempt") or "")==review_event for x in history):
                raise ValueError("this Context-Reviewer attempt already has a recorded outcome")
            recorded={"outcome":outcome,"report":str(report),"reviewer_attempt":review_event,"source_attempt":str(source_attempt),"context_snapshot":str(snapshot.resolve()),"recorded_at":now()}
            history.append(recorded); source["last_context_review"]=recorded
            if outcome=="escalate":
                # The reusable context belongs to the source Analyst proposal, so a
                # Human-bound Context Review escalation blocks that source proposal,
                # not the reusable reviewer conduit. Human authority returns to the
                # source Analyst for revision/confirmation, followed by fresh review.
                record_escalation(run,source,attempt,report,source="context-review")
            source["updated_at"]=now(); write_json(source_path,source)
        _record_review_conduit(review_task,recorded,history_key="context_review_history",last_key="last_context_review")
        write_json(path,review_task)
    release_read_only_runtime(run,phase,tid)
    result={"task_id":tid,"reviews_task":target_id,"outcome":outcome}
    if outcome=="escalate": result["escalation_target"]=(source.get("last_escalation") or {}).get("target")
    return result


def command_analysis_result(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); report=args.report.resolve()
        if task.get("status") in {"accepted","integrated","superseded"}: raise ValueError(f"cannot record a new analysis result for completed task status {task.get('status')!r}")
        if not report.is_file(): raise ValueError(f"Analyst report missing: {report}")
        attempt=matching_gated_attempt(task,{"discovery","planner","phase-surveyor","recovery","phase-auditor"},report)
        if attempt is None or attempt_tier(attempt)!="analyst": raise ValueError("analysis result must refer to a gated Analyst attempt for this task")
        require_current_attempt(task,attempt,reason="analysis result")
        outcome=args.outcome; task["last_analysis"]={"outcome":outcome,"report":str(report),"attempt":str(attempt.get("event_dir")),"recorded_at":now()}
        if outcome=="resume":
            if task.get("kind") not in {"implementation","verification"}: raise ValueError("analysis-result resume is only valid for implementation/verification work returning from Analyst diagnosis")
            task["status"]="planned"
        elif outcome in {"replan","replan-resume"}:
            require_analyst_plan_graph(attempt, reason=f"analysis-result {outcome}")
            if outcome=="replan-resume":
                if task.get("kind") not in {"implementation","verification"}: raise ValueError("analysis-result replan-resume is only valid when the current implementation/verification task also returns to its prior lane")
                task["status"]="planned"
            else:
                task["status"]="needs-analysis"
        else:
            record_escalation(run,task,attempt,report,source="analysis-result")
        task["updated_at"]=now(); write_json(path,task)
    return {"task_id":tid,"outcome":outcome,"status":task["status"]}


def command_escalate(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); report=args.report.resolve()
        if task.get("status") in {"accepted","integrated","superseded"}: raise ValueError(f"cannot escalate completed task status {task.get('status')!r}")
        if not report.is_file(): raise ValueError(f"escalation report missing: {report}")
        attempt=matching_any_gated_attempt(task,report)
        if attempt is None:
            raise ValueError(
                "escalate must reference a gated worker report for this task; do not author a parent escalation report. "
                "Analyst specialists use analysis-result --outcome escalate; Reviewer/Plan-Reviewer/Context-Reviewer "
                "use their own semantic outcome command"
            )
        role=str(attempt.get("role") or "")
        specialized={"reviewer","plan-reviewer","context-reviewer","planner","discovery","phase-surveyor","recovery","phase-auditor"}
        if role in specialized:
            raise ValueError(
                f"{role} escalation must be recorded through its semantic outcome command, "
                "not generic escalate"
            )
        require_current_attempt(task,attempt,reason="escalation")
        record=record_escalation(run,task,attempt,report,source="worker")
        task["updated_at"]=now(); write_json(path,task)
    return {"task_id":tid,"status":task["status"],"escalation_target":record["target"],"report":str(report)}


def command_resolve_escalation(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); decision=args.decision.resolve()
        escalation=task.get("last_escalation") if isinstance(task.get("last_escalation"),dict) else {}
        if task.get("status")!="blocked" or escalation.get("target")!="human":
            raise ValueError(f"resolve-escalation requires a Human-targeted blocked escalation; current status is {task.get('status')!r}")
        if not decision.is_file(): raise ValueError(f"decision file missing: {decision}")
        if decision.is_symlink(): raise ValueError("Human decision input must be a regular file, not a symlink")
        route=getattr(args,"route","resume")
        if route=="accept":
            if task.get("kind")!="implementation" or not task.get("requires_integration"):
                raise ValueError("Human accept route is only valid for a project-changing implementation task")
            review=task.get("last_review") if isinstance(task.get("last_review"),dict) else {}
            if review.get("outcome") not in {"fail","escalate"} or not Path(str(review.get("report") or "")).is_file():
                raise ValueError("Human accept route requires an existing fresh Reviewer FAIL/ESCALATE record; it cannot bypass task Review")
        authority_dir=run/"authority"/"decisions"; authority_dir.mkdir(parents=True,exist_ok=True)
        seq=len(task.get("human_decision_history",[]))+1
        snapshot=authority_dir/f"{phase}--{tid}--{seq:03d}.md"
        while snapshot.exists():
            seq+=1; snapshot=authority_dir/f"{phase}--{tid}--{seq:03d}.md"
        snapshot.write_bytes(decision.read_bytes())
        recorded={"path":str(snapshot.resolve()),"source_path":str(decision.resolve()),"recorded_at":now(),"escalation_report":escalation.get("report"),"route":route}
        task.setdefault("human_decision_history",[]).append(recorded); task["last_human_decision"]=recorded
        if route=="accept":
            task["status"]="accepted"; task["accepted_at"]=now(); task["accepted_report"]=str(snapshot.resolve())
            task["human_acceptance"]={
                "decision":str(snapshot.resolve()),
                "review_outcome":review.get("outcome"),
                "review_report":review.get("report"),
                "review_checkpoint_ref":review.get("checkpoint_ref"),
                "recorded_at":now(),
            }
        else:
            task["status"]="needs-analysis" if route=="analysis" else "planned"
        task["updated_at"]=now(); write_json(path,task)
    result={"task_id":tid,"status":task["status"],"decision":str(snapshot.resolve()),"route":route}
    if route=="accept": result["acceptance_basis"]="explicit-human-authority"
    return result


def release_read_only_runtime(run: Path, phase: str, task_id: str) -> bool:
    """Release task-local DB/binding for shared analysis-view tasks.

    Reports/plans live under the run tree, so accepted/result-only work does not need
    to retain a task-local checkout or session database. Reusable review conduits can
    reacquire the current shared view on their next fresh attempt.
    """
    ws_path=task_root(run,phase,task_id)/"workspace.json"
    if not ws_path.is_file(): return False
    try: ws=load_json(ws_path)
    except (OSError,ValueError,json.JSONDecodeError): return False
    if ws.get("mode")!="analysis-view": return False
    db_raw=ws.get("db")
    if isinstance(db_raw,str) and db_raw:
        db=Path(db_raw)
        for candidate in (db,Path(str(db)+"-wal"),Path(str(db)+"-shm")):
            try: candidate.unlink()
            except FileNotFoundError: pass
    ws["released"]=True; ws["released_at"]=now(); write_json(ws_path,ws)
    return True

def command_accept(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path)
        if task.get("requires_integration"):
            review=task.get("last_review") or {}
            if review.get("outcome")!="pass": raise ValueError("project-changing task requires an explicit fresh Reviewer PASS before acceptance")
        report=args.report.resolve() if args.report else None
        kind=str(task.get("kind") or "")
        status=str(task.get("status") or "")
        if kind=="implementation" and status!="review-passed": raise ValueError(f"implementation acceptance requires current review-passed state; current status is {status!r}")
        if kind=="analysis" and task.get("role") in {"plan-reviewer","context-reviewer"}:
            raise ValueError("Plan/Context Reviewer tasks are reusable review conduits; record their semantic outcome with the dedicated review command, do not accept the task itself")
        if kind=="analysis" and task.get("role")=="goal-planner":
            if status!="review-passed": raise ValueError(f"Goal-Planner acceptance requires current review-passed state; current status is {status!r}")
        elif kind in {"analysis","verification"} and status!="active": raise ValueError(f"{kind} acceptance requires a completed/gated specialist attempt in active task state; current status is {status!r}")
        if kind in {"analysis","verification"} and report is None:
            raise ValueError(f"{kind} task acceptance requires --report so dependent workers can consume the accepted specialist result")
        if report is not None and not report.is_file(): raise ValueError(f"accepted report missing: {report}")
        if kind=="analysis":
            attempt=matching_gated_attempt(task,BASE_ROLES_BY_KIND["analysis"],report) if report else None
            if attempt is None or attempt.get("tier")!="analyst": raise ValueError("analysis acceptance report must be the report from a gated Analyst attempt for this task")
            # Role selects Analyst expertise, not a mandatory artifact shape. A task
            # graph is required only by transitions that actually consume one
            # (replan/register-plan), so findings-only Planner work can close cleanly.
            if attempt.get("role")=="goal-planner":
                plan=require_analyst_goal_plan(attempt, reason="Goal-Planner acceptance")
                require_goal_plan_review(task, attempt, plan)
        elif kind=="verification":
            attempt=matching_gated_attempt(task,BASE_ROLES_BY_KIND["verification"],report) if report else None
            if attempt is None: raise ValueError("verification acceptance report must be the report from a gated Verification/Evidence-Clerk attempt for this task")
        elif kind=="implementation" and report is not None:
            review=task.get("last_review") or {}
            if str(review.get("report") or "") != str(report): raise ValueError("implementation acceptance report, when supplied, must be the recorded passing Reviewer report")
        task["status"]="accepted"; task["accepted_at"]=now()
        if report: task["accepted_report"]=str(report)
        task["updated_at"]=now(); write_json(path,task)
    released=release_read_only_runtime(run,phase,tid)
    return {"task_id":tid,"status":"accepted","requires_integration":bool(task.get("requires_integration")),"runtime_released":released}


def command_integrated(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path)
        if task.get("status")!="accepted": raise ValueError("task must be accepted before integration")
        integration_paths=getattr(args,"integration_paths",None)
        integration_untracked=getattr(args,"integration_untracked_paths",None)
        if integration_paths is not None: task["integration_paths"]=list(dict.fromkeys(str(x) for x in integration_paths if str(x)))
        if integration_untracked is not None: task["integration_untracked_paths"]=list(dict.fromkeys(str(x) for x in integration_untracked if str(x)))
        task["status"]="integrated"; task["integrated_at"]=now(); task["updated_at"]=now(); write_json(path,task)
    return {"task_id":tid,"status":"integrated"}


def command_supersede(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path)
        if task.get("status")=="integrated": raise ValueError("cannot supersede an integrated task; add an amending task that depends on it")
        if task_has_live_attempt(task): raise ValueError("cannot supersede a task with a live attempt")
        task["status"]="superseded"; task["superseded_at"]=now();
        if args.by: task["superseded_by"]=slug(args.by)
        write_json(path,task)
    released=release_read_only_runtime(run,phase,tid)
    return {"task_id":tid,"status":"superseded","runtime_released":released}


def parser() -> argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="command",required=True)
    p=sub.add_parser("init-run"); p.add_argument("--project-root",type=Path,required=True); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--run-id",required=True); p.add_argument("--runtime-root"); p.add_argument("--max-workers",type=int,default=4); p.add_argument("--grunt-driver"); p.add_argument("--grunt-model"); p.add_argument("--analyst-driver"); p.add_argument("--analyst-model"); p.add_argument("--escalation",choices=("on","off"),default="on")
    p=sub.add_parser("runtime-status"); p.add_argument("--run-root",type=Path,required=True)
    p=sub.add_parser("set-runtime"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--tier",choices=sorted(TIERS),required=True); p.add_argument("--driver",required=True); p.add_argument("--model",required=True); p.add_argument("--allow-unwired-driver",action="store_true",help=argparse.SUPPRESS)
    p=sub.add_parser("set-escalation"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--mode",choices=("on","off"),required=True)
    p=sub.add_parser("set-run-status"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--status",choices=sorted(RUN_STATUSES),required=True); p.add_argument("--reason")
    p=sub.add_parser("preflight-plan"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--plan",type=Path,required=True)
    p=sub.add_parser("register-plan"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--plan",type=Path,required=True)
    p=sub.add_parser("register-direct",description="Direct registration is limited to Analyst analysis/control tasks or an explicit Human-authorized Implementer task. Verification and inferred implementation must come from an approved Analyst graph."); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True); p.add_argument("--brief",type=Path,required=True); p.add_argument("--kind",choices=sorted(KINDS),required=True); p.add_argument("--role",choices=sorted(ROLE_NAMES)); p.add_argument("--tier",choices=sorted(TIERS)); p.add_argument("--dependency",action="append",default=[]); p.add_argument("--requires-integration",dest="requires_integration",action="store_true"); p.add_argument("--no-integration",dest="requires_integration",action="store_false"); p.add_argument("--reviews-task"); p.add_argument("--owner-authority",type=Path); p.set_defaults(requires_integration=None)
    p=sub.add_parser("ready"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True)
    p=sub.add_parser("list"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id"); p.add_argument("--status",choices=sorted(STATUSES))
    p=sub.add_parser("sweep-stale"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id")
    p=sub.add_parser("reconcile-run"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id"); p.add_argument("--no-sweep",action="store_true"); p.add_argument("--details",action="store_true")
    p=sub.add_parser("idle-check"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id")
    for name in ("show", "record-attempt", "update-attempt", "review", "plan-review", "context-review", "analysis-result", "escalate", "resolve-escalation", "accept", "integrated", "supersede"):
        description="Record the semantic outcome of a gated Analyst result. resume/replan-resume are only valid when an implementation/verification task is returning from Analyst diagnosis." if name=="analysis-result" else None
        p=sub.add_parser(name,description=description); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True)
        if name=="record-attempt": p.add_argument("--attempt-json",type=Path,required=True)
        elif name=="update-attempt": p.add_argument("--event-dir",type=Path,required=True); p.add_argument("--status",choices=sorted(ATTEMPT_STATUSES)); p.add_argument("--gate",type=Path); p.add_argument("--session-id")
        elif name=="review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="plan-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="context-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="analysis-result": p.add_argument("--outcome",choices=("resume","replan","replan-resume","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="escalate": p.add_argument("--report",type=Path,required=True)
        elif name=="resolve-escalation": p.add_argument("--decision",type=Path,required=True); p.add_argument("--route",choices=("resume","analysis","accept"),default="resume")
        elif name=="accept": p.add_argument("--report",type=Path)
        elif name=="supersede": p.add_argument("--by")
    return ap


def main() -> int:
    args=parser().parse_args()
    try:
        if args.command=="init-run": result=command_init(args)
        elif args.command=="runtime-status": result=command_runtime_status(args)
        elif args.command=="set-runtime": result=command_set_runtime(args)
        elif args.command=="set-escalation": result=command_set_escalation(args)
        elif args.command=="set-run-status": result=command_set_run_status(args)
        elif args.command=="preflight-plan": result=command_preflight_plan(args)
        elif args.command=="register-plan": result=command_register_plan(args)
        elif args.command=="register-direct": result=command_register_direct(args)
        elif args.command=="ready": result=command_ready(args)
        elif args.command=="list": result=command_list(args)
        elif args.command=="sweep-stale": result=command_sweep_stale(args)
        elif args.command=="reconcile-run": result=command_reconcile_run(args)
        elif args.command=="idle-check": result=command_idle_check(args)
        elif args.command=="show": result=command_show(args)
        elif args.command=="record-attempt": result=command_record_attempt(args)
        elif args.command=="update-attempt": result=command_update_attempt(args)
        elif args.command=="review": result=command_review(args)
        elif args.command=="plan-review": result=command_plan_review(args)
        elif args.command=="context-review": result=command_context_review(args)
        elif args.command=="analysis-result": result=command_analysis_result(args)
        elif args.command=="escalate": result=command_escalate(args)
        elif args.command=="resolve-escalation": result=command_resolve_escalation(args)
        elif args.command=="accept": result=command_accept(args)
        elif args.command=="integrated": result=command_integrated(args)
        else: result=command_supersede(args)
        print(json.dumps(result,sort_keys=True,separators=(",",":"))); return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"command":getattr(args,"command",None),"error":str(exc)},sort_keys=True,separators=(",",":")))
        print(f"ERROR: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
