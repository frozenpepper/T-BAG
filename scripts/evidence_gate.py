#!/usr/bin/env python3
"""Objective attempt gate for T-BAG v2.2.

The gate checks lifecycle, report presence, task/worktree identity, project movement,
and explicit write boundaries. It never parses worker prose into semantic PASS/FAIL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from _contract import allowed_source_changes, has_explicit_write_restriction, role_writes_project
from run_worker import classify_report_text


def read_json(path: Path)->dict[str,Any]:
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,dict): raise ValueError(f"expected object: {path}")
    return data


def in_prefix(path: str, prefix: str)->bool:
    p=path.replace("\\","/").strip("/"); q=prefix.replace("\\","/").strip("/")
    return p==q or p.startswith(q+"/")


def gate(event: Path)->dict[str,Any]:
    reservation_path=event/"launch-reservation.json"; terminal_path=event/"terminal.json"
    errors=[]; warnings=[]
    if not reservation_path.is_file(): raise ValueError(f"launch reservation missing: {reservation_path}")
    reservation=read_json(reservation_path)
    task=Path(str(reservation.get("task_contract") or "")); report=Path(str(reservation.get("report") or "")); baseline=Path(str(reservation.get("scope_baseline") or ""))
    for label,p in (("task contract",task),("scope baseline",baseline)):
        if not p.is_file(): errors.append(f"{label} missing: {p}")
    terminal=None; scope=None
    if terminal_path.is_file():
        terminal=read_json(terminal_path)
        for key in ("task_id","role","attempt","tier","model"):
            if terminal.get(key)!=reservation.get(key): errors.append(f"terminal {key} disagrees with launch reservation")
        scope_raw=terminal.get("scope_diff")
        if isinstance(scope_raw,str) and Path(scope_raw).is_file(): scope=read_json(Path(scope_raw))
        else: errors.append("terminal scope comparison missing")
    else:
        errors.append("terminal event missing")

    report_state="missing"
    if report.is_file():
        text=report.read_text(encoding="utf-8",errors="replace")
        report_state=classify_report_text(text)
    changed=list(scope.get("changed_since_attempt_baseline",[])) if isinstance(scope,dict) else []
    role=str(reservation.get("role") or "")
    task_text=task.read_text(encoding="utf-8",errors="replace") if task.is_file() else ""
    writes=bool(reservation.get("writes_project")) if "writes_project" in reservation else role_writes_project(role,task_text)

    forbidden_control=[p for p in changed if p=="TBag" or p.startswith("TBag/")]
    if forbidden_control:
        errors.append("worker changed TBag control/evidence tree: "+", ".join(forbidden_control[:20]))
    if not writes and changed:
        errors.append("read-only attempt changed project/worktree state: "+", ".join(changed[:20])+"; attempt artifacts belong under the launcher-supplied attempt directory/report parent, not the assigned project view. If the changed path is a cache/build artifact (for example __pycache__/*.pyc), the brief itself contains a mutating verification step; fix the verification command rather than retrying the read-only worker")
    if writes and task_text and has_explicit_write_restriction(task_text):
        allowed=allowed_source_changes(task_text)
        outside=[p for p in changed if not any(in_prefix(p,q) for q in allowed)]
        if outside: errors.append("project changes exceeded explicit Allowed source changes: "+", ".join(outside[:20]))

    if report_state in {"missing","launcher-placeholder"}:
        if writes and changed:
            disposition="mutating-report-resume"
            warnings.append("worker left admissible project movement but no substantive final report; continue the same role on the retained workspace. Resume its session when available; otherwise a fresh same-role retry may inspect and finish the retained delta before fresh Review")
        elif errors:
            disposition="integrity-failed"
        else:
            disposition="report-resume"
            warnings.append("worker left no substantive final report and no project movement; continue the same role. Resume its session when available, otherwise retry cold")
    elif errors:
        # Partial-report convenience never overrides an objective scope/read-only/
        # lifecycle failure. Integrity failures remain Recovery boundaries.
        disposition="integrity-failed"
    elif report_state=="in-progress":
        disposition="mutating-report-resume" if writes and changed else "report-resume"
        warnings.append("worker left an in-progress report; prefer same-role same-session continuation when available, otherwise retry the same role on the retained state")
    else:
        disposition="ready-for-interpretation"

    integrity_ok=not errors
    ready=integrity_ok and report_state=="present" and terminal is not None
    return {
        "format":"dsd-evidence-gate-v2.1","integrity_ok":integrity_ok,"ready_for_interpretation":ready,
        "disposition":disposition,"errors":errors,"warnings":warnings,"task_id":reservation.get("task_id"),"role":role,
        "tier":reservation.get("tier"),"model":reservation.get("model"),"event_dir":str(event),"task":str(task),"report":str(report),
        "report_state":report_state,"writes_project":writes,"scope":scope,"terminal_event":str(terminal_path) if terminal_path.is_file() else None,
        "exit_code":terminal.get("exit_code") if isinstance(terminal,dict) else None,"session_id":terminal.get("session_id") if isinstance(terminal,dict) else None,
    }


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--event-dir",type=Path,required=True); ap.add_argument("--output",type=Path)
    args=ap.parse_args()
    try:
        result=gate(args.event_dir.resolve()); rendered=json.dumps(result,indent=2,sort_keys=True)+"\n"
        if args.output:
            out=args.output.resolve(); out.parent.mkdir(parents=True,exist_ok=True)
            if out.exists(): raise ValueError(f"gate output already exists: {out}")
            out.write_text(rendered,encoding="utf-8")
        else: sys.stdout.write(rendered)
        return 0 if result["ready_for_interpretation"] else 1
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(f"evidence_gate error: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
