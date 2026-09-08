#!/usr/bin/env python3
"""Create one numbered run-level worker-rules revision without checksum coupling."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import re
from datetime import datetime, timezone
from pathlib import Path

from _roles import ROLE_SKILLS
import dsd_task
from _rules_snapshot import MANIFEST_FORMAT, rules_revisions, verify_snapshot

PROTOCOL_FILES = {
    "COMMON.md": "worker/COMMON.md",
    "QUALITY.md": "worker/QUALITY.md",
    "PLAN-AUTHORING.md": "worker/PLAN-AUTHORING.md",
    "ANALYST-ESCALATION.md": "worker/ANALYST-ESCALATION.md",
    **{path: f"worker/{path}" for path in ROLE_SKILLS.values()},
}


def skill_dir(source: Path) -> Path:
    source = source.resolve()
    if source.is_file() and source.name == "SKILL.md":
        root = source.parent
    elif source.is_dir() and (source / "SKILL.md").is_file():
        root = source
    else:
        raise ValueError(f"worker skill source must be a skill directory or SKILL.md: {source}")
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise ValueError(f"worker skill source must not contain symlinks: {entry}")
        if not entry.is_dir() and not entry.is_file():
            raise ValueError(f"worker skill source contains unsupported filesystem entry: {entry}")
    return root


def skill_description(root: Path, skill_id: str) -> str:
    text = (root / "SKILL.md").read_text(encoding="utf-8", errors="replace")
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            front = text[4:end].splitlines()
            for line in front:
                if line.lower().startswith("description:"):
                    value = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return " ".join(value.split())
    for line in text.splitlines():
        if line.startswith("# ") and line[2:].strip():
            return line[2:].strip()
    return f"Reusable worker skill {skill_id}."


def validate_internal_goal_plan(run: Path, plan: Path) -> None:
    """Require reviewed/accepted provenance for a Goal-Planner plan produced inside this run.

    User/external authoritative plans remain valid direct inputs. This gate only
    prevents an internally generated bootstrap draft from becoming authority before
    the fresh Plan Reviewer passed that exact Goal-Planner attempt and exact content.
    """
    run_lex = Path(os.path.abspath(str(run.expanduser())))
    plan_lex = Path(os.path.abspath(str(plan.expanduser())))
    try:
        rel = plan_lex.relative_to(run_lex)
    except ValueError:
        return
    parts = rel.parts
    if not (len(parts)==8 and parts[0]=="phases" and parts[1]=="bootstrap" and parts[2]=="tasks" and parts[4]=="attempts" and parts[6]=="plan" and parts[7]=="PLAN.md"):
        raise ValueError("an internally generated authoritative plan must be a reviewed bootstrap Goal-Planner PLAN.md")
    cursor=run_lex
    for part in parts:
        cursor=cursor/part
        if cursor.is_symlink():
            raise ValueError("internal Goal-Planner PLAN.md and its run-relative path must not use symlinks")
    if not plan_lex.is_file():
        raise ValueError(f"internal Goal-Planner plan missing: {plan_lex}")
    task_path = run_lex / "phases" / "bootstrap" / "tasks" / parts[3] / "task.json"
    if not task_path.is_file(): raise ValueError("cannot verify internal Goal-Planner task state for --plan")
    task = json.loads(task_path.read_text(encoding="utf-8"))
    event = run_lex / Path(*parts[:6])
    report = event / "report.md"
    if task.get("role")!="goal-planner" or task.get("status") not in {"accepted","integrated"}:
        raise ValueError("internal Goal-Planner plan must be accepted after Plan-Reviewer PASS before becoming authority")
    if str(task.get("accepted_report") or "") != str(report.resolve()):
        raise ValueError("accepted Goal-Planner report does not match the plan-producing attempt")
    review = task.get("last_plan_review") if isinstance(task.get("last_plan_review"),dict) else {}
    review_report=Path(str(review.get("report") or ""))
    review_snapshot=Path(str(review.get("plan_snapshot") or ""))
    if review.get("outcome")!="pass" or Path(str(review.get("planner_attempt") or "")).resolve()!=event.resolve() or Path(str(review.get("plan") or "")).resolve()!=plan_lex.resolve() or not review_report.is_file():
        raise ValueError("internal Goal-Planner plan lacks a fresh PASS report bound to this exact planner attempt/PLAN.md")
    if review_snapshot.is_symlink() or review_snapshot.parent.is_symlink() or not review_snapshot.is_file():
        raise ValueError("internal Goal-Planner plan lacks a regular frozen PLAN.md copy reviewed by the fresh Plan Reviewer")
    try:
        if plan_lex.samefile(review_snapshot):
            raise ValueError("reviewed PLAN.md must be an independent copy, not the live plan/hardlink")
    except FileNotFoundError:
        raise ValueError("reviewed PLAN.md snapshot is missing")
    try:
        review_snapshot.resolve().relative_to(run_lex.resolve())
    except ValueError as exc:
        raise ValueError("reviewed PLAN.md snapshot must remain inside this run") from exc
    if plan_lex.read_bytes()!=review_snapshot.read_bytes():
        raise ValueError("internal Goal-Planner plan changed after the fresh Plan Reviewer PASS; review it again before promotion")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project-root", type=Path, required=True)
    ap.add_argument("--run-root", type=Path, required=True)
    ap.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--plan", type=Path, help="authoritative plan; omit on an initial goal-only bootstrap revision")
    ap.add_argument("--revision", type=int, default=1)
    ap.add_argument("--project-instruction", action="append", default=[])
    ap.add_argument("--project-protocol", type=Path)
    ap.add_argument("--clear-project-protocol", action="store_true")
    ap.add_argument("--worker-skill", action="append", default=[], metavar="ID=SKILL_DIR|SKILL.md")
    ap.add_argument("--adopt-context-from", type=Path, help="mechanically adopt project-protocol/ and worker-skills/ from an approved Analyst attempt directory")
    ap.add_argument("--drop-worker-skill", action="append", default=[], metavar="ID")
    ap.add_argument("--fresh-context", action="store_true", help="do not inherit prior revision project instructions/protocol/custom skill catalog")
    ap.add_argument("--rule", action="append", default=[])
    ap.add_argument("--clear-run-rules", action="store_true", help="remove inherited run-specific rules in this revision")
    ap.add_argument("--reuse-existing", action="store_true")
    args = ap.parse_args()
    try:
        project = args.project_root.resolve(); run = args.run_root.resolve(); skill = args.skill_root.resolve()
        if args.plan is not None: validate_internal_goal_plan(run, args.plan)
        plan = args.plan.resolve() if args.plan else None
        if args.revision < 1: raise ValueError("--revision must be >= 1")
        for name in ("project-root", "run-root"):
            if not Path(getattr(args, name.replace("-", "_"))).is_absolute():
                raise ValueError(f"--{name} must be absolute")
        if args.plan is not None and not args.plan.is_absolute():
            raise ValueError("--plan must be absolute")
        if not project.is_dir(): raise ValueError(f"project root missing: {project}")
        if not run.is_dir(): raise ValueError(f"run root missing: {run}")
        if plan is not None and not plan.is_file(): raise ValueError(f"authoritative plan must be a file: {plan}")
        try: run.relative_to(project / "TBag")
        except ValueError as exc: raise ValueError("run root must live below PROJECT/TBag") from exc
        root = run / "worker-rules" / f"r{args.revision:04d}"
        rules = root / "WORKER_RULES.md"
        if root.exists():
            if not args.reuse_existing: raise ValueError(f"rules revision already exists: {root}; create the next revision")
            print(json.dumps(verify_snapshot(rules), indent=2, sort_keys=True)); return 0
        prior = None
        previous = None
        completed = rules_revisions(run)
        later = [x for x in completed if int(x.parent.name[1:]) > args.revision]
        if later:
            raise ValueError(f"cannot create worker-rules revision r{args.revision:04d} after later completed revisions already exist")
        candidates = [x for x in completed if int(x.parent.name[1:]) < args.revision]
        if candidates:
            previous = verify_snapshot(candidates[-1])
            if not args.fresh_context:
                prior = previous
        if plan is None and previous and previous.get("authority_plan"):
            plan = Path(str(previous["authority_plan"])).resolve()
        tmp = root.with_name(root.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        protocol = tmp / "protocol"; protocol.mkdir(parents=True)
        for dest, source_rel in PROTOCOL_FILES.items():
            source = skill / source_rel
            if not source.is_file(): raise ValueError(f"protocol source missing: {source}")
            target = protocol / dest; target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
        if args.project_instruction:
            instructions = [Path(x).resolve() for x in args.project_instruction]
        elif prior:
            prior_plan = str(prior.get("authority_plan") or "")
            instructions = [Path(str(x)).resolve() for x in prior.get("authority_files", []) if str(x) != prior_plan]
        else:
            instructions = []
        missing = [p for p in instructions if not p.is_file()]
        if missing: raise ValueError("project instruction missing: " + ", ".join(map(str, missing)))

        if args.rule and args.clear_run_rules:
            raise ValueError("use either --rule or --clear-run-rules, not both")
        if args.rule:
            run_rules = list(dict.fromkeys(str(x).strip() for x in args.rule if str(x).strip()))
        elif args.clear_run_rules:
            run_rules = []
        elif prior:
            run_rules = [str(x) for x in prior.get("run_rules", []) if isinstance(x, str) and x.strip()]
        else:
            run_rules = []

        adopt_from = args.adopt_context_from.resolve() if args.adopt_context_from else None
        adopted_protocol = None
        adopted_skills: dict[str, Path] = {}
        if adopt_from is not None:
            try:
                rel = adopt_from.relative_to(run)
            except ValueError as exc:
                raise ValueError("--adopt-context-from must be an Analyst attempt directory under the current run") from exc
            parts = rel.parts
            if len(parts) != 6 or parts[0] != "phases" or parts[2] != "tasks" or parts[4] != "attempts" or not adopt_from.is_dir():
                raise ValueError("--adopt-context-from must be <run>/phases/<phase>/tasks/<task>/attempts/<analyst-attempt>")
            attempt_record = adopt_from / "task-attempt.json"
            if not attempt_record.is_file():
                raise ValueError("--adopt-context-from requires a recorded Analyst task-attempt.json")
            attempt_data = json.loads(attempt_record.read_text(encoding="utf-8"))
            if attempt_data.get("tier") != "analyst" or attempt_data.get("role") not in {"goal-planner", "planner", "discovery", "phase-surveyor", "recovery"}:
                raise ValueError("--adopt-context-from may only use Goal-Planner/Planner/Discovery/Phase-Surveyor/Recovery Analyst attempts")
            task_state_path = run / "phases" / parts[1] / "tasks" / parts[3] / "task.json"
            if not task_state_path.is_file():
                raise ValueError("--adopt-context-from cannot verify the source task state")
            task_state = json.loads(task_state_path.read_text(encoding="utf-8"))
            gated_attempt = next((
                item for item in task_state.get("attempts", [])
                if isinstance(item, dict)
                and Path(str(item.get("event_dir") or "")).resolve() == adopt_from
                and item.get("status") == "gated"
            ), None)
            if gated_attempt is None:
                raise ValueError("--adopt-context-from requires a gated Analyst attempt")
            report = adopt_from / "report.md"
            report_resolved = str(report.resolve())
            accepted = task_state.get("status") in {"accepted", "integrated"} and str(task_state.get("accepted_report") or "") == report_resolved
            analysis = task_state.get("last_analysis") if isinstance(task_state.get("last_analysis"), dict) else {}
            routed = analysis.get("outcome") in {"resume", "replan", "replan-resume"} and str(analysis.get("report") or "") == report_resolved and Path(str(analysis.get("attempt") or "")).resolve() == adopt_from
            if not report.is_file() or not (accepted or routed):
                raise ValueError("Analyst context is mechanically gated but has not been approved: accept the Analyst result, or record analysis-result --outcome resume/replan/replan-resume for same-task diagnosis")
            dsd_task.require_context_review(task_state, gated_attempt, reason="Analyst context adoption")
            candidate = adopt_from / "project-protocol" / "PROJECT-PROTOCOL.md"
            if candidate.is_symlink():
                raise ValueError("Analyst-authored Project Protocol must be a regular file inside the attempt, not a symlink")
            if candidate.is_file():
                adopted_protocol = candidate.resolve()
            skills_dir = adopt_from / "worker-skills"
            if skills_dir.is_symlink():
                raise ValueError("Analyst-authored worker-skills directory must live inside the attempt, not be a symlink")
            if skills_dir.is_dir():
                for candidate in sorted(skills_dir.glob("*/SKILL.md")):
                    if candidate.parent.is_symlink() or candidate.is_symlink():
                        raise ValueError(f"Analyst-authored worker skill must live inside the attempt, not be a symlink: {candidate}")
                    skill_id = candidate.parent.name
                    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", skill_id):
                        raise ValueError(f"unsafe Analyst-authored worker skill id: {skill_id!r}")
                    adopted_skills[skill_id] = skill_dir(candidate)

        if args.project_protocol and args.clear_project_protocol:
            raise ValueError("use either --project-protocol or --clear-project-protocol, not both")
        if args.project_protocol and adopted_protocol is not None:
            raise ValueError("project protocol supplied both explicitly and by --adopt-context-from")
        if args.project_protocol:
            project_protocol_source = args.project_protocol.resolve()
        elif args.clear_project_protocol:
            project_protocol_source = None
        elif adopted_protocol is not None:
            project_protocol_source = adopted_protocol
        elif prior and prior.get("project_protocol"):
            project_protocol_source = Path(str(prior["project_protocol"])).resolve()
        else:
            project_protocol_source = None
        if project_protocol_source is not None and not project_protocol_source.is_file():
            raise ValueError(f"project protocol missing: {project_protocol_source}")

        skill_sources: dict[str, Path] = {}
        if prior:
            for skill_id, source_raw in prior.get("worker_skills", {}).items():
                source = Path(str(source_raw)).resolve()
                if source.is_file(): skill_sources[str(skill_id)] = skill_dir(source)
        builtins = skill / "worker" / "skills"
        builtin_ids: set[str] = set()
        if builtins.is_dir():
            for candidate in sorted(builtins.glob("*/SKILL.md")):
                skill_id = candidate.parent.name
                if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", skill_id):
                    builtin_ids.add(skill_id)
                    skill_sources[skill_id] = skill_dir(candidate)
        collisions = sorted(set(adopted_skills) & builtin_ids)
        if collisions:
            raise ValueError("Analyst-authored worker skill id collides with built-in skill: " + ", ".join(collisions))
        skill_sources.update(adopted_skills)
        for raw in args.worker_skill:
            if "=" not in raw:
                raise ValueError("--worker-skill must be ID=/absolute/path/to/skill-dir or ID=/absolute/path/to/SKILL.md")
            skill_id, source_raw = raw.split("=", 1)
            skill_id = skill_id.strip(); source = skill_dir(Path(source_raw))
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", skill_id):
                raise ValueError(f"unsafe worker skill id: {skill_id!r}")
            skill_sources[skill_id] = source
        for skill_id in args.drop_worker_skill:
            skill_id = skill_id.strip()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", skill_id):
                raise ValueError(f"unsafe worker skill id: {skill_id!r}")
            skill_sources.pop(skill_id, None)

        project_context = tmp / "project-context"; project_context.mkdir(parents=True, exist_ok=True)
        project_protocol_snapshot = None
        if project_protocol_source is not None:
            project_protocol_snapshot = project_context / "PROJECT-PROTOCOL.md"
            shutil.copy2(project_protocol_source, project_protocol_snapshot)

        skill_snapshots: dict[str, Path] = {}
        skill_descriptions: dict[str, str] = {}
        skills_root = tmp / "worker-skills"; skills_root.mkdir(parents=True, exist_ok=True)
        for skill_id, source in sorted(skill_sources.items()):
            dest_root = skills_root / skill_id
            shutil.copytree(source, dest_root, copy_function=shutil.copy2)
            dest = dest_root / "SKILL.md"
            skill_snapshots[skill_id] = dest
            skill_descriptions[skill_id] = skill_description(source, skill_id)
        catalog = tmp / "WORKER-SKILL-CATALOG.md"
        catalog_lines = [
            "# Reusable worker skill catalog", "",
            "Metadata-only discovery for planning/review Analyst roles that need reusable-skill visibility. Ordinary workers do not load this catalog; they receive only task-selected skill bodies.", "",
        ]
        catalog_lines += [f"- `{skill_id}` — {skill_descriptions[skill_id]}" for skill_id in sorted(skill_descriptions)] or ["- NONE"]
        catalog.write_text("\n".join(catalog_lines) + "\n", encoding="utf-8")

        authority = tmp / "authority"; authority.mkdir(parents=True, exist_ok=True)
        plan_snapshot = None
        if plan is not None:
            plan_snapshot = authority / ("PLAN" + plan.suffix)
            shutil.copy2(plan, plan_snapshot)
        instruction_snapshots = []
        for index, source in enumerate(instructions, 1):
            dest = authority / f"instruction-{index:02d}-{source.name}"
            shutil.copy2(source, dest); instruction_snapshots.append(dest)
        final_plan_snapshot = root / plan_snapshot.relative_to(tmp) if plan_snapshot else None
        final_instruction_snapshots = [root / x.relative_to(tmp) for x in instruction_snapshots]
        final_project_protocol = root / project_protocol_snapshot.relative_to(tmp) if project_protocol_snapshot else None
        final_skill_snapshots = {name: root / path.relative_to(tmp) for name, path in skill_snapshots.items()}
        final_skill_catalog = root / catalog.relative_to(tmp)
        lines = [
            "# T-BAG Run Rules", "", f"Revision: {args.revision}",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "Accepted plan authority: ESTABLISHED" if final_plan_snapshot else "Accepted plan authority: NONE (goal-only bootstrap)", "",
            "## Run-specific rules",
            *([f"- {x}" for x in run_rules] or ["- NONE"]), "",
            "Authority/context paths are disclosed only to roles that need them. COMMON.md holds universal worker rules; QUALITY.md holds shared technical method; the selected role SKILL.md holds role-specific behavior.", "",
        ]
        (tmp / "WORKER_RULES.md").write_text("\n".join(lines), encoding="utf-8")
        (tmp / "MANIFEST.json").write_text(json.dumps({
            "format": MANIFEST_FORMAT, "revision": args.revision,
            "path": str(root / "WORKER_RULES.md"), "protocol_dir": str(root / "protocol"),
            "protocol_files": list(PROTOCOL_FILES),
            "authority_plan": str(final_plan_snapshot) if final_plan_snapshot else None,
            "authority_files": ([str(final_plan_snapshot)] if final_plan_snapshot else []) + [str(p) for p in final_instruction_snapshots],
            "project_protocol": str(final_project_protocol) if final_project_protocol else None,
            "worker_skill_catalog": str(final_skill_catalog),
            "worker_skills": {name: str(path) for name, path in sorted(final_skill_snapshots.items())},
            "run_rules": run_rules,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        root.parent.mkdir(parents=True, exist_ok=True); tmp.rename(root)
        # Maintain one human-facing plan folder for the run. Worker authority remains
        # the frozen revision snapshot; this mirror exists so owners can read the plan
        # and chronological phase-gate reports without navigating attempt internals.
        if plan is not None:
            owner_plan_dir=run/"plan"; owner_plan_dir.mkdir(parents=True,exist_ok=True)
            owner_plan=owner_plan_dir/"PLAN.md"; owner_tmp=owner_plan.with_suffix(".md.tmp")
            shutil.copyfile(plan,owner_tmp); os.replace(owner_tmp,owner_plan)
        print(json.dumps(verify_snapshot(rules), indent=2, sort_keys=True)); return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"command":"prepare-worker-rules","error":str(exc)},sort_keys=True,separators=(",",":")))
        print(f"ERROR: {exc}", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
