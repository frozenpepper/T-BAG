#!/usr/bin/env python3
"""Launch, inspect, follow and gate one task-local T-BAG worker attempt."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dsd_task
import dsd_workspace
import report_surface as report_surface_helper
from _roles import DEFAULT_TIER, ROLE_NAMES
from _rules_snapshot import rules_revisions, verify_snapshot


def run_checked(cmd:list[str],allowed:set[int]={0})->subprocess.CompletedProcess[str]:
    cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode not in allowed:
        raise ValueError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{(cp.stderr or cp.stdout).strip()[:1500]}")
    return cp


def pid_alive(pid:Any)->bool:
    if not isinstance(pid,int) or pid<=0: return False
    try: os.kill(pid,0); return True
    except OSError: return False


def latest_rules(run:Path)->Path:
    candidates=rules_revisions(run)
    if not candidates: raise ValueError("no worker-rules revision exists; run prepare_worker_rules.py first")
    return candidates[-1].resolve()




def attempt_worker_rules(attempt: dict[str, Any]) -> str | None:
    value = attempt.get("worker_rules")
    if isinstance(value, str) and value:
        return str(Path(value).resolve())
    event = Path(str(attempt.get("event_dir") or ""))
    reservation = event / "launch-reservation.json"
    if reservation.is_file():
        try:
            data = json.loads(reservation.read_text())
            value = data.get("worker_rules")
            if isinstance(value, str) and value:
                return str(Path(value).resolve())
        except (OSError, json.JSONDecodeError):
            pass
    return None


def attempt_session_id(attempt: dict[str, Any]) -> str | None:
    value = attempt.get("session_id")
    if isinstance(value, str) and value:
        return value
    event = Path(str(attempt.get("event_dir") or ""))
    for evidence in (event / "attempt.json", event / "terminal.json"):
        if not evidence.is_file(): continue
        try:
            value = json.loads(evidence.read_text()).get("session_id")
            if isinstance(value, str) and value:
                return value
        except (OSError, json.JSONDecodeError):
            pass
    return None


def rules_for_resumed_session(task: dict[str, Any], session_id: str) -> Path | None:
    """Return the rules revision originally used by a resumed CLI session."""
    for attempt in reversed(task.get("attempts", [])):
        if not isinstance(attempt, dict) or attempt_session_id(attempt) != session_id:
            continue
        value = attempt_worker_rules(attempt)
        return Path(value).resolve() if value else None
    return None

def attempt_number(task_root:Path,role:str)->int:
    root=task_root/"attempts"; n=0; pattern=re.compile(rf"^{re.escape(role)}-(\d+)$")
    if root.is_dir():
        for p in root.iterdir():
            m=pattern.match(p.name)
            if m: n=max(n,int(m.group(1)))
    return n+1


def live_same_task(task:dict[str,Any])->list[dict[str,Any]]:
    return [a for a in task.get("attempts",[]) if isinstance(a,dict) and dsd_task.attempt_is_live(a)]


def live_run_attempts(run:Path)->list[dict[str,Any]]:
    live=[]
    phases=run/"phases"
    for path in phases.glob("*/tasks/*/task.json") if phases.is_dir() else []:
        try:
            task=dsd_task.load_json(path)
        except Exception:
            continue
        live.extend(live_same_task(task))
    return live


def resolve_runtime(run_info:dict[str,Any],tier:str,driver_override:str|None,model_override:str|None,profile_name:str|None=None)->tuple[str,str,dict[str,Any],str]:
    if profile_name and (driver_override or model_override):
        raise ValueError("choose a configured --runtime-profile or an explicit driver/model override, not both")
    if profile_name:
        configured=dsd_task.runtime_profile(run_info,tier,profile_name)
        if configured is None:
            raise ValueError(f"runtime profile {tier}/{profile_name} is not configured or has no remaining uses")
        selected=str(configured.get("name") or profile_name)
    else:
        configured=dsd_task.runtime_config(run_info,tier)
        selected="default"
    configured_driver=str((configured or {}).get("driver") or "").strip()
    if driver_override and configured_driver and driver_override.strip()!=configured_driver and not model_override:
        raise ValueError(
            f"RUNTIME_OVERRIDE_MISMATCH: --driver {driver_override!r} differs from configured {tier} driver {configured_driver!r}; "
            "supply an explicit --model for that driver or register/select a runtime profile"
        )
    driver=(driver_override or (configured or {}).get("driver") or "").strip()
    model=(model_override or (configured or {}).get("model") or "").strip()
    options=(configured or {}).get("options") if isinstance((configured or {}).get("options"),dict) else {}
    if not driver or not model:
        raise ValueError(f"MISSING_RUNTIME_CONFIG: {tier} authority lane needs a default driver/model; resolve it from owner authority/run config or ask once")
    if driver not in dsd_task.SUPPORTED_WORKER_DRIVERS:
        raise ValueError(f"worker driver {driver!r} has no first-class T-BAG adapter; wired drivers: {sorted(dsd_task.SUPPORTED_WORKER_DRIVERS)}")
    return driver,model,dict(options),selected


def latest_session(task:dict[str,Any],role:str)->str|None:
    for attempt in reversed(task.get("attempts",[])):
        if not isinstance(attempt,dict) or attempt.get("role")!=role: continue
        sid=attempt_session_id(attempt)
        if sid: return sid
    return None



def resolve_resume_session(task:dict[str,Any], role:str, status:str, explicit:str|None, resume_last:bool)->str|None:
    """Choose session continuity for one role without inferring semantic completion.

    Normal task loop:
      Implementer: fresh unless explicitly continuing the unfinished Implementer.
      Reviewer: always fresh.
      Fixer: first Fixer turn resumes the Reviewer session that produced the findings;
             interrupted Fixer turns may resume that same Fixer session.
    Analyst roles use their own explicit same-role continuation only.
    """
    if role in {"reviewer","plan-reviewer","context-reviewer","phase-auditor"}:
        if explicit or resume_last:
            raise ValueError(f"{role} must always start in a fresh session")
        return None
    if role=="fixer" and status=="needs-fix":
        reviewer_sid=latest_session(task,"reviewer")
        if explicit:
            if reviewer_sid and explicit != reviewer_sid:
                raise ValueError("Fixer must resume the Reviewer session that produced the current findings; explicit session does not match it")
            return explicit
        if resume_last:
            raise ValueError("A new Fixer round must resume the current Reviewer session automatically; --resume-last is only for continuing an interrupted Fixer turn")
        if not reviewer_sid:
            raise ValueError("Fixer must resume the Reviewer session that produced the current findings; no Reviewer session ID is recorded (recover it explicitly or route transport recovery)")
        return reviewer_sid
    if resume_last:
        sid=latest_session(task,role)
        if not sid:
            raise ValueError(f"no prior {role} session is recorded for this task")
        return sid
    return explicit

def latest_attempt_report(task:dict[str,Any], roles:set[str])->str|None:
    for attempt in reversed(task.get("attempts", [])):
        if not isinstance(attempt, dict) or attempt.get("role") not in roles:
            continue
        event = Path(str(attempt.get("event_dir") or ""))
        report = event / "report.md"
        if report.is_file():
            return str(report.resolve())
    return None


def plan_review_target(run:Path, phase:str, task:dict[str,Any]) -> dict[str,str]:
    target_id=str(task.get("reviews_task") or "")
    if not target_id:
        raise ValueError("Plan Reviewer task is missing reviews_task binding")
    target=dsd_task.load_task(run,phase,target_id)
    if target.get("role")!="goal-planner":
        raise ValueError("Plan Reviewer target is not a Goal-Planner task")
    if target.get("status") in {"accepted","integrated","superseded"}:
        raise ValueError(f"Goal-Planner target is already {target.get('status')!r}; do not launch another Plan Review")
    if target.get("status")=="blocked":
        raise ValueError("Goal-Planner target is blocked on an owner decision; do not launch another Plan Review")
    # The Goal-Planner task is the authoritative record of Plan-Review outcomes.
    # Using it here also keeps recovery sane if a process dies after persisting the
    # target outcome but before mirroring convenience history onto the reviewer task.
    recorded={str(x.get("reviewer_attempt") or "") for x in target.get("plan_review_history",[]) if isinstance(x,dict)}
    for review_attempt in task.get("attempts",[]):
        if not isinstance(review_attempt,dict) or review_attempt.get("role")!="plan-reviewer" or review_attempt.get("status")!="gated":
            continue
        event=str(review_attempt.get("event_dir") or "")
        if event and event not in recorded:
            raise ValueError("record the completed Plan-Reviewer attempt outcome before launching another fresh Plan Reviewer")
    attempt=dsd_task.latest_gated_attempt(target,"goal-planner")
    if attempt is None:
        raise ValueError("Plan Reviewer requires a gated Goal-Planner attempt")
    planner_event=Path(str(attempt.get("event_dir") or "")).resolve()
    role_attempts=[a for a in target.get("attempts",[]) if isinstance(a,dict) and a.get("role")=="goal-planner"]
    if not role_attempts or Path(str(role_attempts[-1].get("event_dir") or "")).resolve()!=planner_event:
        raise ValueError("Plan Reviewer cannot start while a newer Goal-Planner attempt is unresolved or unreviewable")
    prior=target.get("last_plan_review") if isinstance(target.get("last_plan_review"),dict) else {}
    if prior and Path(str(prior.get("planner_attempt") or "")).resolve()==planner_event:
        outcome=str(prior.get("outcome") or "unknown")
        raise ValueError(f"this Goal-Planner attempt already has Plan-Reviewer outcome {outcome!r}; revise the Planner after FAIL, accept after PASS, or resolve the owner decision")
    plan=dsd_task.require_analyst_goal_plan(attempt, reason="Plan Review")
    return {"task_id":target_id,"attempt":str(planner_event),"plan":str(plan.resolve())}


def context_review_target(run:Path, phase:str, task:dict[str,Any]) -> dict[str,str]:
    target_id=str(task.get("reviews_task") or "")
    if not target_id: raise ValueError("Context Reviewer task is missing reviews_task binding")
    target=dsd_task.load_task(run,phase,target_id)
    if target.get("kind")!="analysis" or target.get("role") not in dsd_task.CONTEXT_AUTHOR_ROLES:
        raise ValueError("Context Reviewer target is not a reusable-context-authoring Analyst task")
    recorded={str(x.get("reviewer_attempt") or "") for x in target.get("context_review_history",[]) if isinstance(x,dict)}
    for review_attempt in task.get("attempts",[]):
        if not isinstance(review_attempt,dict) or review_attempt.get("role")!="context-reviewer" or review_attempt.get("status")!="gated": continue
        event=str(review_attempt.get("event_dir") or "")
        if event and event not in recorded:
            raise ValueError("record the completed Context-Reviewer outcome before launching another fresh Context Reviewer")
    author_attempts=[a for a in target.get("attempts",[]) if isinstance(a,dict) and a.get("role") in dsd_task.CONTEXT_AUTHOR_ROLES]
    if not author_attempts: raise ValueError("Context Reviewer requires an Analyst source attempt")
    latest=author_attempts[-1]
    if latest.get("status")!="gated": raise ValueError("Context Reviewer cannot start while the latest source Analyst attempt is unresolved")
    event=Path(str(latest.get("event_dir") or "")).resolve()
    if not dsd_task.has_proposed_context(latest): raise ValueError("latest source Analyst attempt contains no reusable context proposal")
    prior=target.get("last_context_review") if isinstance(target.get("last_context_review"),dict) else {}
    if prior and Path(str(prior.get("source_attempt") or "")).resolve()==event:
        raise ValueError(f"this Analyst attempt already has Context-Reviewer outcome {prior.get('outcome')!r}; revise the source after FAIL or adopt after PASS")
    return {"task_id":target_id,"attempt":str(event)}


def validate_plan_authority_for_launch(rules:Path, phase:str, role:str, task:dict[str,Any]|None=None) -> dict[str,Any]:
    snapshot=verify_snapshot(rules)
    if snapshot.get("authority_plan") is None:
        direct=Path(str((task or {}).get("direct_owner_authority") or ""))
        owner_direct=bool(str(direct) not in {".",""} and direct.is_file())
        bootstrap=phase=="bootstrap" and role in {"goal-planner","plan-reviewer","context-reviewer"}
        if not (bootstrap or owner_direct):
            raise ValueError("NO_ACCEPTED_PLAN: planless execution requires bootstrap planning/review or a frozen direct owner authority; otherwise accept and snapshot a reviewed plan before normal execution")
    return snapshot


def _add_input(groups: dict[str,list[str]], key: str, value: str | Path | None) -> None:
    if value is None: return
    path=Path(str(value)).resolve()
    if path.exists(): groups.setdefault(key,[]).append(str(path))


def task_input_groups(run:Path, phase:str, task:dict[str,Any], role:str, extra:list[str])->dict[str,list[str]]:
    groups: dict[str,list[str]]={}
    for raw in extra: _add_input(groups,"authority_input",raw)
    _add_input(groups,"owner_decision",task.get("direct_owner_authority"))
    for raw in task.get("followup_source_reports",[]) if isinstance(task.get("followup_source_reports"),list) else []:
        _add_input(groups,"review_finding",raw)
    analysis=task.get("last_analysis") or {}
    if analysis.get("outcome") in {"resume","replan","replan-resume"}:
        _add_input(groups,"analyst_finding",analysis.get("report"))
    decision=task.get("last_human_decision") or task.get("last_decision") or {}
    _add_input(groups,"owner_decision",decision.get("path"))
    if decision.get("path"):
        escalation=task.get("last_escalation") if isinstance(task.get("last_escalation"),dict) else {}
        _add_input(groups,"escalation_context",escalation.get("report"))
    for dep_id in task.get("dependencies", []):
        try: dep=dsd_task.load_task(run, phase, str(dep_id))
        except ValueError: continue
        _add_input(groups,"dependency_finding",dep.get("accepted_report"))
    if role=="goal-planner":
        prior=task.get("last_plan_review") or {}
        _add_input(groups,"review_finding",prior.get("report"))
    elif role=="plan-reviewer":
        target=plan_review_target(run,phase,task)
        goal=dsd_task.load_task(run,phase,target["task_id"])
        planner_attempt=next((a for a in goal.get("attempts",[]) if isinstance(a,dict) and Path(str(a.get("event_dir") or "")).resolve()==Path(target["attempt"]).resolve()),None)
        if planner_attempt is None: raise ValueError("Plan Reviewer cannot resolve recorded Goal-Planner attempt")
        _add_input(groups,"authority_input",goal.get("brief"))
        recorded=planner_attempt.get("inputs_by_type") if isinstance(planner_attempt.get("inputs_by_type"),dict) else None
        if recorded:
            for key,values in recorded.items():
                if key not in {"authority_input","owner_decision","analyst_finding","dependency_finding","decision_context","review_finding","worker_report","recovery_evidence","proposal_input"}: continue
                if isinstance(values,list):
                    for value in values: _add_input(groups,key,value)
        else:
            for original in planner_attempt.get("inputs",[]): _add_input(groups,"authority_input",original)
        _add_input(groups,"proposal_input",target["plan"])
    elif role=="context-reviewer":
        target=context_review_target(run,phase,task)
        source=dsd_task.load_task(run,phase,target["task_id"])
        source_attempt=next((a for a in source.get("attempts",[]) if isinstance(a,dict) and Path(str(a.get("event_dir") or "")).resolve()==Path(target["attempt"]).resolve()),None)
        if source_attempt is None: raise ValueError("Context Reviewer cannot resolve recorded source Analyst attempt")
        _add_input(groups,"authority_input",source.get("brief")); _add_input(groups,"worker_report",Path(target["attempt"])/"report.md")
        recorded=source_attempt.get("inputs_by_type") if isinstance(source_attempt.get("inputs_by_type"),dict) else None
        if recorded:
            for key,values in recorded.items():
                if isinstance(values,list):
                    for value in values: _add_input(groups,key,value)
        else:
            for original in source_attempt.get("inputs",[]): _add_input(groups,"authority_input",original)
    elif role=="reviewer":
        _add_input(groups,"worker_report",latest_attempt_report(task,{"implementer","fixer","verification"}))
    elif role=="fixer":
        review=task.get("last_review") or {}; _add_input(groups,"review_finding",review.get("report"))
    elif role in {"discovery","recovery"}:
        review=task.get("last_review") or {}; _add_input(groups,"review_finding",review.get("report"))
        conflict=task.get("last_integration_conflict") if isinstance(task.get("last_integration_conflict"),dict) else {}
        _add_input(groups,"recovery_evidence",conflict.get("evidence"))
        workspace_conflict=task.get("last_workspace_conflict") if isinstance(task.get("last_workspace_conflict"),dict) else {}
        _add_input(groups,"recovery_evidence",workspace_conflict.get("evidence"))
        escalation=task.get("last_escalation") if isinstance(task.get("last_escalation"),dict) else {}
        escalation_report=escalation.get("report") if escalation.get("target")=="analyst" else None
        _add_input(groups,"escalation_context",escalation_report)
        latest=latest_attempt_report(task,{"implementer","fixer","verification"})
        same_as_escalation = bool(
            latest and escalation_report and Path(latest).resolve()==Path(str(escalation_report)).resolve()
        )
        if latest and not same_as_escalation:
            _add_input(groups,"worker_report",latest)
        if role=="recovery":
            attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
            latest_event=None
            for prior in reversed(attempts):
                event=Path(str(prior.get("event_dir") or ""))
                if event.is_dir():
                    latest_event=event; _add_input(groups,"recovery_evidence",event); break
            for prior in reversed(attempts):
                if prior.get("role") in {"recovery","discovery"}: continue
                event=Path(str(prior.get("event_dir") or ""))
                if event.is_dir() and (latest_event is None or event.resolve()!=latest_event.resolve()):
                    _add_input(groups,"recovery_evidence",event)
                break
    for key,values in list(groups.items()): groups[key]=list(dict.fromkeys(values))
    return groups


def validate_launch_role(task:dict[str,Any], role:str, *, continuing:bool=False)->None:
    kind=str(task.get("kind") or "")
    status=str(task.get("status") or "")
    base=str(task.get("role") or "")
    if role==base:
        if status=="recovery-required":
            raise ValueError("task requires Analyst Recovery before the base role may continue")
        attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
        latest=attempts[-1] if attempts else {}
        if latest.get("status") in {"report-recovery","report-resume","mutating-report-resume"} and not continuing and (latest.get("session_id") or latest.get("resume_session")):
            raise ValueError("latest attempt has resumable context; resume the recorded same-role session instead of discarding it")
        return
    if role=="reviewer":
        if not task.get("requires_integration") or status!="awaiting-review":
            raise ValueError("Reviewer is a task-local transition only for project-changing work awaiting review")
        return
    if role=="fixer":
        if status in {"active","awaiting-review"} and continuing: return
        if status!="needs-fix": raise ValueError(f"Fixer launch requires task status needs-fix (or explicit same-session continuation after an unfinished Fixer turn); current status is {status!r}")
        return
    if role in {"discovery","recovery"}:
        if status not in {"needs-analysis","recovery-required","active"}:
            raise ValueError(f"Analyst diagnosis/recovery requires needs-analysis or recovery-required task state; current status is {status!r}")
        return
    raise ValueError(f"role {role!r} is not a valid transition for {kind} task with base role {base!r}")


def copy_context_snapshot(source_event: Path, dest_root: Path) -> None:
    files=dsd_task.proposed_context_files(source_event)
    if not files: raise ValueError("Context Reviewer source attempt contains no reusable context proposal")
    for rel,source in files.items():
        dest=dest_root/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,dest)


def _command_launch(args:argparse.Namespace)->dict[str,Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    info=dsd_task.load_run(run); task=dsd_task.load_task(run,phase,tid)
    run_status=str(info.get("status") or "active")
    if run_status!="active":
        raise ValueError(f"run is {run_status!r}; set run status active before launching more workers")
    live=live_same_task(task)
    if live: raise ValueError(f"task already has a live attempt: {live[-1].get('event_dir')}")
    status=str(task.get("status") or "")
    if status in {"accepted","integrated","superseded"}: raise ValueError(f"task is complete and cannot launch another worker: {status}")
    if status=="blocked": raise ValueError("task is blocked on a Human-targeted escalation; resolve the escalation before launching more technical work")
    role=args.role or str(task.get("role") or "")
    if role not in ROLE_NAMES: raise ValueError(f"unknown role: {role}")
    tier=DEFAULT_TIER[role]
    if args.tier and args.tier != tier:
        raise ValueError(f"{role} is fixed to the {tier} authority lane; choose a runtime profile instead of changing authority")
    profile_name=getattr(args,"runtime_profile",None) or task.get("pending_runtime_profile")
    if role=="fixer" and status=="needs-fix" and not profile_name:
        for prior in reversed(task.get("attempts",[])):
            if isinstance(prior,dict) and prior.get("role")=="reviewer":
                profile_name=str(prior.get("runtime_profile") or "default"); break
    continuing=bool(args.resume_last or args.resume_session)
    if role in {"reviewer","plan-reviewer","context-reviewer","phase-auditor"} and continuing:
        raise ValueError(f"{role} must always start in a fresh session; independent review may not resume prior worker/reviewer context")
    validate_launch_role(task,role,continuing=continuing)
    unresolved=[a for a in task.get("attempts",[]) if isinstance(a,dict) and dsd_task.attempt_is_unresolved(a)]
    dead_unresolved=[a for a in unresolved if not dsd_task.attempt_is_live(a)]
    if dead_unresolved and role!="recovery":
        raise ValueError(f"UNRESOLVED_ATTEMPT: prior attempt has no terminal event: {dead_unresolved[-1].get('event_dir')}; run sweep-stale first so T-BAG can mechanically decide safe retry versus Recovery")
    if role not in {"reviewer","fixer","recovery"}:
        ok,missing=dsd_task.readiness(run,phase,task)
        if not ok: raise ValueError(f"task dependencies not satisfied/integrated: {missing}")
    if role=="implementer":
        if status=="awaiting-review" and not continuing:
            raise ValueError("implementation turn is awaiting Review; use --resume-last only when the same task is genuinely unfinished, otherwise launch the Reviewer")
        if status in {"needs-analysis","needs-fix","review-passed","accepted","superseded","integrated","recovery-required","blocked"}:
            raise ValueError(f"task is not implementation-runnable: {status}")
    if role=="goal-planner":
        latest=(task.get("attempts") or [{}])[-1] if isinstance(task.get("attempts"),list) and task.get("attempts") else {}
        cold_transport_retry=bool(status=="active" and latest.get("status") in {"report-recovery","report-resume","mutating-report-resume"} and not (latest.get("session_id") or latest.get("resume_session")))
        if status=="active" and not continuing and not cold_transport_retry:
            raise ValueError("completed Goal-Planner work is awaiting Plan Review; launch the fresh Plan Reviewer instead of starting another planning turn")
        if status not in {"planned","active"}:
            raise ValueError(f"Goal Planner is not planning-runnable: {status}")
    resume=resolve_resume_session(task,role,status,args.resume_session,bool(args.resume_last))
    if args.worker_rules:
        rules=Path(args.worker_rules).resolve()
    elif resume:
        pinned=rules_for_resumed_session(task,resume)
        if pinned is None:
            raise ValueError("cannot determine the worker-rules revision originally supplied to the resumed session; pass --worker-rules explicitly only if deliberate rebriefing is intended")
        rules=pinned
    else:
        rules=latest_rules(run)
    rules_snapshot=validate_plan_authority_for_launch(rules,phase,role,task)
    ws=dsd_workspace.prepare_launch_workspace(run,phase,tid,role); wt=Path(ws["worktree"]); db=Path(args.db).resolve() if args.db else Path(ws["db"])
    workspace_mode=str(ws.get("mode") or "isolated-worktree")
    if workspace_mode=="isolated-worktree":
        # Declared ignored fixtures are inputs, not task-authored proof state. Restore
        # them from the frozen task-local snapshot before every attempt.
        dsd_workspace.refresh_task_fixtures(run,phase,tid)
    number=args.attempt or attempt_number(dsd_task.task_root(run,phase,tid),role)
    label=f"{role}-{number}"
    if workspace_mode=="isolated-worktree":
        class C: pass
        c=C(); c.run_root=run; c.phase_id=phase; c.task_id=tid; c.label=label
        checkpoint_info=dsd_workspace.command_checkpoint(c); checkpoint=checkpoint_info["checkpoint_ref"]; checkpoint_oid=checkpoint_info["checkpoint_oid"]
    elif workspace_mode=="analysis-view":
        checkpoint=str(ws.get("baseline_ref") or "")
        if not checkpoint: raise ValueError("analysis-view workspace is missing its frozen baseline ref")
        checkpoint_oid=dsd_workspace.git_text(wt,"rev-parse",checkpoint)
    else:
        raise ValueError(f"unsupported workspace mode: {workspace_mode!r}")
    event=dsd_task.task_root(run,phase,tid)/"attempts"/label; event.mkdir(parents=True,exist_ok=False)
    baseline=event/"scope-baseline.json"; prompt=event/"launch-prompt.txt"; report=event/"report.md"; log=event/"worker.log"
    scripts=Path(__file__).resolve().parent
    scope_cmd=[sys.executable,str(scripts/"scope_snapshot.py"),"capture","--root",str(wt),"--baseline-ref",checkpoint,"--output",str(baseline)]
    for rel in ws.get("fixture_mirrors",[]) if isinstance(ws.get("fixture_mirrors"),list) else []:
        scope_cmd += ["--exclude-prefix",str(rel)]
    run_checked(scope_cmd)
    brief=Path(str(task["brief"])).resolve(); input_groups=task_input_groups(run,phase,task,role,args.input or [])
    if role=="phase-auditor":
        dossier=event/"phase-gate-dossier.md"
        dossier.write_text(dsd_task.phase_gate_dossier_text(run,phase,tid),encoding="utf-8")
        _add_input(input_groups,"authority_input",dossier)
    authority_roles={"goal-planner","plan-reviewer","context-reviewer","planner","discovery","phase-surveyor","recovery","phase-auditor"}
    if role in authority_roles:
        plan_path=rules_snapshot.get("authority_plan")
        for raw in rules_snapshot.get("authority_files",[]):
            if plan_path and Path(raw).resolve()==Path(plan_path).resolve(): continue
            _add_input(input_groups,"authority_input",raw)
    if (role in {"planner","phase-surveyor","phase-auditor"} or (role in {"discovery","recovery"} and status=="needs-analysis")) and rules_snapshot.get("authority_plan"):
        _add_input(input_groups,"authority_input",rules_snapshot["authority_plan"])
    plan_review_binding=None; context_review_binding=None
    if role=="plan-reviewer":
        plan_review_binding=plan_review_target(run,phase,task)
        source_plan=Path(plan_review_binding["plan"]).resolve()
        snapshot=event/"plan-under-review"/"PLAN.md"; snapshot.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source_plan,snapshot)
        proposal=input_groups.get("proposal_input",[])
        input_groups["proposal_input"]=[p for p in proposal if Path(p).resolve()!=source_plan]
        _add_input(input_groups,"proposal_input",snapshot)
        plan_review_binding={**plan_review_binding,"source_plan":str(source_plan),"plan_snapshot":str(snapshot.resolve())}
    elif role=="context-reviewer":
        context_review_binding=context_review_target(run,phase,task)
        source_event=Path(context_review_binding["attempt"]).resolve()
        snapshot_root=event/"context-under-review"; snapshot_root.mkdir(parents=True,exist_ok=True); copy_context_snapshot(source_event,snapshot_root)
        _add_input(input_groups,"proposal_input",snapshot_root)
        context_review_binding={**context_review_binding,"context_snapshot":str(snapshot_root.resolve())}
    prompt_cmd=[sys.executable,str(scripts/"render_worker_prompt.py"),"--role",role,"--task-id",tid,"--phase-id",phase,"--run-root",str(run),"--worker-rules",str(rules),"--task",str(brief),"--report",str(report),"--project-root",str(wt),"--output",str(prompt)]
    for key,values in input_groups.items():
        flag="--"+key.replace("_","-")
        for value in values: prompt_cmd += [flag,str(Path(value).resolve())]
    run_checked(prompt_cmd)
    if role in {"implementer","reviewer","fixer"} and (args.driver or args.model):
        configured=dsd_task.runtime_config(info,"grunt") or {}
        requested_driver=(args.driver or configured.get("driver") or "").strip()
        requested_model=(args.model or configured.get("model") or "").strip()
        if requested_driver != str(configured.get("driver") or "") or requested_model != str(configured.get("model") or ""):
            raise ValueError("Implementer/Reviewer/Fixer must use the configured Grunt runtime; change the run configuration rather than switching models inside one task loop")
    driver,model,runtime_options,selected_profile=resolve_runtime(info,tier,args.driver,args.model,str(profile_name) if profile_name else None)
    if selected_profile!="default":
        # A configured max-use profile is an owner spend authorization. Reserving a
        # use before process launch prevents concurrent parents from overspending it.
        dsd_task.consume_runtime_profile(run,tier,selected_profile)
    launch_cmd=[sys.executable,str(scripts/"run_worker.py"),"--project-root",str(wt),"--run-root",str(run),"--task-id",tid,"--role",role,"--attempt",str(number),"--prompt-file",str(prompt),"--task-contract",str(brief),"--worker-rules",str(rules),"--scope-baseline",str(baseline),"--report",str(report),"--event-dir",str(event),"--log",str(log),"--db",str(db),"--driver",driver,"--model",model,"--tier",tier,"--detach"]
    launch_interval=float(info.get("launch_start_interval_seconds",dsd_task.DEFAULT_LAUNCH_START_INTERVAL_SECONDS))
    launch_cmd += ["--launch-start-interval-seconds",str(launch_interval)]
    effort=str(runtime_options.get("effort") or "").strip()
    if effort: launch_cmd += ["--effort",effort]
    if resume: launch_cmd += ["--resume-session",resume]
    if args.auto_flag is not None: launch_cmd += [f"--auto-flag={args.auto_flag}"]
    cp=run_checked(launch_cmd); launch=json.loads(cp.stdout)
    record={"task_id":tid,"role":role,"tier":tier,"runtime_profile":selected_profile,"driver":driver,"model":model,"attempt":number,"event_dir":str(event),"status":"started","monitor_pid":launch.get("monitor_pid"),"checkpoint_ref":checkpoint,"checkpoint_oid":checkpoint_oid,"resume_session":resume,"worker_rules":str(rules),"workspace_mode":workspace_mode,"project_root":str(wt),"workspace_primary_head":ws.get("primary_head"),"workspace_primary_status":ws.get("primary_status"),"analysis_view_generation":ws.get("analysis_view_generation"),"inputs":[p for values in input_groups.values() for p in values],"inputs_by_type":input_groups}
    if runtime_options: record["runtime_options"]=runtime_options
    if role=="plan-reviewer": record["plan_review_target"]=plan_review_binding
    if role=="context-reviewer": record["context_review_target"]=context_review_binding
    record_path=event/"task-attempt.json"; dsd_task.write_json(record_path,record)
    class R: pass
    r=R(); r.run_root=run; r.phase_id=phase; r.task_id=tid; r.attempt_json=record_path
    dsd_task.command_record_attempt(r)
    if task.get("pending_runtime_profile")==selected_profile:
        state_path=dsd_task.task_file(run,phase,tid)
        with dsd_task.file_lock(state_path.with_suffix(".lock")):
            current=dsd_task.load_json(state_path)
            if current.get("pending_runtime_profile")==selected_profile:
                current.pop("pending_runtime_profile",None); current["updated_at"]=dsd_task.now(); dsd_task.write_json(state_path,current)
    # Launch output is a routing handoff. Runtime/workspace details are durable in the
    # attempt record and do not need to be re-injected into parent context each time.
    result={"status":"started","run_root":str(run),"phase_id":phase,"task_id":tid,"attempt":label,"role":role,"event_dir":str(event)}
    if selected_profile!="default": result["runtime_profile"]=selected_profile
    return result



def command_launch(args:argparse.Namespace)->dict[str,Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    workspace_warning=None
    # Prepare the potentially expensive Git project view/worktree outside the global launch-slot
    # lock. This keeps independent task startup from serializing on repository
    # snapshot cost. _command_launch rechecks lifecycle/dependencies under the final
    # slot lock before a worker process is actually started.
    task=dsd_task.load_task(run,phase,tid); status=str(task.get("status") or "")
    if status not in {"accepted","integrated","superseded","blocked"}:
        role=getattr(args,"role",None) or str(task.get("role") or "")
        continuing=bool(getattr(args,"resume_last",False) or getattr(args,"resume_session",None))
        validate_launch_role(task,role,continuing=continuing)
        if role not in {"reviewer","fixer","recovery"}:
            ok,missing=dsd_task.readiness(run,phase,task)
            if not ok: raise ValueError(f"task dependencies not satisfied/integrated: {missing}")
        if not dsd_workspace.workspace_path(run,phase,tid).exists():
            dsd_workspace.prepare_launch_workspace(run,phase,tid,role)
        elif role==str(task.get("role") or "") and not continuing:
            # A cold retry should not silently keep executing an obsolete engine
            # snapshot when this task has authored no project delta. Dirty/continued
            # workspaces are never refreshed automatically.
            refresh=dsd_workspace.refresh_clean_task_workspace(run,phase,tid)
            if refresh.get("reason")=="task-delta-present-primary-changed":
                workspace_warning={
                    "code":"retained-task-delta-on-stale-primary",
                    "message":"retained workspace has task delta and primary changed since its baseline; retry preserves the task delta and does not auto-rebase it",
                    "primary_change":refresh.get("primary_change"),
                    "workspace_primary_head":refresh.get("workspace_primary_head"),
                    "current_primary_head":refresh.get("current_primary_head"),
                }
    with dsd_task.file_lock(run/".launch.lock"):
        info=dsd_task.load_run(run)
        limit=int(info.get("max_workers") or 1)
        live=live_run_attempts(run)
        if len(live)>=limit:
            raise ValueError(f"worker budget exhausted: {len(live)} live / {limit} configured; launch another READY task when a slot opens")
        result=_command_launch(args)
        if workspace_warning: result["workspace_warning"]=workspace_warning
        return result

def resolve_event(run:Path,phase:str,tid:str,event_arg:Path|None)->Path:
    if event_arg: return event_arg.resolve()
    task=dsd_task.load_task(run,phase,tid)
    attempts=task.get("attempts",[])
    if not attempts: raise ValueError("task has no attempts")
    return Path(str(attempts[-1]["event_dir"])).resolve()


def _file_observation(path:Path)->dict[str,Any]:
    if not path.is_file(): return {"exists":False,"path":str(path)}
    st=path.stat()
    return {"exists":True,"path":str(path),"bytes":st.st_size,"age_seconds":max(0,round(time.time()-st.st_mtime,1))}


def _iso_epoch(value: Any) -> float | None:
    if not isinstance(value,str) or not value.strip(): return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        if parsed.tzinfo is None: parsed=parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def _completed_role_duration_reference(run:Path,phase:str,role:str,driver:str,model:str,profile:str,exclude_event:Path)->dict[str,Any]|None:
    durations=[]; tasks_dir=dsd_task.phase_root(run,phase)/"tasks"
    for state_path in tasks_dir.glob("*/task.json") if tasks_dir.is_dir() else []:
        try: task=dsd_task.load_json(state_path)
        except Exception: continue
        for attempt in task.get("attempts",[]):
            if not isinstance(attempt,dict) or attempt.get("role")!=role: continue
            if driver and model:
                if str(attempt.get("driver") or "")!=driver or str(attempt.get("model") or "")!=model: continue
                if str(attempt.get("runtime_profile") or "default")!=profile: continue
            event=Path(str(attempt.get("event_dir") or ""))
            try:
                if event.resolve()==exclude_event.resolve(): continue
            except OSError:
                pass
            terminal=event/"terminal.json"
            if not terminal.is_file(): continue
            try: data=json.loads(terminal.read_text())
            except (OSError,json.JSONDecodeError): continue
            started=_iso_epoch(data.get("started_at")); ended=_iso_epoch(data.get("ended_at"))
            if started is None or ended is None or ended<started: continue
            durations.append(ended-started)
    if not durations: return None
    durations=sorted(durations)[-40:]
    n=len(durations); mid=n//2
    median=durations[mid] if n%2 else (durations[mid-1]+durations[mid])/2
    return {"samples":n,"median_seconds":round(median,1)}


def _attempt_record_for_event(task:dict[str,Any],event:Path)->dict[str,Any]:
    target=event.resolve()
    for attempt in reversed(task.get("attempts",[])):
        if isinstance(attempt,dict) and Path(str(attempt.get("event_dir") or "")).resolve()==target:
            return attempt
    raise ValueError("attempt is not recorded for this task")


def command_retire(args:argparse.Namespace)->dict[str,Any]:
    """Request bounded termination of one exact live worker attempt.

    The launcher remains alive and owns terminal.json. New RC45 workers start in their
    own process group, so SIGTERM also reaches worker-spawned MCP/child processes. For
    older attempts without a dedicated group, fall back to signaling only worker_pid.
    """
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    task=dsd_task.load_task(run,phase,tid); event=resolve_event(run,phase,tid,args.event_dir)
    _attempt_record_for_event(task,event)  # exact durable binding proof
    class I: pass
    i=I(); i.run_root=run; i.phase_id=phase; i.task_id=tid; i.event_dir=event; i.details=True; i.skip_duration_reference=True
    observed=command_inspect(i)
    if observed.get("state")!="running":
        return {"task_id":tid,"event_dir":str(event),"retired":False,"state":observed.get("state"),"reason":"attempt-not-live"}
    detail_path=event/"attempt.json"
    if not detail_path.is_file(): raise ValueError("live attempt has no attempt.json; refusing raw process retirement")
    detail=json.loads(detail_path.read_text(encoding="utf-8"))
    worker_pid=detail.get("worker_pid"); launcher_pid=detail.get("launcher_pid")
    if not isinstance(worker_pid,int) or worker_pid<=0 or not pid_alive(worker_pid):
        raise ValueError("recorded worker_pid is not live; reconcile/sweep stale state instead")
    request={
        "format":"tbag-attempt-retirement-v1","requested_at":datetime.now(timezone.utc).isoformat(),
        "task_id":tid,"phase_id":phase,"event_dir":str(event),"reason":str(args.reason),
        "worker_pid":worker_pid,"launcher_pid":launcher_pid,"report_state":observed.get("report_state"),
        "elapsed_seconds":observed.get("elapsed_seconds"),"log_age_seconds":observed.get("log_age_seconds"),
    }
    dsd_task.write_json(event/"retirement-request.json",request)
    mode="worker-pid"
    try:
        pgid=os.getpgid(worker_pid)
    except OSError:
        pgid=None
    if pgid==worker_pid:
        os.killpg(worker_pid,signal.SIGTERM); mode="worker-process-group"
    else:
        os.kill(worker_pid,signal.SIGTERM)
    return {**request,"retired":True,"signal":"SIGTERM","mode":mode}


def command_inspect(args:argparse.Namespace)->dict[str,Any]:
    """Return a non-blocking lifecycle snapshot of a running or terminal attempt.

    This is supervision evidence only: process/report/log freshness can show liveness or
    a dead unresolved attempt, but cannot establish semantic progress or PASS.
    """
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id); event=resolve_event(run,phase,tid,args.event_dir)
    task=dsd_task.load_task(run,phase,tid); record=_attempt_record_for_event(task,event)
    terminal_path=event/"terminal.json"; detail_path=event/"attempt.json"; terminal=None; detail=None
    if terminal_path.is_file():
        try: terminal=json.loads(terminal_path.read_text())
        except json.JSONDecodeError: terminal={"status":"malformed-terminal"}
    if detail_path.is_file():
        try: detail=json.loads(detail_path.read_text())
        except json.JSONDecodeError: detail={"status":"malformed-attempt"}
    pids=sorted(dsd_task.attempt_pids(record)); pid_state={str(pid):pid_alive(pid) for pid in pids}
    live=terminal is None and any(pid_state.values())
    state="terminal" if terminal is not None else "running" if live else "dead-unresolved"
    report=event/"report.md"; log=event/"worker.log"; stderr=event/"worker.stderr.log"
    report_state="missing"
    if report.is_file():
        text=report.read_text(encoding="utf-8",errors="replace")
        marker="DSD_WORKER_REPORT_PLACEHOLDER_V2_1"
        if marker not in text: report_state="present"
        else:
            meaningful=[line.strip() for line in text.splitlines() if line.strip() and marker not in line and not line.startswith("# T-BAG worker report placeholder") and not line.startswith("Attempt:") and not line.startswith("Append running status below")]
            report_state="in-progress" if meaningful else "launcher-placeholder"
    log_obs=_file_observation(log); report_obs=_file_observation(report)
    started=_iso_epoch((detail or {}).get("started_at"))
    if started is None:
        try: started=event.stat().st_mtime
        except OSError: started=None
    elapsed=max(0,round(time.time()-started,1)) if started is not None else None
    role=str(record.get("role") or ""); driver=str(record.get("driver") or ""); model=str(record.get("model") or ""); profile=str(record.get("runtime_profile") or "default")
    duration_ref=_completed_role_duration_reference(run,phase,role,driver,model,profile,event) if live and role and not getattr(args,"skip_duration_reference",False) else None
    result={
        "task_id":tid,"event_dir":str(event),"state":state,"role":record.get("role"),"attempt_status":record.get("status"),
        "report_state":report_state,"log_bytes":log_obs.get("bytes",0),"log_age_seconds":log_obs.get("age_seconds"),
        "report_bytes":report_obs.get("bytes",0),"report_age_seconds":report_obs.get("age_seconds"),"elapsed_seconds":elapsed,
        "next_action":"gate" if terminal is not None else "running-progress-unknown" if live else "sweep-stale",
    }
    if profile!="default": result["runtime_profile"]=profile
    if live:
        result["progress_assessment"]="unknown"
        if duration_ref:
            result["runtime_duration_reference"]={**duration_ref,"runtime_profile":profile}
            result["role_duration_reference"]=duration_ref  # legacy/debug alias; omit from ordinary parent routing logic
            median=float(duration_ref.get("median_seconds") or 0)
            report_age=report_obs.get("age_seconds"); log_age=log_obs.get("age_seconds")
            anomalous=median>0 and elapsed is not None and duration_ref.get("samples",0)>=2 and elapsed>=max(1800.0,2.5*median) and isinstance(report_age,(int,float)) and report_age>=max(1800.0,median)
            if anomalous:
                if isinstance(log_age,(int,float)) and log_age<=300:
                    result["attention"]="long-running-with-stale-report-while-log-is-active"
                elif not log_obs.get("exists") or not isinstance(log_age,(int,float)) or log_age>=900:
                    result["attention"]="silent-long-running"
                if result.get("attention"):
                    result["next_action"]="consider-intervention"
        elif elapsed is not None:
            # With no history, surface only extreme silence; never diagnose cause.
            default_limit=7200.0 if dsd_task.DEFAULT_TIER.get(role)=="grunt" else 21600.0
            log_age=log_obs.get("age_seconds"); report_age=report_obs.get("age_seconds")
            if elapsed>=default_limit and (not log_obs.get("exists") or (isinstance(log_age,(int,float)) and log_age>=1800)) and isinstance(report_age,(int,float)) and report_age>=1800:
                result["attention"]="silent-long-running"; result["next_action"]="consider-intervention"
    if terminal is not None:
        result["terminal"]={"status":terminal.get("status"),"exit_code":terminal.get("exit_code")}
    if getattr(args,"details",False):
        result.update({"phase_id":phase,"pids":pid_state,"attempt_detail":_file_observation(detail_path),"report":report_obs,"log":log_obs,"stderr_log":_file_observation(stderr) if stderr.exists() else {"exists":False,"path":str(stderr)},"terminal_full":terminal,"terminal_event":str(terminal_path)})
    return result


def _gate_one(run:Path,phase:str,tid:str,event_arg:Path|None)->dict[str,Any]:
    event=resolve_event(run,phase,tid,event_arg)
    terminal=event/"terminal.json"
    if not terminal.is_file(): raise ValueError(f"attempt has no terminal event yet: {terminal}")
    gate_path=event/"evidence-gate.json"
    if gate_path.exists():
        for n in range(2,100):
            candidate=event/f"evidence-gate-{n:02d}.json"
            if not candidate.exists(): gate_path=candidate; break
    scripts=Path(__file__).resolve().parent
    run_checked([sys.executable,str(scripts/"evidence_gate.py"),"--event-dir",str(event),"--output",str(gate_path)],allowed={0,1})
    gate=json.loads(gate_path.read_text())
    terminal_data=json.loads(terminal.read_text())
    disposition=str(gate.get("disposition") or "integrity-failed")
    status="gated" if gate.get("ready_for_interpretation") else disposition
    class U: pass
    u=U(); u.run_root=run; u.phase_id=phase; u.task_id=tid; u.event_dir=event; u.status=status; u.gate=gate_path; u.session_id=terminal_data.get("session_id")
    dsd_task.command_update_attempt(u)
    errors=list(gate.get("errors") or [])
    warnings=list(gate.get("warnings") or [])
    result={"task_id":tid,"event_dir":str(event),"gate":str(gate_path),"disposition":disposition,"ready_for_interpretation":bool(gate.get("ready_for_interpretation")),"exit_code":gate.get("exit_code"),"session_id":gate.get("session_id"),"first_error":str(errors[0])[:800] if errors else None,"first_warning":str(warnings[0])[:800] if warnings else None}
    report=event/"report.md"
    if result["ready_for_interpretation"] and report.is_file():
        # The evidence gate already owns the report path. Surface only the bounded
        # routing section here so the parent does not spend a second tool call merely
        # to extract the same attempt's verdict/disposition text.
        result["report_surface"]=report_surface_helper.surface(report,max_lines=6,max_chars=1000)
        try:
            task=dsd_task.load_task(run,phase,tid); record=_attempt_record_for_event(task,event); role=str(record.get("role") or "")
            declared=dsd_task.declared_report_outcome(report,role,required=False)
            if declared: result["declared_outcome"]=declared
            elif role in dsd_task.REPORT_OUTCOMES_BY_ROLE:
                result["routing_protocol_error"]=f"{role} report lacks an exact first-line routing token"
        except (OSError,ValueError,KeyError):
            pass
    return result


def command_gate(args:argparse.Namespace)->dict[str,Any]:
    """Evidence-gate one or several completed attempts in one parent transition."""
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id)
    raw=getattr(args,"task_id",None)
    tids=[dsd_task.slug(str(x)) for x in raw] if isinstance(raw,list) else [dsd_task.slug(str(raw))]
    event_arg=getattr(args,"event_dir",None)
    if event_arg is not None and len(tids)!=1:
        raise ValueError("--event-dir is only valid when gating one --task-id")
    if len(tids)==1:
        out=_gate_one(run,phase,tids[0],event_arg)
        try: dsd_workspace.gc_analysis_views(run)
        except (OSError,ValueError): pass
        return out
    results=[]; errors=[]
    for tid in tids:
        try: results.append(_gate_one(run,phase,tid,None))
        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc: errors.append({"task_id":tid,"error":str(exc)})
    try: dsd_workspace.gc_analysis_views(run)
    except (OSError,ValueError): pass
    return {"count":len(results),"results":results,"errors":errors}




def _default_follow_timeout(role:str)->float:
    return 7200.0 if DEFAULT_TIER.get(role)=="grunt" else 21600.0


def command_follow(args:argparse.Namespace)->dict[str,Any]:
    """Observe one already-launched attempt without gating or mutating lifecycle state.

    This exists for parent harnesses that can display a background shell command as a
    native task. It deliberately watches one attempt rather than supervising a run.
    Completion/deadline of this observer is only a wake signal; the parent reconciles.
    """
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    event=resolve_event(run,phase,tid,args.event_dir)
    interval=max(1.0,float(getattr(args,"interval",15.0)))
    requested_timeout=getattr(args,"timeout",None)
    timeout=None
    started=time.monotonic()
    initial=None
    while True:
        class I: pass
        i=I(); i.run_root=run; i.phase_id=phase; i.task_id=tid; i.event_dir=event; i.skip_duration_reference=True
        out=command_inspect(i)
        elapsed=round(time.monotonic()-started,1)
        if timeout is None:
            default_timeout=_default_follow_timeout(str(out.get("role") or ""))
            timeout=max(interval,float(requested_timeout if requested_timeout is not None else default_timeout))
        if out["state"]=="terminal":
            terminal=out.get("terminal") or {}
            print(f"[t-bag] {tid}/{out.get('role')} TERMINAL status={terminal.get('status')} exit={terminal.get('exit_code')}",flush=True)
            out["follow_status"]="terminal"; out["elapsed_seconds"]=elapsed
            return out
        if out["state"]=="dead-unresolved":
            print(f"[t-bag] {tid}/{out.get('role')} DEAD-UNRESOLVED; reconcile/sweep-stale",flush=True)
            out["follow_status"]="dead-unresolved"; out["elapsed_seconds"]=elapsed
            return out
        if initial is None:
            initial={"log_bytes":out.get("log_bytes",0),"report_bytes":out.get("report_bytes",0)}
            print(f"[t-bag] {tid}/{out.get('role')} following log={initial['log_bytes']}B report={initial['report_bytes']}B",flush=True)
        if elapsed>=timeout:
            print(f"[t-bag] {tid}/{out.get('role')} FOLLOW-DEADLINE; reconcile and re-arm only if still live",flush=True)
            out["follow_status"]="deadline"; out["elapsed_seconds"]=elapsed
            return out
        time.sleep(min(interval,max(0.1,timeout-elapsed)))


def parser()->argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="command",required=True)
    p=sub.add_parser("launch"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True); p.add_argument("--role",choices=sorted(ROLE_NAMES)); p.add_argument("--tier",choices=("analyst","grunt"),help=argparse.SUPPRESS); p.add_argument("--driver"); p.add_argument("--model"); p.add_argument("--runtime-profile"); p.add_argument("--worker-rules"); p.add_argument("--db"); p.add_argument("--attempt",type=int); p.add_argument("--authority-input",dest="input",action="append",default=[]); p.add_argument("--input",dest="input",action="append",help=argparse.SUPPRESS); p.add_argument("--resume-session"); p.add_argument("--resume-last",action="store_true"); p.add_argument("--auto-flag",default="--auto")
    p=sub.add_parser("gate"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",action="append",required=True); p.add_argument("--event-dir",type=Path)
    for name in ("inspect","follow","retire"):
        p=sub.add_parser(name); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True); p.add_argument("--event-dir",type=Path)
        if name=="inspect": p.add_argument("--details",action="store_true")
        if name=="follow":
            p.add_argument("--interval",type=float,default=15.0); p.add_argument("--timeout",type=float)
        if name=="retire": p.add_argument("--reason",required=True)
    return ap


def main()->int:
    args=parser().parse_args()
    try:
        out=command_launch(args) if args.command=="launch" else command_gate(args) if args.command=="gate" else command_inspect(args) if args.command=="inspect" else command_retire(args) if args.command=="retire" else command_follow(args)
        print(json.dumps(out,sort_keys=True,separators=(",",":"))); return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"command":getattr(args,"command",None),"error":str(exc)},sort_keys=True,separators=(",",":")))
        print(f"ERROR: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
