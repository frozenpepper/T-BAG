#!/usr/bin/env python3
"""Render one compact path-based T-BAG worker handoff."""
from __future__ import annotations

import argparse
from pathlib import Path

from _contract import worker_skill_tags
from _roles import ANALYST_ROLES, ROLE_SKILLS, TECHNICAL_QUALITY_ROLES
from _rules_snapshot import verify_snapshot

INPUT_FLAGS = {
    "authority_input": "Governing authority inputs",
    "owner_decision": "Owner decisions",
    "analyst_finding": "Accepted Analyst findings",
    "dependency_finding": "Accepted dependency findings",
    "escalation_context": "Current escalation packet",
    "decision_context": "Legacy decision-boundary evidence",
    "review_finding": "Current Review findings",
    "worker_report": "Prior worker report / claims",
    "recovery_evidence": "Recovery evidence",
    "proposal_input": "Proposal under review",
    "input": "Explicit task inputs",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--role", choices=sorted(ROLE_SKILLS), required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--phase-id")
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--worker-rules", type=Path, required=True)
    ap.add_argument("--task", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--project-root", type=Path)
    for flag in INPUT_FLAGS:
        ap.add_argument("--" + flag.replace("_", "-"), action="append", default=[])
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()

    run = args.run_root.resolve(); rules = args.worker_rules.resolve(); task = args.task.resolve(); report = args.report.resolve()
    for name, raw in (("run-root", args.run_root), ("worker-rules", args.worker_rules), ("task", args.task), ("report", args.report)):
        if not raw.is_absolute(): raise SystemExit(f"ERROR: --{name} must be absolute: {raw}")
    snapshot = verify_snapshot(rules)
    protocol = Path(snapshot["protocol_dir"])
    common = protocol / "COMMON.md"; role_skill = protocol / ROLE_SKILLS[args.role]
    quality_candidate = protocol / "QUALITY.md"
    quality = quality_candidate if args.role in TECHNICAL_QUALITY_ROLES and quality_candidate.is_file() else None
    graph_author = args.role in {"planner", "discovery", "phase-surveyor", "recovery"}
    plan_authoring = protocol / "PLAN-AUTHORING.md" if graph_author else None
    # COMMON defines generic ESCALATE. The extra adjudication guidance is only
    # useful when an Analyst is actually receiving a lower-tier escalation.
    analyst_escalation = protocol / "ANALYST-ESCALATION.md" if args.role in ANALYST_ROLES and args.escalation_context else None
    catalog_role = args.role in {"goal-planner", "plan-reviewer", "context-reviewer", "planner", "discovery", "phase-surveyor", "recovery"}
    skill_catalog = Path(snapshot["worker_skill_catalog"]) if catalog_role else None
    project_protocol = Path(snapshot["project_protocol"]) if snapshot.get("project_protocol") else None
    task_text = task.read_text(encoding="utf-8", errors="replace")
    requested_skills = worker_skill_tags(task_text, args.role)
    catalog = snapshot.get("worker_skills", {})
    missing_skill_ids = [name for name in requested_skills if name not in catalog]
    if missing_skill_ids:
        raise SystemExit("ERROR: task requests worker skill(s) absent from this worker-rules revision: " + ", ".join(missing_skill_ids))
    task_skills = [Path(catalog[name]) for name in requested_skills]
    required = [rules, common, role_skill, task] + ([quality] if quality else []) + ([analyst_escalation] if analyst_escalation else []) + ([plan_authoring] if plan_authoring else []) + ([skill_catalog] if skill_catalog else []) + ([project_protocol] if project_protocol else []) + task_skills
    missing = [p for p in required if not p.is_file()]
    if missing: raise SystemExit("ERROR: missing launch authority: " + ", ".join(map(str, missing)))
    try: report.relative_to(run)
    except ValueError: raise SystemExit(f"ERROR: report path must live under run root: {report}")

    groups: list[tuple[str, list[Path]]] = []
    for attr, label in INPUT_FLAGS.items():
        paths = [Path(x).resolve() for x in getattr(args, attr)]
        for p in paths:
            if not p.exists(): raise SystemExit(f"ERROR: input missing: {p}")
        if paths: groups.append((label, list(dict.fromkeys(paths))))

    reads = [rules, common] + ([quality] if quality else []) + [role_skill] + ([analyst_escalation] if analyst_escalation else []) + ([plan_authoring] if plan_authoring else []) + ([skill_catalog] if skill_catalog else []) + ([project_protocol] if project_protocol else []) + task_skills + [task]
    attempt_dir=report.parent
    lines = [
        f"T-BAG {args.role.upper().replace('-', ' ')} for task {args.task_id}.",
        "Read the supplied contracts in order. COMMON defines universal boundaries; QUALITY (when supplied) defines the shared technical method; the role skill defines your mandate; the task brief defines this job.",
    ]
    if args.project_root:
        project_root=args.project_root.resolve()
        if not project_root.is_dir(): raise SystemExit(f"ERROR: assigned project view missing: {project_root}")
        lines += [f"Assigned project view: {project_root}", "Project reads/tools must target only that assigned view; it may differ from the process cwd used to protect read-only tasks."]
    lines += ["Read, in order:"]
    lines += [f"{i}. {p}" for i, p in enumerate(reads, 1)]
    for label, paths in groups:
        lines += [f"{label}:", *[f"- {p}" for p in paths]]
    lines += [f"Attempt directory: {attempt_dir}", "All attempt-output paths below are relative to that directory, never the project cwd/view."]
    if args.role == "goal-planner":
        lines += [
            "Attempt outputs allowed beside the report:",
            "- `plan/PLAN.md` (required proposal)",
            "- optional `project-protocol/PROJECT-PROTOCOL.md` and project-specific `worker-skills/<id>/SKILL.md` proposals",
        ]
    elif args.role in {"planner", "discovery", "phase-surveyor", "recovery"}:
        preflight=(Path(__file__).resolve().parent/"dsd_task.py")
        lines += [
            "Attempt outputs allowed beside the report:",
            "- `plan/task-graph.json` and `plan/tasks/<task-id>.md` when decomposing/replanning",
            "- optional `project-protocol/PROJECT-PROTOCOL.md` and project-specific `worker-skills/<id>/SKILL.md` proposals",
        ]
        if args.phase_id:
            lines += [
                "Before finalizing any emitted task graph, mechanically self-check it and revise until PASS; never leave mechanical brief repair to the parent:",
                f"python3 {preflight} preflight-plan --run-root {run} --phase-id {args.phase_id} --plan {attempt_dir/'plan'/'task-graph.json'}",
            ]
    lines += [f"Report: {report}", "Final stdout: report path plus at most one short conclusion."]
    rendered = "\n".join(lines) + "\n"
    if args.output:
        out = args.output.resolve()
        if out.exists(): raise SystemExit(f"ERROR: launch prompt already exists: {out}")
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(rendered, encoding="utf-8")
    else: print(rendered, end="")
    return 0

if __name__ == "__main__": raise SystemExit(main())
