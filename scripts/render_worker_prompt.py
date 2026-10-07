#!/usr/bin/env python3
"""Render one compact path-based T-BAG worker handoff."""
from __future__ import annotations

import argparse
from pathlib import Path

from _contract import worker_skill_tags
from _roles import ANALYST_DISPOSITION_ROLES, ANALYST_ROLES, ROLE_SKILLS, TECHNICAL_QUALITY_ROLES
from _rules_snapshot import verify_snapshot
from dsd_task import REPORT_OUTCOMES_BY_ROLE

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
    ap.add_argument("--continuation", action="store_true", help="resume an existing worker conversation without forcing stable-context rereads")
    ap.add_argument("--report-only-continuation", action="store_true", help="finish interrupted reporting/evidence only; project mutation is forbidden")
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
    # Planner/Discovery/Surveyor/Recovery may own a lifecycle disposition even
    # without a lower-tier escalation packet. Keep that tiny protocol shared.
    analyst_escalation = protocol / "ANALYST-ESCALATION.md" if args.role in ANALYST_DISPOSITION_ROLES else None
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

    stable = [rules, common] + ([quality] if quality else []) + ([analyst_escalation] if analyst_escalation else []) + ([plan_authoring] if plan_authoring else []) + ([skill_catalog] if skill_catalog else []) + ([project_protocol] if project_protocol else [])
    if args.report_only_continuation:
        reads=[task,role_skill]+task_skills
        fallback=[p for p in stable if p not in reads]
        orientation="REPORT-ONLY CONTINUATION: prior project work is already frozen and this attempt has no source-write authority. Read the current task/role plus supplied prior terminal/gate/report evidence, account for changed instructions if any, and finish the self-contained report. Do not edit project files, redo implementation setup, or rerun expensive verification merely to recreate evidence already supplied."
    elif args.continuation:
        # The recorded CLI session already received immutable run/common/quality context.
        # Reassert the current task/role and any role-selected skills, but keep stable
        # contracts as explicit fallbacks if compaction made an exact rule unavailable.
        reads=[task,role_skill]+task_skills
        fallback=[p for p in stable if p not in reads]
        orientation="This is a resumed worker conversation. Read the current task and role material below; do not reread unchanged stable contracts unless compaction/context loss makes an exact rule unavailable."
    elif args.role=="reviewer":
        # Anchor fresh acceptance review on its frozen predicate before worker claims.
        reads=[task,role_skill]+stable+task_skills
        fallback=[]
        orientation="REVIEWER PRIORITY: read the frozen task brief first as the acceptance authority, then the Reviewer role/method contracts, then typed evidence. Do not let prior worker claims define the predicate."
    else:
        reads=stable+[role_skill]+task_skills+[task]
        fallback=[]
        orientation="Read the supplied contracts in order. COMMON defines universal boundaries; QUALITY (when supplied) defines the shared technical method; the role skill defines your mandate; the task brief defines this job."
    reads=list(dict.fromkeys(reads))
    fallback=list(dict.fromkeys(fallback))
    attempt_dir=report.parent
    lines = [
        f"T-BAG {args.role.upper().replace('-', ' ')} for task {args.task_id}.",
        orientation,
    ]
    if args.project_root:
        project_root=args.project_root.resolve()
        if not project_root.is_dir(): raise SystemExit(f"ERROR: assigned project view missing: {project_root}")
        lines += [f"Assigned project view: {project_root}", "Project reads/tools must target only that assigned view; it may differ from the process cwd used to protect read-only tasks."]
    if args.role in {"implementer","fixer","reviewer"}:
        lines += [
            "CURRENT-CODE PREMISE CHECK:",
            "- Before editing (Implementer/Fixer) or judging (Reviewer), verify in the assigned project view: the actual production owner(s), current existing behavior, the behavior genuinely still missing relative to the frozen brief, and the acceptance predicates that distinguish success.",
            "- If the brief's premise is stale because the production behavior already exists, do not recreate or relocate it merely to match the brief. Narrow to genuinely missing in-authority work such as regression/proof when that still satisfies the frozen acceptance; otherwise preserve the mismatch and escalate/replan.",
            "- Record the materially relevant premise correction in the report so later repair/review turns do not repeat the stale theory.",
        ]
    lines += ["Read now, in order:"]
    lines += [f"{i}. {p}" for i, p in enumerate(reads, 1)]
    if fallback:
        lines += ["Stable fallback references — already supplied in this resumed session; reread only if exact context was lost:", *[f"- {p}" for p in fallback]]
    for label, paths in groups:
        lines += [f"{label}:", *[f"- {p}" for p in paths]]
    lines += [f"Attempt directory: {attempt_dir}", "All attempt-output paths below are relative to that directory, never the project cwd/view.", f"Scratch/temp directory: {attempt_dir/'scratch'} (TMPDIR/TMP/TEMP point here). Never place T-BAG evidence or work products in system /tmp or outside the project-owned run tree."]
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
    routing=REPORT_OUTCOMES_BY_ROLE.get(args.role)
    if routing:
        tokens=" | ".join(routing)
        lines += [
            "MACHINE-CRITICAL REPORT ROUTING:",
            f"- The report file MUST begin with exactly one of these tokens on its first non-empty line: {tokens}",
            "- Nothing may precede that token: no Markdown heading, label, preface, code fence, or commentary.",
            "- This line is parsed mechanically. A missing/moved token turns an otherwise useful report into a routing-protocol error.",
        ]
    lines += ["LIFECYCLE NOTE: report text is evidence, not a stop signal. Complete all assigned work/tooling before finalizing the report; writing a status/verdict does not end the attempt.", f"Report: {report}", "Final stdout: report path plus at most one short conclusion."]
    rendered = "\n".join(lines) + "\n"
    if args.output:
        out = args.output.resolve()
        if out.exists(): raise SystemExit(f"ERROR: launch prompt already exists: {out}")
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(rendered, encoding="utf-8")
    else: print(rendered, end="")
    return 0

if __name__ == "__main__": raise SystemExit(main())
