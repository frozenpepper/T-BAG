#!/usr/bin/env python3
from pathlib import Path

ROOT=Path.cwd()

def replace(path, old, new):
    p=ROOT/path
    text=p.read_text()
    count=text.count(old)
    if count!=1:
        raise SystemExit(f"{path}: expected exactly one patch anchor, found {count}: {old[:120]!r}")
    p.write_text(text.replace(old,new))

# Shared role registry: these Analyst roles may own an explicit lifecycle disposition.
replace("scripts/_roles.py",
'''ANALYST_ROLES = frozenset(name for name, tier in DEFAULT_TIER.items() if tier == "analyst")

TECHNICAL_QUALITY_ROLES = frozenset(set(ROLE_NAMES) - {"evidence-clerk", "context-reviewer"})
''',
'''ANALYST_ROLES = frozenset(name for name, tier in DEFAULT_TIER.items() if tier == "analyst")
ANALYST_DISPOSITION_ROLES = frozenset({"planner", "discovery", "phase-surveyor", "recovery"})

TECHNICAL_QUALITY_ROLES = frozenset(set(ROLE_NAMES) - {"evidence-clerk", "context-reviewer"})
''')

# Every disposition-owning Analyst gets the tiny routing guide, not only escalations.
replace("scripts/render_worker_prompt.py",
'''from _roles import ANALYST_ROLES, ROLE_SKILLS, TECHNICAL_QUALITY_ROLES
''',
'''from _roles import ANALYST_DISPOSITION_ROLES, ANALYST_ROLES, ROLE_SKILLS, TECHNICAL_QUALITY_ROLES
''')
replace("scripts/render_worker_prompt.py",
'''    # COMMON defines generic ESCALATE. The extra adjudication guidance is only
    # useful when an Analyst is actually receiving a lower-tier escalation.
    analyst_escalation = protocol / "ANALYST-ESCALATION.md" if args.role in ANALYST_ROLES and args.escalation_context else None
''',
'''    # Planner/Discovery/Surveyor/Recovery may own a lifecycle disposition even
    # without a lower-tier escalation packet. Keep that tiny protocol shared.
    analyst_escalation = protocol / "ANALYST-ESCALATION.md" if args.role in ANALYST_DISPOSITION_ROLES else None
''')

# The task control plane recognizes the same Analyst dispositions that workers are taught.
replace("scripts/dsd_task.py",
'''from _roles import DEFAULT_TIER, ESCALATION_LADDER, ROLE_NAMES
''',
'''from _roles import ANALYST_DISPOSITION_ROLES, DEFAULT_TIER, ESCALATION_LADDER, ROLE_NAMES
''')
replace("scripts/dsd_task.py",
'''    "phase-auditor": {"PASS": "pass", "BLOCKED": "blocked", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
}
''',
'''    "phase-auditor": {"PASS": "pass", "BLOCKED": "blocked", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
    "planner": {"RESUME": "resume", "REPLAN": "replan", "REPLAN+RESUME": "replan-resume", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
    "discovery": {"RESUME": "resume", "REPLAN": "replan", "REPLAN+RESUME": "replan-resume", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
    "phase-surveyor": {"RESUME": "resume", "REPLAN": "replan", "REPLAN+RESUME": "replan-resume", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
    "recovery": {"RESUME": "resume", "REPLAN": "replan", "REPLAN+RESUME": "replan-resume", "ESCALATE": "escalate", "ESCALATE CAPABILITY": "capability"},
}
''')

replace("scripts/dsd_task.py",
'''def report_requests_capability(report: Path) -> bool:
    if not report.is_file(): return False
    for raw in report.read_text(encoding="utf-8",errors="replace").splitlines():
        if raw.strip(): return raw.strip()=="ESCALATE CAPABILITY"
    return False
''',
'''def report_requests_capability(report: Path) -> bool:
    """Recognize the explicit capability token through the same Markdown envelope as other routing."""
    if not report.is_file(): return False
    allowed={"ESCALATE CAPABILITY":"capability"}
    nonempty=[raw.strip() for raw in report.read_text(encoding="utf-8",errors="replace").splitlines() if raw.strip()]
    if not nonempty: return False
    index=0; skipped=0
    while index < len(nonempty) and skipped < 2 and _decorative_routing_heading(nonempty[index],allowed):
        index+=1; skipped+=1
    return bool(index < len(nonempty) and _routing_line_outcome(nonempty[index],allowed)=="capability")
''')

# Manual Review commands derive the worker's token; --outcome is a legacy fallback only.
replace("scripts/dsd_task.py",
'''def command_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); report=args.report.resolve()
        if not report.is_file(): raise ValueError(f"review report missing: {report}")
        declared=declared_report_outcome(report,"reviewer",required=False)
        if declared=="capability": raise ValueError("Reviewer requested ESCALATE CAPABILITY; route capability escalation instead of recording a Review verdict")
        if declared is not None and declared!=outcome: raise ValueError(f"Reviewer declared {declared!r} but --outcome was {outcome!r}; do not make the parent reinterpret the report")
''',
'''def command_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        task=load_json(path); report=args.report.resolve()
        if not report.is_file(): raise ValueError(f"review report missing: {report}")
        declared=declared_report_outcome(report,"reviewer",required=False); fallback=getattr(args,"outcome",None)
        if declared=="capability": raise ValueError("Reviewer requested ESCALATE CAPABILITY; route capability escalation instead of recording a Review verdict")
        if declared is None:
            if fallback is None: raise ValueError("Reviewer report has no explicit routing token; only legacy/tokenless reports require --outcome")
            outcome=fallback
        else:
            if fallback is not None and declared!=fallback: raise ValueError(f"Reviewer declared {declared!r} but --outcome was {fallback!r}; do not make the parent reinterpret the report")
            outcome=declared
        if outcome not in {"pass","fail","escalate"}: raise ValueError(f"unsupported Reviewer outcome: {outcome!r}")
''')

replace("scripts/dsd_task.py",
'''def command_plan_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve()
        declared=declared_report_outcome(report,"plan-reviewer",required=False)
        if declared=="capability": raise ValueError("Plan Reviewer requested ESCALATE CAPABILITY; route capability escalation instead")
        if declared is not None and declared!=outcome: raise ValueError(f"Plan Reviewer declared {declared!r} but --outcome was {outcome!r}")
''',
'''def command_plan_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve(); declared=declared_report_outcome(report,"plan-reviewer",required=False); fallback=getattr(args,"outcome",None)
        if declared=="capability": raise ValueError("Plan Reviewer requested ESCALATE CAPABILITY; route capability escalation instead")
        if declared is None:
            if fallback is None: raise ValueError("Plan Reviewer report has no explicit routing token; only legacy/tokenless reports require --outcome")
            outcome=fallback
        else:
            if fallback is not None and declared!=fallback: raise ValueError(f"Plan Reviewer declared {declared!r} but --outcome was {fallback!r}")
            outcome=declared
        if outcome not in {"pass","fail","escalate"}: raise ValueError(f"unsupported Plan Reviewer outcome: {outcome!r}")
''')

replace("scripts/dsd_task.py",
'''def command_context_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid); outcome=args.outcome
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve()
        declared=declared_report_outcome(report,"context-reviewer",required=False)
        if declared=="capability": raise ValueError("Context Reviewer requested ESCALATE CAPABILITY; route capability escalation instead")
        if declared is not None and declared!=outcome: raise ValueError(f"Context Reviewer declared {declared!r} but --outcome was {outcome!r}")
''',
'''def command_context_review(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=slug(args.phase_id); tid=slug(args.task_id); path=task_file(run,phase,tid)
    with file_lock(path.with_suffix(".lock")):
        report=args.report.resolve(); declared=declared_report_outcome(report,"context-reviewer",required=False); fallback=getattr(args,"outcome",None)
        if declared=="capability": raise ValueError("Context Reviewer requested ESCALATE CAPABILITY; route capability escalation instead")
        if declared is None:
            if fallback is None: raise ValueError("Context Reviewer report has no explicit routing token; only legacy/tokenless reports require --outcome")
            outcome=fallback
        else:
            if fallback is not None and declared!=fallback: raise ValueError(f"Context Reviewer declared {declared!r} but --outcome was {fallback!r}")
            outcome=declared
        if outcome not in {"pass","fail","escalate"}: raise ValueError(f"unsupported Context Reviewer outcome: {outcome!r}")
''')

# Analyst disposition is also worker-owned. Explicit flags remain for old tokenless reports.
replace("scripts/dsd_task.py",
'''        attempt=matching_gated_attempt(task,{"discovery","planner","phase-surveyor","recovery"},report)
        if attempt is None or attempt_tier(attempt)!="analyst": raise ValueError("analysis result must refer to a gated Analyst attempt for this task")
        require_current_attempt(task,attempt,reason="analysis result")
        outcome=args.outcome; task["last_analysis"]={"outcome":outcome,"report":str(report),"attempt":str(attempt.get("event_dir")),"recorded_at":now()}
''',
'''        attempt=matching_gated_attempt(task,set(ANALYST_DISPOSITION_ROLES),report)
        if attempt is None or attempt_tier(attempt)!="analyst": raise ValueError("analysis result must refer to a gated disposition-owning Analyst attempt for this task")
        require_current_attempt(task,attempt,reason="analysis result")
        role=str(attempt.get("role") or ""); declared=declared_report_outcome(report,role,required=False); fallback=getattr(args,"outcome",None)
        if declared=="capability": raise ValueError(f"{role} requested ESCALATE CAPABILITY; route capability escalation instead of recording an Analyst disposition")
        if declared is None:
            if fallback is None: raise ValueError("Analyst report has no explicit lifecycle disposition; standalone findings use accept --report, while legacy/tokenless lifecycle reports require --outcome")
            outcome=fallback
        else:
            if fallback is not None and declared!=fallback: raise ValueError(f"Analyst declared {declared!r} but --outcome was {fallback!r}; do not make the parent reinterpret the report")
            outcome=declared
        if outcome not in {"resume","replan","replan-resume","escalate"}: raise ValueError(f"unsupported Analyst disposition: {outcome!r}")
        task["last_analysis"]={"outcome":outcome,"report":str(report),"attempt":str(attempt.get("event_dir")),"recorded_at":now()}
''')

# Follow-up triage briefs speak the worker protocol rather than telling the worker a parent CLI flag.
replace("scripts/dsd_task.py",
'''                "- If the current frozen plan already genuinely covers every obligation, explain why and use `analysis-result --outcome resume`.",
                "- If any brief/task/dependency must change, emit a replacement/amending task graph and use `analysis-result --outcome replan`. T-BAG already knows which findings this triage owns; do not repeat IDs as graph ceremony.",
''',
'''                "- If the current frozen plan already genuinely covers every obligation, explain why and open the report with `RESUME`.",
                "- If any brief/task/dependency must change, emit a replacement/amending task graph and open the report with `REPLAN`. T-BAG already knows which findings this triage owns; do not repeat IDs as graph ceremony.",
''')

# Reconciliation routes explicit Analyst dispositions and mechanically-created triage through one path.
replace("scripts/dsd_task.py",
'''        if task.get("kind")=="verification" and role in BASE_ROLES_BY_KIND["verification"]:
            return {**base,"action":"record-verification-result","report":str(event/"report.md")}
        if role in {"discovery","planner","phase-surveyor","recovery"} and task.get("kind") in {"implementation","verification"}:
            return {**base,"action":"record-analyst-disposition","report":str(event/"report.md")}
        if task.get("kind") in {"analysis","verification"}: return {**base,"action":"accept-specialist-result","report":str(event/"report.md")}
''',
'''        if task.get("kind")=="verification" and role in BASE_ROLES_BY_KIND["verification"]:
            return {**base,"action":"record-verification-result","report":str(event/"report.md")}
        if role in ANALYST_DISPOSITION_ROLES:
            declared=declared_report_outcome(event/"report.md",role,required=False)
            if task.get("followup_triage_for") or task.get("kind") in {"implementation","verification"} or declared in {"resume","replan","replan-resume","escalate"}:
                return {**base,"action":"record-analyst-disposition","report":str(event/"report.md")}
        if task.get("kind") in {"analysis","verification"}: return {**base,"action":"accept-specialist-result","report":str(event/"report.md")}
''')

# Advance can now record the Analyst's own disposition rather than stopping for parent interpretation.
replace("scripts/dsd_task.py",
'''            elif name=="record-phase-gate":
                class A: pass
                a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.report=Path(str(action["report"]))
                result=command_phase_gate(a)
            elif name=="accept-reviewed-task":
''',
'''            elif name=="record-phase-gate":
                class A: pass
                a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.report=Path(str(action["report"]))
                result=command_phase_gate(a)
            elif name=="record-analyst-disposition":
                class A: pass
                a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.report=Path(str(action["report"])); a.outcome=None
                result=command_analysis_result(a)
            elif name=="accept-reviewed-task":
''')

# The CLI mirrors the normal automatic path: outcome flags are compatibility fallbacks.
replace("scripts/dsd_task.py",
'''        elif name=="review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="plan-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="context-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
        elif name=="verification-result": p.add_argument("--report",type=Path,required=True)
        elif name=="analysis-result": p.add_argument("--outcome",choices=("resume","replan","replan-resume","escalate"),required=True); p.add_argument("--report",type=Path,required=True)
''',
'''        elif name=="review": p.add_argument("--outcome",choices=("pass","fail","escalate"),help="legacy/tokenless report fallback; a routing token in the report is authoritative"); p.add_argument("--report",type=Path,required=True)
        elif name=="plan-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),help="legacy/tokenless report fallback; a routing token in the report is authoritative"); p.add_argument("--report",type=Path,required=True)
        elif name=="context-review": p.add_argument("--outcome",choices=("pass","fail","escalate"),help="legacy/tokenless report fallback; a routing token in the report is authoritative"); p.add_argument("--report",type=Path,required=True)
        elif name=="verification-result": p.add_argument("--report",type=Path,required=True)
        elif name=="analysis-result": p.add_argument("--outcome",choices=("resume","replan","replan-resume","escalate"),help="legacy/tokenless report fallback; Analyst disposition token is authoritative"); p.add_argument("--report",type=Path,required=True)
''')

# Error/help prose must describe the same report-owned contract.
replace("scripts/dsd_task.py",
'''        raise ValueError("Analyst task graph is mechanically gated but has not been approved: accept the Analyst result, or record analysis-result --outcome replan/replan-resume for a replacement plan")
''',
'''        raise ValueError("Analyst task graph is mechanically gated but has not been approved: accept standalone findings, or record the Analyst report's REPLAN/REPLAN+RESUME disposition before registering its replacement plan")
''')
replace("scripts/dsd_task.py",
'''                "Analyst specialists use analysis-result --outcome escalate; Reviewer/Plan-Reviewer/Context-Reviewer "
''',
'''                "Analyst specialists use their ESCALATE report through analysis-result; Reviewer/Plan-Reviewer/Context-Reviewer "
''')

# Reusable-context adoption error wording follows the same contract.
replace("scripts/prepare_worker_rules.py",
'''                raise ValueError("Analyst context is mechanically gated but has not been approved: accept the Analyst result, or record analysis-result --outcome resume/replan/replan-resume for same-task diagnosis")
''',
'''                raise ValueError("Analyst context is mechanically gated but has not been approved: accept standalone findings, or record the Analyst report's RESUME/REPLAN/REPLAN+RESUME disposition for same-task diagnosis")
''')

print("RC49_PATCH_APPLIED")
