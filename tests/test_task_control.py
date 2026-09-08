import json, os, subprocess, sys, tempfile, unittest, time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dsd_task, dsd_attempt, dsd_workspace, scope_snapshot


def git(cwd, *args):
    cp = subprocess.run(["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if cp.returncode:
        raise RuntimeError(cp.stderr)
    return cp.stdout.strip()


class TaskControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"; self.project.mkdir()
        git(self.project, "init", "-q"); git(self.project, "config", "user.email", "t@example.com"); git(self.project, "config", "user.name", "T")
        (self.project / "a.txt").write_text("a\n"); git(self.project, "add", "."); git(self.project, "commit", "-qm", "init")
        self.run = self.project / "TBag" / "runs" / "r1"; self.run.mkdir(parents=True)
        class A: pass
        a=A(); a.project_root=self.project; a.run_root=self.run; a.run_id="r1"; a.runtime_root=str(self.root/"runtime"); a.max_workers=4; a.grunt_driver="opencode"; a.grunt_model="grunt/model"; a.analyst_driver="opencode"; a.analyst_model="analyst/model"
        dsd_task.command_init(a)
        self.plan_n=0
    def tearDown(self): self.tmp.cleanup()

    def write_plan(self, tasks):
        self.plan_n += 1
        source_id=f"PLAN{self.plan_n}"
        source_brief=self.run/f"{source_id}-brief.md"; source_brief.write_text("# Analyst planning bootstrap\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=source_id; a.brief=source_brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",source_id)/"attempts"/"planner-1"; plan_dir=event/"plan"; tasks_dir=plan_dir/"tasks"; tasks_dir.mkdir(parents=True)
        report=event/"report.md"; report.write_text("Analyst produced the attached rolling task plan.\n")
        source=dsd_task.load_task(self.run,"P1",source_id); source.setdefault("attempts",[]).append({"task_id":source_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); source["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",source_id),source)
        entries=[]
        for t in tasks:
            brief=tasks_dir/f"{t['task_id']}.md"; brief.write_text(t.get("text",f"# {t['task_id']}\n"))
            item={k:v for k,v in t.items() if k not in {"text"}}
            item["brief"]="tasks/"+brief.name; entries.append(item)
        graph=plan_dir/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":entries}))
        ac=A(); ac.run_root=self.run; ac.phase_id="P1"; ac.task_id=source_id; ac.report=report; dsd_task.command_accept(ac)
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        return dsd_task.command_register_plan(a), graph

    def gated_review_report(self, task_id, name="reviewer-1", text="review\n", checkpoint_ref="dummy-review-checkpoint"):
        event=dsd_task.task_root(self.run,"P1",task_id)/"attempts"/name; event.mkdir(parents=True,exist_ok=True)
        report=event/"report.md"; report.write_text(text)
        task=dsd_task.load_task(self.run,"P1",task_id)
        task.setdefault("attempts",[]).append({"task_id":task_id,"role":"reviewer","status":"gated","event_dir":str(event),"checkpoint_ref":checkpoint_ref})
        task["status"]="awaiting-review"
        dsd_task.write_json(dsd_task.task_file(self.run,"P1",task_id),task)
        return report

    def gated_analysis_report(self, task_id, role="discovery", name=None, text="analysis\n"):
        name=name or f"{role}-1"
        event=dsd_task.task_root(self.run,"P1",task_id)/"attempts"/name; event.mkdir(parents=True,exist_ok=True)
        report=event/"report.md"; report.write_text(text)
        task=dsd_task.load_task(self.run,"P1",task_id)
        task.setdefault("attempts",[]).append({"task_id":task_id,"role":role,"tier":"analyst","status":"gated","event_dir":str(event)})
        task["status"]="active"
        dsd_task.write_json(dsd_task.task_file(self.run,"P1",task_id),task)
        return report


    def test_carry_from_requires_semantic_supersession(self):
        self.write_plan([{"task_id":"OLD-CARRY","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        with self.assertRaisesRegex(ValueError,"must also appear in supersedes"):
            self.write_plan([{"task_id":"NEW-CARRY","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"carry_from":"OLD-CARRY"}])

    def test_one_predecessor_delta_cannot_be_inherited_twice(self):
        self.write_plan([{"task_id":"OLD-SPLIT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        with self.assertRaisesRegex(ValueError,"claimed by multiple replacements"):
            self.write_plan([
                {"task_id":"NEW-A","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"supersedes":["OLD-SPLIT"],"carry_from":"OLD-SPLIT"},
                {"task_id":"NEW-B","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"supersedes":["OLD-SPLIT"],"carry_from":"OLD-SPLIT"},
            ])

    def test_replacement_plan_cannot_both_carry_and_rederive_same_predecessor(self):
        self.write_plan([{"task_id":"OLD-DISPOSITION","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        self.plan_n += 1
        source_id=f"PLAN{self.plan_n}"; source_brief=self.run/f"{source_id}-brief.md"; source_brief.write_text("# Analyst planning bootstrap\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=source_id; a.brief=source_brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",source_id)/"attempts"/"planner-1"; plan_dir=event/"plan"; tasks_dir=plan_dir/"tasks"; tasks_dir.mkdir(parents=True)
        report=event/"report.md"; report.write_text("plan\n"); (tasks_dir/"NEW-DISPOSITION.md").write_text("# NEW\n")
        graph=plan_dir/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"rederive_from_primary":["OLD-DISPOSITION"],"tasks":[{"task_id":"NEW-DISPOSITION","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/NEW-DISPOSITION.md","dependencies":[],"supersedes":["OLD-DISPOSITION"],"carry_from":"OLD-DISPOSITION"}]}))
        source=dsd_task.load_task(self.run,"P1",source_id); source["attempts"].append({"task_id":source_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); source["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",source_id),source)
        ac=A(); ac.run_root=self.run; ac.phase_id="P1"; ac.task_id=source_id; ac.report=report; dsd_task.command_accept(ac)
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.plan=graph
        with self.assertRaisesRegex(ValueError,"choose carry_from or rederive_from_primary"):
            dsd_task.command_register_plan(r)

    def test_carry_from_cannot_resurrect_already_superseded_predecessor(self):
        self.write_plan([{"task_id":"OLD-RETIRED","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        self.write_plan([{"task_id":"FIRST-REPLACEMENT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"supersedes":["OLD-RETIRED"]}])
        with self.assertRaisesRegex(ValueError,"already-superseded predecessor OLD-RETIRED"):
            self.write_plan([{"task_id":"LATE-CARRY","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"supersedes":["OLD-RETIRED"],"carry_from":"OLD-RETIRED"}])

    def test_run_has_no_global_state_or_current_contract(self):
        self.assertTrue((self.run/"run.json").is_file())
        self.assertFalse((self.run/"state.json").exists())
        self.assertNotIn("current_contract", (self.run/"run.json").read_text())

    def test_registered_replan_closes_standalone_analyst_control_task_and_returns_ready_set(self):
        self.plan_n += 1
        source_id=f"PLAN{self.plan_n}"; brief=self.run/f"{source_id}-brief.md"; brief.write_text("# Replan frontier\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=source_id; a.brief=brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",source_id)/"attempts"/"planner-1"; tasks=event/"plan"/"tasks"; tasks.mkdir(parents=True)
        report=event/"report.md"; report.write_text("REPLAN\n")
        (tasks/"NEW.md").write_text("# NEW\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"NEW","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/NEW.md","dependencies":[],"requires_integration":True}]}))
        task=dsd_task.load_task(self.run,"P1",source_id); task["attempts"].append({"task_id":source_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",source_id),task)
        a.report=report; a.outcome="replan"; dsd_task.command_analysis_result(a)
        self.assertEqual(dsd_task.load_task(self.run,"P1",source_id)["status"],"needs-analysis")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.plan=graph
        out=dsd_task.command_register_plan(r)
        self.assertTrue(out["source_closed"]); self.assertEqual([x["task_id"] for x in out["ready_registered"]],["NEW"])
        closed=dsd_task.load_task(self.run,"P1",source_id); self.assertEqual(closed["status"],"accepted"); self.assertEqual(closed["accepted_report"],str(report.resolve()))
        q=A(); q.run_root=self.run; q.phase_id="P1"; q.no_sweep=True
        reconciled=dsd_task.command_reconcile_run(q)
        self.assertFalse(any(x.get("task_id")==source_id for x in reconciled.get("first_useful_actions",[])),reconciled)

    def test_independent_tasks_are_both_ready(self):
        self.write_plan([
            {"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
            {"task_id":"T2","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False},
        ])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        ready=dsd_task.command_ready(a)["tasks"]
        self.assertEqual({x["task_id"] for x in ready if x["ready"]},{"T1","T2"})

    def test_decorated_allowlist_is_rejected_before_task_registration(self):
        bad="# BAD\n\n## Allowed source changes\n- DELETE `src/generated/file.ts`\n"
        with self.assertRaisesRegex(ValueError,"brief mechanical validation failed"):
            self.write_plan([{"task_id":"BAD-ALLOW","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":bad}])
        self.assertFalse(dsd_task.task_file(self.run,"P1","BAD-ALLOW").exists())

    def test_direct_registration_validates_contract_before_freezing_task(self):
        brief=self.root/"bad-direct.md"; brief.write_text("# BAD\n\n## Allowed source changes\n- Nothing else may change.\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="BAD-DIRECT"; a.brief=brief; a.kind="analysis"; a.role="discovery"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None; a.owner_authority=None
        with self.assertRaisesRegex(ValueError,"exactly one path"):
            dsd_task.command_register_direct(a)
        self.assertFalse(dsd_task.task_file(self.run,"P1","BAD-DIRECT").exists())

    def test_plan_brief_is_copied_verbatim(self):
        text="# T1\n\nExact analyst-authored technical brief.\n"
        self.write_plan([{"task_id":"T1","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False,"text":text}])
        task=dsd_task.load_task(self.run,"P1","T1")
        self.assertEqual(Path(task["brief"]).read_text(), text)

    def test_integration_conflict_evidence_is_passed_to_analyst_discovery(self):
        self.write_plan([{"task_id":"T-CONFLICT-CONTEXT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        evidence=self.run/"conflict.json"; evidence.write_text("{}")
        task=dsd_task.load_task(self.run,"P1","T-CONFLICT-CONTEXT"); task["status"]="needs-analysis"; task["last_integration_conflict"]={"evidence":str(evidence.resolve())}; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-CONFLICT-CONTEXT"),task)
        groups=dsd_attempt.task_input_groups(self.run,"P1",task,"discovery",[])
        self.assertIn(str(evidence.resolve()),groups["recovery_evidence"])

    def test_reconcile_never_advertises_duplicate_launch_for_live_reviewer(self):
        self.write_plan([{"task_id":"T-LIVE-REVIEW","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        task=dsd_task.load_task(self.run,"P1","T-LIVE-REVIEW")
        impl=dsd_task.task_root(self.run,"P1","T-LIVE-REVIEW")/"attempts"/"implementer-1"; impl.mkdir(parents=True)
        task["attempts"].append({"task_id":"T-LIVE-REVIEW","role":"implementer","tier":"grunt","status":"gated","event_dir":str(impl)})
        reviewer=dsd_task.task_root(self.run,"P1","T-LIVE-REVIEW")/"attempts"/"reviewer-1"; reviewer.mkdir(parents=True)
        task["attempts"].append({"task_id":"T-LIVE-REVIEW","role":"reviewer","tier":"grunt","status":"started","event_dir":str(reviewer),"monitor_pid":os.getpid()})
        task["status"]="awaiting-review"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-LIVE-REVIEW"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.no_sweep=True
        out=dsd_task.command_reconcile_run(a)
        self.assertTrue(any(x["task_id"]=="T-LIVE-REVIEW" for x in out["live_attempts"]),out)
        self.assertFalse(any(x.get("task_id")=="T-LIVE-REVIEW" and x.get("action")=="launch-fresh-reviewer" for x in out.get("first_useful_actions",[])),out)

    def test_nonmutating_preflight_plan_can_be_run_by_author_before_registration(self):
        root=self.run/"scratch-plan"; tasks=root/"tasks"; tasks.mkdir(parents=True)
        (tasks/"SELF-CHECK.md").write_text("# Self-check\n\n## Worker skills\n- positive-control\n")
        graph=root/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"SELF-CHECK","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/SELF-CHECK.md","dependencies":[],"requires_integration":False}]}))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        out=dsd_task.command_preflight_plan(a)
        self.assertTrue(out["valid"]); self.assertEqual(out["task_ids"],["SELF-CHECK"])
        self.assertFalse(dsd_task.task_file(self.run,"P1","SELF-CHECK").exists())

    def test_plan_preflight_rejects_role_names_or_unknown_worker_skills_against_frozen_rules(self):
        from unittest.mock import patch
        root=self.run/"skill-plan"; tasks=root/"tasks"; tasks.mkdir(parents=True)
        (tasks/"BAD-SKILL.md").write_text("# Bad skill\n\n## Analyst skills\n- dsd-phase-surveyor\n- made-up-skill\n")
        graph=root/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"BAD-SKILL","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/BAD-SKILL.md","dependencies":[],"requires_integration":False}]}))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        with patch.object(dsd_task,"rules_revisions",return_value=[self.run/"worker-rules"/"1"]), patch.object(dsd_task,"verify_snapshot",return_value={"worker_skills":{"positive-control":{}}}):
            with self.assertRaises(ValueError) as cm:
                dsd_task.command_preflight_plan(a)
        msg=str(cm.exception)
        self.assertIn("unknown worker skill",msg)
        self.assertIn("dsd-phase-surveyor",msg)
        self.assertIn("role name(s) used as worker skill",msg)
        self.assertIn("made-up-skill",msg)

    def test_plan_preflight_validates_later_role_skill_sections_before_registration(self):
        from unittest.mock import patch
        root=self.run/"later-role-skill-plan"; tasks=root/"tasks"; tasks.mkdir(parents=True)
        (tasks/"BAD-LATER-SKILL.md").write_text("# Bad later skill\n\n## Implementer skills\n- positive-control\n\n## Reviewer skills\n- missing-review-skill\n")
        graph=root/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"BAD-LATER-SKILL","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/BAD-LATER-SKILL.md","dependencies":[],"requires_integration":True}]}))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        with patch.object(dsd_task,"rules_revisions",return_value=[self.run/"worker-rules"/"1"]), patch.object(dsd_task,"verify_snapshot",return_value={"worker_skills":{"positive-control":{}}}):
            with self.assertRaisesRegex(ValueError,"missing-review-skill"):
                dsd_task.command_preflight_plan(a)
        self.assertFalse(dsd_task.task_file(self.run,"P1","BAD-LATER-SKILL").exists())

    def test_plan_preflight_validates_later_role_skill_syntax_before_registration(self):
        with self.assertRaisesRegex(ValueError,"Reviewer skills entries must be bare skill IDs"):
            self.write_plan([{
                "task_id":"BAD-LATER-SYNTAX","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],
                "text":"# Bad later syntax\n\n## Reviewer skills\n- positive-control (review this carefully)\n",
            }])
        self.assertFalse(dsd_task.task_file(self.run,"P1","BAD-LATER-SYNTAX").exists())

    def test_plan_preflight_ignores_quoted_skill_heading_inside_fence(self):
        from unittest.mock import patch
        root=self.run/"quoted-skill-plan"; tasks=root/"tasks"; tasks.mkdir(parents=True)
        (tasks/"QUOTED-SKILL.md").write_text("# Repair parser\n\nQuoted prior defect:\n\n```markdown\n## Analyst skills\n- dsd-phase-surveyor\n```\n\n## Analyst skills\n- positive-control\n")
        graph=root/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"QUOTED-SKILL","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/QUOTED-SKILL.md","dependencies":[],"requires_integration":False}]}))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        with patch.object(dsd_task,"rules_revisions",return_value=[self.run/"worker-rules"/"1"]), patch.object(dsd_task,"verify_snapshot",return_value={"worker_skills":{"positive-control":{}}}):
            out=dsd_task.command_preflight_plan(a)
        self.assertTrue(out["valid"])

    def test_plan_preflight_rejects_non_bullet_mechanical_sections_early(self):
        with self.assertRaisesRegex(ValueError,"Allowed source changes must contain only"):
            self.write_plan([{"task_id":"BAD-FENCE","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":"# Bad\n\n## Allowed source changes\n```text\nsrc/a.ts\n```\n"}])
        with self.assertRaisesRegex(ValueError,"must be bare skill IDs"):
            self.write_plan([{"task_id":"BAD-SKILL-DESC","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False,"text":"# Bad\n\n## Worker skills\n- positive-control (prove it)\n"}])

    def test_plan_registration_reports_all_task_shape_errors_together(self):
        with self.assertRaises(ValueError) as cm:
            self.write_plan([
                {"task_id":"BAD1","kind":"analysis","role":"reviewer","tier":"analyst","dependencies":[],"requires_integration":False},
                {"task_id":"BAD2","kind":"verification","role":"phase-auditor","tier":"grunt","dependencies":[],"requires_integration":False},
                {"task_id":"BAD3","kind":"implementation","role":"implementer","tier":"strong","dependencies":[]},
                {"task_id":"VALID-SHAPE","kind":"analysis","role":"discovery","tier":"analyst","dependencies":["MISSING"],"requires_integration":False},
            ])
        msg=str(cm.exception)
        self.assertIn("BAD1",msg); self.assertIn("BAD2",msg); self.assertIn("BAD3",msg)
        self.assertIn("VALID-SHAPE",msg); self.assertIn("unknown dependencies",msg)

    def test_registered_brief_is_read_only_and_task_list_is_builtin(self):
        self.write_plan([{"task_id":"T-LIST","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        task=dsd_task.load_task(self.run,"P1","T-LIST")
        self.assertEqual(Path(task["brief"]).stat().st_mode & 0o222,0)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.status=None
        rows=dsd_task.command_list(a)["tasks"]
        self.assertEqual([r["task_id"] for r in rows if r["task_id"]=="T-LIST"],["T-LIST"])

    def _dead_attempt_with_scope(self, task_id, *, changed_path=None):
        class A: pass
        w=A(); w.run_root=self.run; w.phase_id="P1"; w.task_id=task_id
        ws=dsd_workspace.command_create(w); wt=Path(ws["worktree"])
        c=A(); c.run_root=self.run; c.phase_id="P1"; c.task_id=task_id; c.label="implementer-1"
        checkpoint=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        event=dsd_task.task_root(self.run,"P1",task_id)/"attempts"/"implementer-1"; event.mkdir(parents=True)
        baseline=event/"scope-baseline.json"; baseline.write_text(json.dumps(scope_snapshot.capture(wt,checkpoint)))
        task=dsd_task.load_task(self.run,"P1",task_id)
        reservation={"project_root":str(wt),"scope_baseline":str(baseline),"task_contract":task["brief"],"role":"implementer","writes_project":True}
        (event/"launch-reservation.json").write_text(json.dumps(reservation))
        task["attempts"].append({"task_id":task_id,"role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"worker_pid":99999999,"prior_task_status":"planned"}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",task_id),task)
        if changed_path: (wt/changed_path).write_text("partial worker change\n")
        return wt,event

    def test_sweep_stale_retries_mechanically_admissible_dead_attempt_without_recovery(self):
        self.write_plan([{"task_id":"T-STALE","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":"# T-STALE\n\n## Allowed source changes\n- a.txt\n"}])
        wt,event=self._dead_attempt_with_scope("T-STALE",changed_path="a.txt")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_sweep_stale(a)
        self.assertEqual(out["count"],1); self.assertEqual(out["marked"][0]["disposition"],"safe-retry")
        task=dsd_task.load_task(self.run,"P1","T-STALE")
        self.assertEqual(task["status"],"planned"); self.assertEqual(task["attempts"][-1]["status"],"stale-unresolved")
        self.assertEqual(task["attempts"][-1]["stale_changed_paths"],["a.txt"]); self.assertTrue((wt/"a.txt").is_file())

    def test_sweep_stale_routes_recovery_only_when_dead_attempt_residual_state_breaks_contract(self):
        self.write_plan([{"task_id":"T-STALE-BAD","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":"# T-STALE-BAD\n\n## Allowed source changes\n- a.txt\n"}])
        self._dead_attempt_with_scope("T-STALE-BAD",changed_path="b.txt")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_sweep_stale(a)
        self.assertEqual(out["count"],1); self.assertEqual(out["marked"][0]["disposition"],"recovery-required")
        task=dsd_task.load_task(self.run,"P1","T-STALE-BAD")
        self.assertEqual(task["status"],"recovery-required"); self.assertEqual(task["attempts"][-1]["stale_reason"],"changes-outside-authorized-scope")

    def test_attempt_inspect_is_nonblocking_and_distinguishes_running_terminal_and_dead(self):
        self.write_plan([{"task_id":"T-OBS","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        event=dsd_task.task_root(self.run,"P1","T-OBS")/"attempts"/"implementer-1"; event.mkdir(parents=True)
        (event/"report.md").write_text("# T-BAG worker report placeholder\nDSD_WORKER_REPORT_PLACEHOLDER_V2_1\nAttempt: x\nAppend running status below while working. Keep the marker until the report is complete; remove the marker only when the final self-contained report is ready.\nWorking on lifecycle wiring.\n")
        (event/"worker.log").write_text("worker output\n")
        task=dsd_task.load_task(self.run,"P1","T-OBS"); task["attempts"].append({"task_id":"T-OBS","role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"monitor_pid":os.getpid()}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-OBS"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T-OBS"; a.event_dir=None
        running=dsd_attempt.command_inspect(a)
        self.assertEqual(running["state"],"running"); self.assertEqual(running["next_action"],"running-progress-unknown"); self.assertEqual(running["progress_assessment"],"unknown"); self.assertEqual(running["report_state"],"in-progress"); self.assertNotIn("semantics",running); self.assertIn("log_bytes",running); self.assertIn("report_age_seconds",running); self.assertIn("elapsed_seconds",running)
        (event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0,"task_id":"T-OBS","role":"implementer"}))
        terminal=dsd_attempt.command_inspect(a)
        self.assertEqual(terminal["state"],"terminal"); self.assertEqual(terminal["next_action"],"gate")
        (event/"terminal.json").unlink(); task=dsd_task.load_task(self.run,"P1","T-OBS"); task["attempts"][-1]["monitor_pid"]=99999999; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-OBS"),task)
        dead=dsd_attempt.command_inspect(a)
        self.assertEqual(dead["state"],"dead-unresolved"); self.assertEqual(dead["next_action"],"sweep-stale")

    def test_inspect_surfaces_long_running_stale_report_as_attention_not_semantic_failure(self):
        self.write_plan([{"task_id":"T-OBS-LONG","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        base=time.time()-4000
        for idx in (1,2):
            event=dsd_task.task_root(self.run,"P1","T-OBS-LONG")/"attempts"/f"implementer-{idx}"; event.mkdir(parents=True,exist_ok=True)
            started=datetime.fromtimestamp(base+idx*10,timezone.utc).isoformat(); ended=datetime.fromtimestamp(base+idx*10+600,timezone.utc).isoformat()
            (event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0,"started_at":started,"ended_at":ended}))
        current=dsd_task.task_root(self.run,"P1","T-OBS-LONG")/"attempts"/"implementer-3"; current.mkdir(parents=True)
        started=datetime.fromtimestamp(time.time()-2000,timezone.utc).isoformat(); (current/"attempt.json").write_text(json.dumps({"started_at":started,"worker_pid":os.getpid()}))
        report=current/"report.md"; report.write_text("# T-BAG worker report placeholder\nDSD_WORKER_REPORT_PLACEHOLDER_V2_1\nWorking but no milestone.\n")
        log=current/"worker.log"; log.write_text("active loop\n")
        os.utime(report,(time.time()-1900,time.time()-1900)); os.utime(log,(time.time(),time.time()))
        task=dsd_task.load_task(self.run,"P1","T-OBS-LONG")
        task["attempts"]=[
            {"task_id":"T-OBS-LONG","role":"implementer","tier":"grunt","status":"gated","event_dir":str(dsd_task.task_root(self.run,"P1","T-OBS-LONG")/"attempts"/"implementer-1")},
            {"task_id":"T-OBS-LONG","role":"implementer","tier":"grunt","status":"gated","event_dir":str(dsd_task.task_root(self.run,"P1","T-OBS-LONG")/"attempts"/"implementer-2")},
            {"task_id":"T-OBS-LONG","role":"implementer","tier":"grunt","status":"started","event_dir":str(current),"monitor_pid":os.getpid()},
        ]; task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-OBS-LONG"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T-OBS-LONG"; a.event_dir=current
        out=dsd_attempt.command_inspect(a)
        self.assertEqual(out["progress_assessment"],"unknown"); self.assertEqual(out["attention"],"long-running-with-stale-report-while-log-is-active"); self.assertEqual(out["next_action"],"consider-intervention")
        self.assertEqual(out["role_duration_reference"]["samples"],2); self.assertEqual(out["role_duration_reference"]["median_seconds"],600.0)
        self.assertGreater(out["elapsed_seconds"],1900); self.assertGreater(out["report_age_seconds"],1800)

    def test_idle_check_requires_generic_harness_observer_without_embedding_harness_policy(self):
        self.write_plan([{"task_id":"T-LIVE-GENERIC","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        event=dsd_task.task_root(self.run,"P1","T-LIVE-GENERIC")/"attempts"/"implementer-1"; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,"P1","T-LIVE-GENERIC"); task["attempts"].append({"task_id":"T-LIVE-GENERIC","role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"monitor_pid":os.getpid()}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-LIVE-GENERIC"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_idle_check(a)
        self.assertTrue(out["safe_to_end_routine_turn"]); self.assertEqual(out["reason"],"workers-live")
        self.assertTrue(out["observer_required"]); self.assertNotIn("live_supervision_rule",out)
        self.assertNotIn("harness_supervision",out); self.assertNotIn("opencode",json.dumps(out).lower())

    def test_reconcile_run_sweeps_stale_and_surfaces_ready_work_without_repo_archaeology(self):
        self.write_plan([
            {"task_id":"T-READY","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":"# Improve startup routing (T-READY)\n"},
            {"task_id":"T-STALE-R","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
        ])
        event=dsd_task.task_root(self.run,"P1","T-STALE-R")/"attempts"/"implementer-1"; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,"P1","T-STALE-R"); task["attempts"].append({"task_id":"T-STALE-R","role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"worker_pid":99999999}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-STALE-R"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.no_sweep=False; a.details=True
        out=dsd_task.command_reconcile_run(a)
        actions={(x["task_id"],x["action"]) for x in out["actions"]}
        self.assertIn(("T-READY","launch-ready-task"),actions); self.assertIn(("T-STALE-R","launch-recovery"),actions)
        self.assertEqual(out["swept_stale"]["count"],1); self.assertNotIn("semantics",out)
        self.assertEqual(out["status_counts"]["planned"],1); self.assertEqual(out["status_counts"]["recovery-required"],1)
        self.assertEqual(out["backlog_count"],2); self.assertEqual({x["task_id"] for x in out["backlog"]},{"T-READY","T-STALE-R"}); self.assertTrue(all(x.get("brief") for x in out["backlog"]))
        self.assertEqual(next(x for x in out["backlog"] if x["task_id"]=="T-READY")["label"],"Improve startup routing (T-READY)")

    def test_reconcile_default_omits_full_backlog_and_cleanup_inventory(self):
        self.write_plan([{"task_id":"T-COMPACT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.no_sweep=True
        out=dsd_task.command_reconcile_run(a)
        self.assertEqual(out["backlog_count"],1)
        self.assertNotIn("backlog",out); self.assertNotIn("cleanup_candidates",out); self.assertNotIn("actions",out); self.assertNotIn("worker_runtimes",out); self.assertNotIn("semantics",out)
        self.assertTrue(any(x.get("task_id")=="T-COMPACT" for x in out["first_useful_actions"]))
        self.assertIn("scheduler_warning",out)

    def test_resume_last_can_return_to_prior_base_session_after_recovery_handoff(self):
        task={
            "kind":"implementation","role":"implementer","status":"planned",
            "attempts":[
                {"role":"implementer","status":"stale-unresolved","session_id":"impl-session"},
                {"role":"recovery","status":"gated","session_id":"recovery-session"},
            ],
        }
        self.assertEqual(dsd_attempt.resolve_resume_session(task,"implementer","planned",None,True),"impl-session")

    def test_in_progress_report_prefers_recorded_session_but_allows_cold_retry_when_transport_lost_it(self):
        task={"kind":"implementation","role":"implementer","status":"active","attempts":[{"role":"implementer","status":"mutating-report-resume","session_id":"ses-1"}]}
        with self.assertRaisesRegex(ValueError,"resume the recorded same-role session"):
            dsd_attempt.validate_launch_role(task,"implementer",continuing=False)
        dsd_attempt.validate_launch_role(task,"implementer",continuing=True)
        task["attempts"][-1].pop("session_id")
        dsd_attempt.validate_launch_role(task,"implementer",continuing=False)

    def test_reconcile_routes_reportless_admissible_mutation_to_same_role_retry_without_session(self):
        task={"task_id":"T","kind":"implementation","role":"implementer","tier":"grunt","status":"active","requires_integration":True,"attempts":[{"role":"implementer","status":"mutating-report-resume","event_dir":"/tmp/no-session"}]}
        action=dsd_task._reconcile_action(self.run,"P1",task)
        self.assertEqual(action["action"],"retry-same-role-retained-workspace"); self.assertEqual(action["role"],"implementer")

    def test_sweep_stale_is_idempotent(self):
        self.write_plan([{"task_id":"T-STALE-IDEMP","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        event=dsd_task.task_root(self.run,"P1","T-STALE-IDEMP")/"attempts"/"implementer-1"; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,"P1","T-STALE-IDEMP"); task["attempts"].append({"task_id":"T-STALE-IDEMP","role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"worker_pid":99999999}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-STALE-IDEMP"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        self.assertEqual(dsd_task.command_sweep_stale(a)["count"],1)
        self.assertEqual(dsd_task.command_sweep_stale(a)["count"],0)

    def test_project_changing_dependency_requires_integration(self):
        self.write_plan([
            {"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
            {"task_id":"T2","kind":"implementation","role":"implementer","tier":"grunt","dependencies":["T1"]},
        ])
        p=dsd_task.task_file(self.run,"P1","T1"); t=dsd_task.load_json(p); t["status"]="accepted"; dsd_task.write_json(p,t)
        t2=dsd_task.load_task(self.run,"P1","T2"); ok,missing=dsd_task.readiness(self.run,"P1",t2)
        self.assertFalse(ok); self.assertEqual(missing,["T1"])
        t["status"]="integrated"; dsd_task.write_json(p,t)
        self.assertTrue(dsd_task.readiness(self.run,"P1",t2)[0])

    def test_analysis_dependency_only_needs_acceptance(self):
        self.write_plan([
            {"task_id":"A1","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False},
            {"task_id":"T2","kind":"implementation","role":"implementer","tier":"grunt","dependencies":["A1"]},
        ])
        report=self.gated_analysis_report("A1",text="analysis result\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="A1"; a.report=report; dsd_task.command_accept(a)
        self.assertTrue(dsd_task.readiness(self.run,"P1",dsd_task.load_task(self.run,"P1","T2"))[0])

    def test_grunt_review_escalation_routes_to_analyst(self):
        self.write_plan([{"task_id":"T-ANALYZE","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        report=self.gated_review_report("T-ANALYZE","reviewer-1","Failure is recurring and needs diagnosis; basis not disproven.\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T-ANALYZE"; a.outcome="escalate"; a.report=report
        out=dsd_task.command_review(a)
        self.assertEqual(out["status"],"needs-analysis")
        updated=dsd_task.load_task(self.run,"P1","T-ANALYZE")
        self.assertEqual(updated["last_review"]["outcome"],"escalate")
        self.assertEqual(updated["last_escalation"]["target"],"analyst")

    def test_human_accept_route_preserves_red_review_and_records_explicit_authority(self):
        self.write_plan([{"task_id":"HUMAN-ACCEPT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        review=self.gated_review_report("HUMAN-ACCEPT","reviewer-1","ESCALATE: owner must decide whether composed evidence is sufficient.\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="HUMAN-ACCEPT"; a.outcome="escalate"; a.report=review
        self.assertEqual(dsd_task.command_review(a)["status"],"needs-analysis")
        analysis=self.gated_analysis_report("HUMAN-ACCEPT",role="discovery",name="discovery-1",text="ESCALATE: this is an owner acceptance decision.\n")
        a.outcome="escalate"; a.report=analysis
        self.assertEqual(dsd_task.command_analysis_result(a)["status"],"blocked")
        decision=self.run/"owner-accept.md"; decision.write_text("Accept this reviewed implementation despite the recorded escalation; preserve the red evidence.\n")
        a.decision=decision; a.route="accept"
        out=dsd_task.command_resolve_escalation(a)
        self.assertEqual(out["status"],"accepted"); self.assertEqual(out["acceptance_basis"],"explicit-human-authority")
        task=dsd_task.load_task(self.run,"P1","HUMAN-ACCEPT")
        self.assertEqual(task["last_review"]["outcome"],"escalate")
        self.assertEqual(task["human_acceptance"]["review_report"],str(review.resolve()))
        self.assertEqual(task["accepted_report"],task["last_human_decision"]["path"])

    def test_human_accept_route_cannot_bypass_fresh_task_review(self):
        self.write_plan([{"task_id":"NO-REVIEW-ACCEPT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        analysis=self.gated_analysis_report("NO-REVIEW-ACCEPT",role="discovery",name="discovery-1",text="ESCALATE\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="NO-REVIEW-ACCEPT"; a.outcome="escalate"; a.report=analysis
        dsd_task.command_analysis_result(a)
        decision=self.run/"owner-no-review.md"; decision.write_text("accept\n"); a.decision=decision; a.route="accept"
        with self.assertRaisesRegex(ValueError,"cannot bypass task Review"):
            dsd_task.command_resolve_escalation(a)

    def test_human_decision_snapshot_uses_next_free_index_when_parent_note_collides(self):
        self.write_plan([{"task_id":"HUMAN-IDX","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        report=self.gated_analysis_report("HUMAN-IDX",text="ESCALATE\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="HUMAN-IDX"; a.outcome="escalate"; a.report=report
        dsd_task.command_analysis_result(a)
        decisions=self.run/"authority"/"decisions"; decisions.mkdir(parents=True,exist_ok=True)
        (decisions/"P1--HUMAN-IDX--001.md").write_text("parent note\n")
        decision=self.run/"owner.md"; decision.write_text("resume\n")
        a.decision=decision; a.route="resume"
        out=dsd_task.command_resolve_escalation(a)
        self.assertTrue(out["decision"].endswith("P1--HUMAN-IDX--002.md"),out)

    def test_repeated_concrete_review_failures_stay_in_grunt_fix_loop(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        report=self.gated_review_report("T1","reviewer-1","defect\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.outcome="fail"; a.report=report
        first=dsd_task.command_review(a); self.assertEqual(first["status"],"needs-fix")
        report2=self.gated_review_report("T1","reviewer-2","another concrete defect\n","dummy-review-checkpoint-2")
        a.report=report2
        second=dsd_task.command_review(a); self.assertEqual(second["status"],"needs-fix")
        self.assertEqual(second["review_rounds"],2)

    def test_reviewer_escalation_skips_fixer_loop(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        report=self.gated_review_report("T1","reviewer-1","basis wrong\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.outcome="escalate"; a.report=report
        self.assertEqual(dsd_task.command_review(a)["status"],"needs-analysis")

    def test_implementation_accept_requires_review_pass(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.report=None
        with self.assertRaises(ValueError): dsd_task.command_accept(a)
        report=self.gated_review_report("T1","reviewer-1","pass\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id="T1"; r.outcome="pass"; r.report=report
        self.assertEqual(dsd_task.command_review(r)["status"],"review-passed")
        self.assertEqual(dsd_task.command_accept(a)["status"],"accepted")

    def test_analysis_can_be_accepted_without_review_but_requires_result_report(self):
        self.write_plan([{"task_id":"A1","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="A1"; a.report=None
        with self.assertRaises(ValueError): dsd_task.command_accept(a)
        report=self.gated_analysis_report("A1",text="measured result\n"); a.report=report
        self.assertEqual(dsd_task.command_accept(a)["status"],"accepted")
        self.assertEqual(Path(dsd_task.load_task(self.run,"P1","A1")["accepted_report"]).read_text(),"measured result\n")

    def test_dependency_reports_are_passed_without_parent_paraphrase(self):
        self.write_plan([
            {"task_id":"A1","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False},
            {"task_id":"T2","kind":"implementation","role":"implementer","tier":"grunt","dependencies":["A1"]},
        ])
        report=self.gated_analysis_report("A1",text="exact analyst result\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="A1"; a.report=report; dsd_task.command_accept(a)
        task=dsd_task.load_task(self.run,"P1","T2")
        inputs=[x for group in dsd_attempt.task_input_groups(self.run,"P1",task,"implementer",[]).values() for x in group]
        self.assertEqual(inputs,[str(report.resolve())])

    def test_runtime_never_falls_back_or_invents_driver(self):
        with self.assertRaises(ValueError):
            dsd_attempt.resolve_runtime({"worker_runtimes":{"grunt":{"driver":"opencode","model":"cheap","options":{}}}},"analyst",None,None)
        self.assertEqual(dsd_attempt.resolve_runtime({"worker_runtimes":{"grunt":{"driver":"opencode","model":"cheap","options":{}}}},"grunt",None,None)[:2],("opencode","cheap"))
        with self.assertRaises(ValueError):
            dsd_attempt.resolve_runtime({},"grunt",None,"cheap")
        with self.assertRaisesRegex(ValueError,"RUNTIME_OVERRIDE_MISMATCH"):
            dsd_attempt.resolve_runtime({"worker_runtimes":{"analyst":{"driver":"opencode","model":"opus","options":{}}}},"analyst","codex",None)
        self.assertEqual(dsd_attempt.resolve_runtime({"worker_runtimes":{"analyst":{"driver":"opencode","model":"opus","options":{}}}},"analyst","codex","gpt-5.6")[:2],("codex","gpt-5.6"))

    def test_fresh_reviewer_gets_latest_worker_report_but_not_previous_review(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        root=dsd_task.task_root(self.run,"P1","T1")/"attempts"
        impl=root/"implementer-1"; impl.mkdir(parents=True); (impl/"report.md").write_text("implementation\n")
        review=root/"reviewer-1"; review.mkdir(); (review/"report.md").write_text("first review\n")
        task=dsd_task.load_task(self.run,"P1","T1"); task["attempts"]=[{"role":"implementer","event_dir":str(impl),"status":"gated"},{"role":"reviewer","event_dir":str(review),"status":"gated"}]; task["last_review"]={"report":str(review/"report.md"),"outcome":"fail"}; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T1"),task)
        inputs=[x for group in dsd_attempt.task_input_groups(self.run,"P1",task,"reviewer",[]).values() for x in group]
        self.assertIn(str((impl/"report.md").resolve()),inputs); self.assertNotIn(str((review/"report.md").resolve()),inputs)

    def test_plan_registration_preflights_all_tasks_before_writing(self):
        self.write_plan([{"task_id":"EXISTING","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        self.plan_n += 1; source_id=f"PLAN{self.plan_n}"; source_brief=self.run/f"{source_id}-brief.md"; source_brief.write_text("# planner\n")
        class A: pass
        a=A();a.run_root=self.run;a.phase_id="P1";a.task_id=source_id;a.brief=source_brief;a.kind="analysis";a.role="planner";a.tier="analyst";a.dependency=[];a.requires_integration=False;dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",source_id)/"attempts"/"planner-1"; (event/"plan"/"tasks").mkdir(parents=True); report=event/"report.md";report.write_text("plan\n")
        st=dsd_task.load_task(self.run,"P1",source_id);st["attempts"].append({"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)});st["status"]="active";dsd_task.write_json(dsd_task.task_file(self.run,"P1",source_id),st)
        for tid in ("NEW","EXISTING"):(event/"plan"/"tasks"/f"{tid}.md").write_text(f"# {tid}\n")
        graph=event/"plan"/"task-graph.json";graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"NEW","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/NEW.md","dependencies":[],"requires_integration":False},{"task_id":"EXISTING","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/EXISTING.md","dependencies":[],"requires_integration":False}]}))
        ac=A();ac.run_root=self.run;ac.phase_id="P1";ac.task_id=source_id;ac.report=report
        dsd_task.command_accept(ac)
        rp=A(); rp.run_root=self.run; rp.phase_id="P1"; rp.plan=graph
        with self.assertRaises(ValueError): dsd_task.command_register_plan(rp)
        self.assertFalse(dsd_task.task_file(self.run,"P1","NEW").exists())

    def test_goal_planner_acceptance_requires_fresh_plan_review_pass(self):
        brief=self.run/"goal-planner.md"; brief.write_text("# goal planner\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-PLAN"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL-PLAN")/"attempts"/"goal-planner-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("plan report\n")
        plan=event/"plan"/"PLAN.md"; plan.parent.mkdir(); plan.write_text("# Goal\n\n## Phase 1\n")
        state=dsd_task.load_task(self.run,"bootstrap","GOAL-PLAN"); state["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event),"inputs":[]}); state["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-PLAN"),state)
        ac=A(); ac.run_root=self.run; ac.phase_id="bootstrap"; ac.task_id="GOAL-PLAN"; ac.report=report
        with self.assertRaisesRegex(ValueError, "review-passed"):
            dsd_task.command_accept(ac)

        rb=self.run/"review.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="GOAL-PLAN-REVIEW"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-PLAN"
        dsd_task.command_register_direct(r)
        rev_event=dsd_task.task_root(self.run,"bootstrap","GOAL-PLAN-REVIEW")/"attempts"/"plan-reviewer-1"; rev_event.mkdir(parents=True)
        rev_report=rev_event/"report.md"; rev_report.write_text("PASS\n")
        plan_snapshot=rev_event/"plan-under-review"/"PLAN.md"; plan_snapshot.parent.mkdir(); plan_snapshot.write_bytes(plan.read_bytes())
        rev=dsd_task.load_task(self.run,"bootstrap","GOAL-PLAN-REVIEW"); rev["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev_event),"plan_review_target":{"task_id":"GOAL-PLAN","attempt":str(event.resolve()),"plan":str(plan.resolve()),"source_plan":str(plan.resolve()),"plan_snapshot":str(plan_snapshot.resolve())}}); rev["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-PLAN-REVIEW"),rev)
        pr=A(); pr.run_root=self.run; pr.phase_id="bootstrap"; pr.task_id="GOAL-PLAN-REVIEW"; pr.outcome="pass"; pr.report=rev_report
        self.assertEqual(dsd_task.command_plan_review(pr)["goal_planner_status"],"review-passed")
        self.assertEqual(dsd_task.command_accept(ac)["status"], "accepted")

    def test_plan_review_rejects_symlinked_plan_snapshot(self):
        brief=self.run/"goal-link-snapshot.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-LINK-SNAPSHOT"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL-LINK-SNAPSHOT")/"attempts"/"goal-planner-1"; (event/"plan").mkdir(parents=True); (event/"report.md").write_text("planned\n"); plan=event/"plan"/"PLAN.md"; plan.write_text("# plan\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL-LINK-SNAPSHOT"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event)}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-LINK-SNAPSHOT"),goal)
        rb=self.run/"review-link-snapshot.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-LINK-SNAPSHOT"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-LINK-SNAPSHOT"; dsd_task.command_register_direct(r)
        rev=dsd_task.task_root(self.run,"bootstrap","REVIEW-LINK-SNAPSHOT")/"attempts"/"plan-reviewer-1"; rev.mkdir(parents=True); rr=rev/"report.md"; rr.write_text("PASS\n")
        snapshot=rev/"plan-under-review"/"PLAN.md"; snapshot.parent.mkdir(); snapshot.symlink_to(plan)
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-LINK-SNAPSHOT"); review["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev),"plan_review_target":{"task_id":"GOAL-LINK-SNAPSHOT","attempt":str(event.resolve()),"source_plan":str(plan.resolve()),"plan_snapshot":str(snapshot)}}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW-LINK-SNAPSHOT"),review)
        pr=A(); pr.run_root=self.run; pr.phase_id="bootstrap"; pr.task_id="REVIEW-LINK-SNAPSHOT"; pr.outcome="pass"; pr.report=rr
        with self.assertRaisesRegex(ValueError,"regular frozen copy"):
            dsd_task.command_plan_review(pr)

    def test_goal_plan_mutation_after_plan_review_pass_requires_fresh_review(self):
        brief=self.run/"goal-mutate.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-MUTATE"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL-MUTATE")/"attempts"/"goal-planner-1"; (event/"plan").mkdir(parents=True); report=event/"report.md"; report.write_text("planned\n"); plan=event/"plan"/"PLAN.md"; plan.write_text("# reviewed v1\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL-MUTATE"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event)}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-MUTATE"),goal)
        rb=self.run/"review-mutate.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-MUTATE"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-MUTATE"; dsd_task.command_register_direct(r)
        rev=dsd_task.task_root(self.run,"bootstrap","REVIEW-MUTATE")/"attempts"/"plan-reviewer-1"; rev.mkdir(parents=True); rr=rev/"report.md"; rr.write_text("PASS\n")
        snapshot=rev/"plan-under-review"/"PLAN.md"; snapshot.parent.mkdir(); snapshot.write_bytes(plan.read_bytes())
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-MUTATE"); review["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev),"plan_review_target":{"task_id":"GOAL-MUTATE","attempt":str(event.resolve()),"source_plan":str(plan.resolve()),"plan_snapshot":str(snapshot.resolve())}}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW-MUTATE"),review)
        pr=A(); pr.run_root=self.run; pr.phase_id="bootstrap"; pr.task_id="REVIEW-MUTATE"; pr.outcome="pass"; pr.report=rr
        dsd_task.command_plan_review(pr)
        plan.write_text("# changed after PASS\n")
        ac=A(); ac.run_root=self.run; ac.phase_id="bootstrap"; ac.task_id="GOAL-MUTATE"; ac.report=report
        with self.assertRaisesRegex(ValueError,"differs from the immutable copy"):
            dsd_task.command_accept(ac)

    def test_planner_findings_can_be_accepted_without_fabricating_a_graph(self):
        brief=self.run/"planner-findings.md"; brief.write_text("# Reconcile the frozen inventory and report findings only\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="PLAN-FINDINGS"; a.brief=brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        report=self.gated_analysis_report("PLAN-FINDINGS",role="planner",name="planner-1",text="No decomposition change is required; findings only.\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.no_sweep=True
        reconciled=dsd_task.command_reconcile_run(r)
        action=next(x for x in reconciled["first_useful_actions"] if x["task_id"]=="PLAN-FINDINGS")
        self.assertEqual(action["action"],"accept-specialist-result")
        a.report=report
        out=dsd_task.command_accept(a)
        self.assertEqual(out["status"],"accepted")
        self.assertEqual(dsd_task.load_task(self.run,"P1","PLAN-FINDINGS")["accepted_report"],str(report.resolve()))
        self.assertFalse((report.parent/"plan"/"task-graph.json").exists())


    def test_live_analyst_can_preflight_its_own_carry_replacement_graph(self):
        self.write_plan([{"task_id":"SELF-CARRY","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        w=A(); w.run_root=self.run; w.phase_id="P1"; w.task_id="SELF-CARRY"; ws=dsd_workspace.command_create(w); (Path(ws["worktree"])/"a.txt").write_text("preserved delta\n")
        event=dsd_task.task_root(self.run,"P1","SELF-CARRY")/"attempts"/"discovery-1"; tasks=event/"plan"/"tasks"; tasks.mkdir(parents=True)
        (tasks/"SELF-CARRY-R1.md").write_text("# Continue preserved work\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"SELF-CARRY-R1","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/SELF-CARRY-R1.md","dependencies":[],"requires_integration":True,"supersedes":["SELF-CARRY"],"carry_from":"SELF-CARRY"}]}))
        task=dsd_task.load_task(self.run,"P1","SELF-CARRY"); task["attempts"].append({"task_id":"SELF-CARRY","role":"discovery","tier":"analyst","status":"started","event_dir":str(event),"monitor_pid":os.getpid()}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","SELF-CARRY"),task)
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        out=dsd_task.command_preflight_plan(a); self.assertTrue(out["valid"]); self.assertEqual(out["task_ids"],["SELF-CARRY-R1"])

    def test_replan_resume_can_register_additional_work_and_return_current_task_to_base_lane(self):
        self.write_plan([{"task_id":"BOTH","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        path=dsd_task.task_file(self.run,"P1","BOTH"); task=dsd_task.load_json(path); task["status"]="needs-analysis"; dsd_task.write_json(path,task)
        event=dsd_task.task_root(self.run,"P1","BOTH")/"attempts"/"discovery-1"; tasks=event/"plan"/"tasks"; tasks.mkdir(parents=True); report=event/"report.md"; report.write_text("Current work stands; add follow-up wiring.\n")
        (tasks/"FOLLOW.md").write_text("# Follow-up\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"FOLLOW","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/FOLLOW.md","dependencies":[],"requires_integration":False}]}))
        task=dsd_task.load_task(self.run,"P1","BOTH"); task["attempts"].append({"task_id":"BOTH","role":"discovery","tier":"analyst","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(path,task)
        ar=A(); ar.run_root=self.run; ar.phase_id="P1"; ar.task_id="BOTH"; ar.outcome="replan-resume"; ar.report=report
        out=dsd_task.command_analysis_result(ar); self.assertEqual(out["status"],"planned")
        reg=A(); reg.run_root=self.run; reg.phase_id="P1"; reg.plan=graph; self.assertEqual(dsd_task.command_register_plan(reg)["registered"],["FOLLOW"])
        current=dsd_task.load_task(self.run,"P1","BOTH"); self.assertEqual(current["status"],"planned"); self.assertEqual(current["last_analysis"]["outcome"],"replan-resume")
        inputs=dsd_attempt.task_input_groups(self.run,"P1",current,"implementer",[]); self.assertIn(str(report.resolve()),inputs["analyst_finding"])

    def test_replan_routing_requires_replacement_graph_to_already_exist(self):
        self.write_plan([{"task_id":"REPLAN-MISSING","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        path=dsd_task.task_file(self.run,"P1","REPLAN-MISSING"); t=dsd_task.load_json(path); t["status"]="needs-analysis"; dsd_task.write_json(path,t)
        report=self.gated_analysis_report("REPLAN-MISSING",role="discovery",name="discovery-1",text="needs split\n")
        ar=A(); ar.run_root=self.run; ar.phase_id="P1"; ar.task_id="REPLAN-MISSING"; ar.outcome="replan"; ar.report=report
        with self.assertRaisesRegex(ValueError,"replan requires"): dsd_task.command_analysis_result(ar)

    def test_register_plan_rejects_parent_authored_graph_outside_analyst_attempt(self):
        graph=self.run/"manual-plan.json"; brief=self.run/"manual-task.md"; brief.write_text("# task\n")
        graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"BAD","kind":"implementation","role":"implementer","tier":"grunt","brief":str(brief),"dependencies":[]}]}))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        with self.assertRaises(ValueError): dsd_task.command_register_plan(a)

    def test_worker_budget_counts_independent_live_tasks_without_global_current_task(self):
        # The launch lock is brief; it limits process count, not concurrency of completed task state.
        info=dsd_task.load_json(self.run/"run.json"); info["max_workers"]=1; dsd_task.write_json(self.run/"run.json",info)
        self.write_plan([
            {"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
            {"task_id":"T2","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
        ])
        class A: pass
        event=dsd_task.task_root(self.run,"P1","T1")/"attempts"/"implementer-1";event.mkdir(parents=True)
        t=dsd_task.load_task(self.run,"P1","T1");t["attempts"].append({"task_id":"T1","role":"implementer","event_dir":str(event),"monitor_pid":os.getpid(),"status":"started"});t["status"]="active";dsd_task.write_json(dsd_task.task_file(self.run,"P1","T1"),t)
        args=A();args.run_root=self.run;args.phase_id="P1";args.task_id="T2"
        with self.assertRaisesRegex(ValueError,"worker budget exhausted"): dsd_attempt.command_launch(args)

    def test_plan_registration_requires_approved_analyst_result(self):
        self.plan_n += 1; source_id=f"PLAN{self.plan_n}"
        brief=self.run/f"{source_id}.md"; brief.write_text("# plan\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=source_id; a.brief=brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",source_id)/"attempts"/"planner-1"; (event/"plan"/"tasks").mkdir(parents=True)
        report=event/"report.md"; report.write_text("gated but not accepted\n")
        task=dsd_task.load_task(self.run,"P1",source_id); task["attempts"].append({"task_id":source_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",source_id),task)
        (event/"plan"/"tasks"/"T1.md").write_text("# T1\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"T1","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/T1.md","dependencies":[],"requires_integration":False}]}))
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.plan=graph
        with self.assertRaisesRegex(ValueError,"has not been approved"): dsd_task.command_register_plan(r)

    def test_replan_can_register_from_approved_same_task_analyst_result(self):
        self.write_plan([{"task_id":"OLD","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="OLD"
        path=dsd_task.task_file(self.run,"P1","OLD"); old=dsd_task.load_json(path); old["status"]="needs-analysis"; dsd_task.write_json(path,old)
        event=dsd_task.task_root(self.run,"P1","OLD")/"attempts"/"discovery-1"; (event/"plan"/"tasks").mkdir(parents=True)
        report=event/"report.md"; report.write_text("split this work\n")
        old=dsd_task.load_task(self.run,"P1","OLD"); old["attempts"].append({"task_id":"OLD","role":"discovery","tier":"analyst","status":"gated","event_dir":str(event)}); old["status"]="active"; dsd_task.write_json(path,old)
        (event/"plan"/"tasks"/"NEW.md").write_text("# NEW\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"NEW","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/NEW.md","dependencies":[],"requires_integration":True,"supersedes":["OLD"]}]}))
        ar=A(); ar.run_root=self.run; ar.phase_id="P1"; ar.task_id="OLD"; ar.outcome="replan"; ar.report=report; dsd_task.command_analysis_result(ar)
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.plan=graph
        self.assertEqual(dsd_task.command_register_plan(r)["registered"],["NEW"])
        self.assertEqual(dsd_task.load_task(self.run,"P1","OLD")["status"],"superseded")

    def test_analyst_plan_brief_cannot_escape_plan_directory(self):
        # Start from a valid accepted Planner package, then point a new task at an external brief.
        _, graph=self.write_plan([{"task_id":"SAFE","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        external=self.run/"outside-brief.md"; external.write_text("# external\n")
        data=json.loads(graph.read_text()); data["tasks"][0]["task_id"]="ESCAPE"; data["tasks"][0]["brief"]=str(external); graph.write_text(json.dumps(data))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.plan=graph
        with self.assertRaisesRegex(ValueError,"must be relative"): dsd_task.command_register_plan(a)

    def test_replan_can_split_one_old_task_into_multiple_replacements(self):
        self.write_plan([{"task_id":"OLD","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        self.plan_n += 1; sid=f"PLAN{self.plan_n}"; brief=self.run/f"{sid}.md"; brief.write_text("# planner\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=sid; a.brief=brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P1",sid)/"attempts"/"planner-1"; (event/"plan"/"tasks").mkdir(parents=True); report=event/"report.md"; report.write_text("split OLD into two bounded jobs\n")
        for tid in ("N1","N2"): (event/"plan"/"tasks"/f"{tid}.md").write_text(f"# {tid}\n")
        graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[
            {"task_id":"N1","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/N1.md","dependencies":[],"requires_integration":False,"supersedes":["OLD"]},
            {"task_id":"N2","kind":"analysis","role":"discovery","tier":"analyst","brief":"tasks/N2.md","dependencies":[],"requires_integration":False,"supersedes":["OLD"]}
        ]}))
        st=dsd_task.load_task(self.run,"P1",sid); st["attempts"].append({"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); st["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",sid),st)
        a.task_id=sid; a.report=report; dsd_task.command_accept(a); a.plan=graph
        self.assertEqual(dsd_task.command_register_plan(a)["registered"],["N1","N2"])
        old=dsd_task.load_task(self.run,"P1","OLD")
        self.assertEqual(old["status"],"superseded")
        self.assertEqual(old["superseded_by"],["N1","N2"])

    def test_task_kind_role_and_integration_shape_are_enforced(self):
        with self.assertRaises(ValueError):
            self.write_plan([{"task_id":"BAD","kind":"implementation","role":"discovery","tier":"analyst","dependencies":[]}])
        with self.assertRaisesRegex(ValueError,"must require integration"):
            self.write_plan([{"task_id":"BAD2","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"requires_integration":False}])
        with self.assertRaisesRegex(ValueError,"implementation tasks use the Grunt tier"):
            self.write_plan([{"task_id":"BAD3","kind":"implementation","role":"implementer","tier":"analyst","dependencies":[]}])

    def test_direct_registration_rejects_execution_tasks_without_owner_authority(self):
        brief=self.run/"direct-impl.md"; brief.write_text("# direct implementation\n")
        class A: pass
        a=A();a.run_root=self.run;a.phase_id="P1";a.task_id="DIRECT";a.brief=brief;a.kind="implementation";a.role="implementer";a.tier="grunt";a.dependency=[];a.requires_integration=True
        with self.assertRaisesRegex(ValueError,"direct implementation requires --owner-authority"):
            dsd_task.command_register_direct(a)
        self.assertFalse(dsd_task.task_root(self.run,"P1","DIRECT").exists())

    def test_analysis_accept_rejects_parent_authored_report(self):
        self.write_plan([{"task_id":"A1","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        fake=self.run/"parent-summary.md"; fake.write_text("parent version\n")
        path=dsd_task.task_file(self.run,"P1","A1"); t=dsd_task.load_json(path); t["status"]="active"; dsd_task.write_json(path,t)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="A1"; a.report=fake
        with self.assertRaisesRegex(ValueError,"gated Analyst attempt"): dsd_task.command_accept(a)

    def test_same_reviewer_attempt_cannot_be_counted_twice(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        report=self.gated_review_report("T1","reviewer-1","defect\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.outcome="fail"; a.report=report
        dsd_task.command_review(a)
        with self.assertRaisesRegex(ValueError,"already has a recorded"): dsd_task.command_review(a)
        self.assertEqual(dsd_task.load_task(self.run,"P1","T1")["review_rounds"],1)

    def test_integrated_task_cannot_be_superseded(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        path=dsd_task.task_file(self.run,"P1","T1"); t=dsd_task.load_json(path); t["status"]="integrated"; dsd_task.write_json(path,t)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.by="T2"
        with self.assertRaisesRegex(ValueError,"cannot supersede an integrated"): dsd_task.command_supersede(a)

    def test_plan_reviewer_cannot_resume_prior_review_session(self):
        task={"role":"plan-reviewer","status":"active","attempts":[{"role":"plan-reviewer","session_id":"s1"}]}
        with self.assertRaisesRegex(ValueError,"fresh session"):
            dsd_attempt.resolve_resume_session(task,"plan-reviewer","active",None,True)

    def test_plan_reviewer_requires_semantic_outcome_before_another_review_attempt(self):
        brief=self.run/"goal-pending-review.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-PENDING"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None; dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL-PENDING")/"attempts"/"goal-planner-1"; (event/"plan").mkdir(parents=True); (event/"report.md").write_text("planned\n"); (event/"plan"/"PLAN.md").write_text("# plan\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL-PENDING"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event)}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-PENDING"),goal)
        rb=self.run/"review-pending.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-PENDING"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-PENDING"; dsd_task.command_register_direct(r)
        rev_event=dsd_task.task_root(self.run,"bootstrap","REVIEW-PENDING")/"attempts"/"plan-reviewer-1"; rev_event.mkdir(parents=True); (rev_event/"report.md").write_text("PASS\n")
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-PENDING"); review["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev_event)}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW-PENDING"),review)
        with self.assertRaisesRegex(ValueError,"record the completed Plan-Reviewer attempt outcome"):
            dsd_attempt.plan_review_target(self.run,"bootstrap",review)

    def test_plan_review_recovery_uses_goal_history_if_reviewer_mirror_was_not_written(self):
        brief=self.run/"goal-review-recovery.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-RECOVER-REVIEW"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None; dsd_task.command_register_direct(a)
        first=dsd_task.task_root(self.run,"bootstrap","GOAL-RECOVER-REVIEW")/"attempts"/"goal-planner-1"; (first/"plan").mkdir(parents=True); (first/"report.md").write_text("v1\n"); (first/"plan"/"PLAN.md").write_text("# v1\n")
        second=dsd_task.task_root(self.run,"bootstrap","GOAL-RECOVER-REVIEW")/"attempts"/"goal-planner-2"; (second/"plan").mkdir(parents=True); (second/"report.md").write_text("v2\n"); plan2=second/"plan"/"PLAN.md"; plan2.write_text("# v2\n")
        rev_event=dsd_task.task_root(self.run,"bootstrap","REVIEW-RECOVER-REVIEW")/"attempts"/"plan-reviewer-1"
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL-RECOVER-REVIEW"); goal["attempts"]=[{"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(first)},{"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(second)}]; goal["status"]="active"; goal["plan_review_history"]=[{"outcome":"fail","planner_attempt":str(first.resolve()),"reviewer_attempt":str(rev_event)}]; goal["last_plan_review"]=goal["plan_review_history"][-1]; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-RECOVER-REVIEW"),goal)
        rb=self.run/"review-recovery.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-RECOVER-REVIEW"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-RECOVER-REVIEW"; dsd_task.command_register_direct(r)
        rev_event.mkdir(parents=True); (rev_event/"report.md").write_text("FAIL\n")
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-RECOVER-REVIEW"); review["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev_event)}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW-RECOVER-REVIEW"),review)
        target=dsd_attempt.plan_review_target(self.run,"bootstrap",review)
        self.assertEqual(Path(target["attempt"]).resolve(),second.resolve()); self.assertEqual(Path(target["plan"]).resolve(),plan2.resolve())

    def test_same_goal_planner_attempt_cannot_be_review_shopped_after_fail(self):
        brief=self.run/"goal-reviewed-once.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-ONCE"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None; dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL-ONCE")/"attempts"/"goal-planner-1"; (event/"plan").mkdir(parents=True); (event/"report.md").write_text("planned\n"); (event/"plan"/"PLAN.md").write_text("# plan\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL-ONCE"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event)}); goal["status"]="planned"; goal["last_plan_review"]={"outcome":"fail","planner_attempt":str(event.resolve())}; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL-ONCE"),goal)
        rb=self.run/"review-once.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-ONCE"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-ONCE"; dsd_task.command_register_direct(r)
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-ONCE")
        with self.assertRaisesRegex(ValueError,"already has Plan-Reviewer outcome 'fail'"):
            dsd_attempt.plan_review_target(self.run,"bootstrap",review)

    def test_plan_reviewer_task_cannot_be_accepted(self):
        brief=self.run/"goal-for-review-accept.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL-RA"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None; dsd_task.command_register_direct(a)
        rb=self.run/"review-accept.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW-RA"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL-RA"; dsd_task.command_register_direct(r)
        event=dsd_task.task_root(self.run,"bootstrap","REVIEW-RA")/"attempts"/"plan-reviewer-1"; event.mkdir(parents=True); report=event/"report.md"; report.write_text("PASS\n")
        review=dsd_task.load_task(self.run,"bootstrap","REVIEW-RA"); review["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(event)}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW-RA"),review)
        ac=A(); ac.run_root=self.run; ac.phase_id="bootstrap"; ac.task_id="REVIEW-RA"; ac.report=report
        with self.assertRaisesRegex(ValueError,"do not accept the task itself"):
            dsd_task.command_accept(ac)

    def test_plan_reviewer_receives_exact_goal_inputs_and_plan(self):
        brief=self.run/"goal-source.md"; brief.write_text("# user goal\n")
        authority=self.run/"owner-authority.md"; authority.write_text("owner constraint\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"bootstrap","GOAL")/"attempts"/"goal-planner-1"; (event/"plan").mkdir(parents=True); (event/"report.md").write_text("planned\n"); plan=event/"plan"/"PLAN.md"; plan.write_text("# plan\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(event),"inputs":[str(authority.resolve())]}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL"),goal)
        rb=self.run/"review-source.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL"
        dsd_task.command_register_direct(r)
        review_task=dsd_task.load_task(self.run,"bootstrap","REVIEW")
        inputs=[x for group in dsd_attempt.task_input_groups(self.run,"bootstrap",review_task,"plan-reviewer",[]).values() for x in group]
        self.assertIn(str(Path(goal["brief"]).resolve()),inputs); self.assertIn(str(authority.resolve()),inputs); self.assertIn(str(plan.resolve()),inputs)

    def test_stale_plan_review_cannot_approve_new_goal_planner_attempt(self):
        brief=self.run/"goal-stale.md"; brief.write_text("# goal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="bootstrap"; a.task_id="GOAL"; a.brief=brief; a.kind="analysis"; a.role="goal-planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        first=dsd_task.task_root(self.run,"bootstrap","GOAL")/"attempts"/"goal-planner-1"; (first/"plan").mkdir(parents=True); (first/"report.md").write_text("v1\n"); plan1=first/"plan"/"PLAN.md"; plan1.write_text("# v1\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(first)}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL"),goal)
        rb=self.run/"review-stale.md"; rb.write_text("# review\n")
        r=A(); r.run_root=self.run; r.phase_id="bootstrap"; r.task_id="REVIEW"; r.brief=rb; r.kind="analysis"; r.role="plan-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="GOAL"; dsd_task.command_register_direct(r)
        rev=dsd_task.task_root(self.run,"bootstrap","REVIEW")/"attempts"/"plan-reviewer-1"; rev.mkdir(parents=True); rr=rev/"report.md"; rr.write_text("PASS\n")
        snapshot=rev/"plan-under-review"/"PLAN.md"; snapshot.parent.mkdir(); snapshot.write_bytes(plan1.read_bytes())
        state=dsd_task.load_task(self.run,"bootstrap","REVIEW"); state["attempts"].append({"role":"plan-reviewer","tier":"analyst","status":"gated","event_dir":str(rev),"plan_review_target":{"task_id":"GOAL","attempt":str(first.resolve()),"plan":str(plan1.resolve()),"source_plan":str(plan1.resolve()),"plan_snapshot":str(snapshot.resolve())}}); state["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","REVIEW"),state)
        second=dsd_task.task_root(self.run,"bootstrap","GOAL")/"attempts"/"goal-planner-2"; (second/"plan").mkdir(parents=True); (second/"report.md").write_text("v2\n"); (second/"plan"/"PLAN.md").write_text("# v2\n")
        goal=dsd_task.load_task(self.run,"bootstrap","GOAL"); goal["attempts"].append({"role":"goal-planner","tier":"analyst","status":"gated","event_dir":str(second)}); goal["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"bootstrap","GOAL"),goal)
        pr=A(); pr.run_root=self.run; pr.phase_id="bootstrap"; pr.task_id="REVIEW"; pr.outcome="pass"; pr.report=rr
        with self.assertRaisesRegex(ValueError,"stale"):
            dsd_task.command_plan_review(pr)

    def test_case_insensitive_phase_id_collision_is_rejected(self):
        brief=self.run/"phase-case.md"; brief.write_text("# discovery\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="PhaseA"; a.task_id="D1"; a.brief=brief; a.kind="analysis"; a.role="discovery"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        a.phase_id="phasea"; a.task_id="D2"
        with self.assertRaisesRegex(ValueError,"case-insensitive"):
            dsd_task.command_register_direct(a)

    def test_case_insensitive_task_id_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"case-insensitive"):
            self.write_plan([
                {"task_id":"BuildAPI","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False},
                {"task_id":"buildapi","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False},
            ])

    def test_event_attempt_worker_pid_is_counted_even_if_monitor_record_lacks_it(self):
        event=self.run/"pid-probe"; event.mkdir(); (event/"attempt.json").write_text(json.dumps({"worker_pid":os.getpid(),"launcher_pid":99999999}))
        attempt={"event_dir":str(event),"monitor_pid":99999998}
        self.assertTrue(dsd_task.attempt_is_live(attempt))
        self.assertTrue(dsd_task.attempt_is_unresolved(attempt))

    def test_invalid_role_override_is_rejected(self):
        self.write_plan([{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        task=dsd_task.load_task(self.run,"P1","T1")
        with self.assertRaises(ValueError): dsd_attempt.validate_launch_role(task,"planner")


    def test_direct_registration_is_bootstrap_simple(self):
        brief=self.run/"bootstrap.md"; brief.write_text("# Analyze phase\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="PLAN"; a.brief=brief; a.kind="analysis"; a.role="planner"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        t=dsd_task.load_task(self.run,"P1","PLAN")
        self.assertEqual(t["role"],"planner"); self.assertEqual(Path(t["brief"]).read_text(),brief.read_text())


    def test_ordinary_task_graph_rejects_context_reviewer_control_role(self):
        with self.assertRaisesRegex(ValueError, "control-plane"):
            self.write_plan([{"task_id":"CTX","kind":"analysis","role":"context-reviewer","tier":"analyst","dependencies":[],"requires_integration":False}])

    def test_verification_role_cannot_be_promoted_to_analyst_tier(self):
        with self.assertRaisesRegex(ValueError, "Grunt tier"):
            self.write_plan([{"task_id":"VERIFY","kind":"verification","role":"verification","tier":"analyst","dependencies":[],"requires_integration":False}])

    def test_context_reviewer_is_always_fresh(self):
        task={"role":"context-reviewer","status":"active","attempts":[{"role":"context-reviewer","session_id":"s1"}]}
        with self.assertRaisesRegex(ValueError,"fresh session"):
            dsd_attempt.resolve_resume_session(task,"context-reviewer","active",None,True)
        with self.assertRaisesRegex(ValueError,"fresh session"):
            dsd_attempt.resolve_resume_session(task,"context-reviewer","active","s1",False)

    def test_context_review_pass_is_bound_to_exact_snapshot_and_stales_on_mutation(self):
        brief=self.run/"context-source.md"; brief.write_text("# discover recurring worker context\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="CTX-SOURCE"; a.brief=brief; a.kind="analysis"; a.role="discovery"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        source_event=dsd_task.task_root(self.run,"P1","CTX-SOURCE")/"attempts"/"discovery-1"; source_event.mkdir(parents=True)
        (source_event/"report.md").write_text("found recurring rule\n")
        proposal=source_event/"project-protocol"/"PROJECT-PROTOCOL.md"; proposal.parent.mkdir(); proposal.write_text("# Protocol\nUse project command X.\n")
        source=dsd_task.load_task(self.run,"P1","CTX-SOURCE"); source["attempts"].append({"role":"discovery","tier":"analyst","status":"gated","event_dir":str(source_event)}); source["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","CTX-SOURCE"),source)

        review_brief=self.run/"context-review.md"; review_brief.write_text("# review reusable context\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id="CTX-REVIEW"; r.brief=review_brief; r.kind="analysis"; r.role="context-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="CTX-SOURCE"
        dsd_task.command_register_direct(r)
        review_event=dsd_task.task_root(self.run,"P1","CTX-REVIEW")/"attempts"/"context-reviewer-1"; review_event.mkdir(parents=True)
        review_report=review_event/"report.md"; review_report.write_text("PASS\n")
        snapshot=review_event/"context-under-review"; snap_file=snapshot/"project-protocol"/"PROJECT-PROTOCOL.md"; snap_file.parent.mkdir(parents=True); snap_file.write_bytes(proposal.read_bytes())
        review=dsd_task.load_task(self.run,"P1","CTX-REVIEW"); review["attempts"].append({"role":"context-reviewer","tier":"analyst","status":"gated","event_dir":str(review_event),"context_review_target":{"task_id":"CTX-SOURCE","attempt":str(source_event.resolve()),"context_snapshot":str(snapshot.resolve())}}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","CTX-REVIEW"),review)
        cr=A(); cr.run_root=self.run; cr.phase_id="P1"; cr.task_id="CTX-REVIEW"; cr.outcome="pass"; cr.report=review_report
        out=dsd_task.command_context_review(cr); self.assertEqual(out["outcome"],"pass")
        source=dsd_task.load_task(self.run,"P1","CTX-SOURCE"); attempt=source["attempts"][-1]
        self.assertIsNotNone(dsd_task.require_context_review(source,attempt,reason="promotion"))
        proposal.write_text("# Protocol\nCHANGED after review.\n")
        with self.assertRaisesRegex(ValueError,"stale"):
            dsd_task.require_context_review(dsd_task.load_task(self.run,"P1","CTX-SOURCE"),attempt,reason="promotion")

    def test_context_review_escalation_blocks_source_and_human_decision_returns_to_source(self):
        brief=self.run/"context-source-escalate.md"; brief.write_text("# recurring context proposal\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="CTX-SOURCE-E"; a.brief=brief; a.kind="analysis"; a.role="discovery"; a.tier="analyst"; a.dependency=[]; a.requires_integration=False; a.reviews_task=None
        dsd_task.command_register_direct(a)
        source_event=dsd_task.task_root(self.run,"P1","CTX-SOURCE-E")/"attempts"/"discovery-1"; source_event.mkdir(parents=True)
        (source_event/"report.md").write_text("proposal needs owner authority\n")
        proposal=source_event/"project-protocol"/"PROJECT-PROTOCOL.md"; proposal.parent.mkdir(); proposal.write_text("# Protocol\nPotential owner-sensitive rule.\n")
        source=dsd_task.load_task(self.run,"P1","CTX-SOURCE-E"); source["attempts"].append({"role":"discovery","tier":"analyst","status":"gated","event_dir":str(source_event)}); source["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","CTX-SOURCE-E"),source)

        review_brief=self.run/"context-review-escalate.md"; review_brief.write_text("# review proposal\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id="CTX-REVIEW-E"; r.brief=review_brief; r.kind="analysis"; r.role="context-reviewer"; r.tier="analyst"; r.dependency=[]; r.requires_integration=False; r.reviews_task="CTX-SOURCE-E"
        dsd_task.command_register_direct(r)
        review_event=dsd_task.task_root(self.run,"P1","CTX-REVIEW-E")/"attempts"/"context-reviewer-1"; review_event.mkdir(parents=True)
        review_report=review_event/"report.md"; review_report.write_text("ESCALATE: owner must decide whether this rule is authoritative.\n")
        snapshot=review_event/"context-under-review"; snap_file=snapshot/"project-protocol"/"PROJECT-PROTOCOL.md"; snap_file.parent.mkdir(parents=True); snap_file.write_bytes(proposal.read_bytes())
        review=dsd_task.load_task(self.run,"P1","CTX-REVIEW-E"); review["attempts"].append({"role":"context-reviewer","tier":"analyst","status":"gated","event_dir":str(review_event),"context_review_target":{"task_id":"CTX-SOURCE-E","attempt":str(source_event.resolve()),"context_snapshot":str(snapshot.resolve())}}); review["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","CTX-REVIEW-E"),review)
        cr=A(); cr.run_root=self.run; cr.phase_id="P1"; cr.task_id="CTX-REVIEW-E"; cr.outcome="escalate"; cr.report=review_report
        out=dsd_task.command_context_review(cr); self.assertEqual(out["escalation_target"],"human")
        source=dsd_task.load_task(self.run,"P1","CTX-SOURCE-E"); self.assertEqual(source["status"],"blocked"); self.assertEqual(source["last_escalation"]["source"],"context-review")
        self.assertEqual(dsd_task.load_task(self.run,"P1","CTX-REVIEW-E")["status"],"active")

        decision=self.run/"owner-context-decision.md"; decision.write_text("Revise the proposal to make this advisory only.\n")
        cr.task_id="CTX-SOURCE-E"; cr.decision=decision; cr.route="resume"
        resolved=dsd_task.command_resolve_escalation(cr); self.assertEqual(resolved["status"],"planned")
        source=dsd_task.load_task(self.run,"P1","CTX-SOURCE-E")
        self.assertTrue(Path(source["last_human_decision"]["path"]).is_file())

    def test_recorded_reusable_review_conduits_do_not_remain_actionable(self):
        for role,field in (("plan-reviewer","last_plan_review"),("context-reviewer","last_context_review")):
            with self.subTest(role=role):
                event=dsd_task.task_root(self.run,"P1",f"REC-{role}")/"attempts"/f"{role}-1"; event.mkdir(parents=True,exist_ok=True)
                task={"task_id":f"REC-{role}","status":"active","role":role,"attempts":[{"role":role,"status":"gated","event_dir":str(event)}],field:{"reviewer_attempt":str(event)}}
                self.assertIsNone(dsd_task._reconcile_action(self.run,"P1",task))

    def test_swept_stale_attempt_is_no_longer_unresolved_or_reflipped(self):
        self.write_plan([{"task_id":"T-STALE","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        event=dsd_task.task_root(self.run,"P1","T-STALE")/"attempts"/"implementer-1"; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,"P1","T-STALE")
        task["attempts"].append({"task_id":"T-STALE","role":"implementer","tier":"grunt","status":"started","event_dir":str(event),"monitor_pid":99999999})
        task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-STALE"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        first=dsd_task.command_sweep_stale(a); self.assertEqual(first["count"],1)
        task=dsd_task.load_task(self.run,"P1","T-STALE")
        self.assertEqual(task["attempts"][-1]["status"],"stale-unresolved")
        self.assertFalse(dsd_task.task_has_unresolved_attempt(task))
        task["status"]="planned"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-STALE"),task)
        second=dsd_task.command_sweep_stale(a); self.assertEqual(second["count"],0)
        self.assertEqual(dsd_task.load_task(self.run,"P1","T-STALE")["status"],"planned")

    def test_dependency_follows_superseded_successor_chain(self):
        self.write_plan([{"task_id":"OLD","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        self.write_plan([{"task_id":"NEW","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"supersedes":["OLD"]}])
        new=dsd_task.load_task(self.run,"P1","NEW"); new["status"]="integrated"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","NEW"),new)
        self.write_plan([{"task_id":"DEP","kind":"analysis","role":"discovery","tier":"analyst","dependencies":["OLD"],"requires_integration":False}])
        dep=dsd_task.load_task(self.run,"P1","DEP"); ready,missing=dsd_task.readiness(self.run,"P1",dep)
        self.assertTrue(ready); self.assertEqual(missing,[])

    def test_superseded_dependency_without_successor_stays_unsatisfied(self):
        self.write_plan([{"task_id":"OLD-DROPPED","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        old=dsd_task.load_task(self.run,"P1","OLD-DROPPED"); old["status"]="superseded"; old.pop("superseded_by",None); dsd_task.write_json(dsd_task.task_file(self.run,"P1","OLD-DROPPED"),old)
        self.write_plan([{"task_id":"DEP-DROPPED","kind":"analysis","role":"discovery","tier":"analyst","dependencies":["OLD-DROPPED"],"requires_integration":False}])
        dep=dsd_task.load_task(self.run,"P1","DEP-DROPPED"); ready,missing=dsd_task.readiness(self.run,"P1",dep)
        self.assertFalse(ready); self.assertEqual(missing,["OLD-DROPPED"])


    def test_verification_blocked_stays_red_and_does_not_release_dependents(self):
        self.write_plan([
            {"task_id":"V1","kind":"verification","role":"verification","tier":"grunt","dependencies":[],"requires_integration":False},
            {"task_id":"T-AFTER-V","kind":"implementation","role":"implementer","tier":"grunt","dependencies":["V1"]},
        ])
        event=dsd_task.task_root(self.run,"P1","V1")/"attempts"/"verification-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("BLOCKED\nThe required production predicate is not yet established.\n")
        task=dsd_task.load_task(self.run,"P1","V1"); task["attempts"].append({"task_id":"V1","role":"verification","tier":"grunt","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","V1"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="V1"; a.report=report
        out=dsd_task.command_verification_result(a)
        self.assertEqual(out["outcome"],"blocked"); self.assertEqual(out["status"],"needs-analysis")
        self.assertFalse(dsd_task.dependency_satisfied(self.run,"P1","V1"))
        downstream=dsd_task.load_task(self.run,"P1","T-AFTER-V"); self.assertEqual(dsd_task.readiness(self.run,"P1",downstream),(False,["V1"]))

    def test_capability_ladder_strengthens_runtime_without_widening_authority(self):
        class A: pass
        for name,driver,model in (("deep","claude","claude-opus-5"),("frontier","codex","astra-high")):
            a=A(); a.run_root=self.run; a.tier="analyst"; a.name=name; a.driver=driver; a.model=model; a.max_uses=None
            dsd_task.command_set_runtime_profile(a)
        self.write_plan([{"task_id":"AN-DEEP","kind":"analysis","role":"discovery","tier":"analyst","dependencies":[],"requires_integration":False}])
        event=dsd_task.task_root(self.run,"P1","AN-DEEP")/"attempts"/"discovery-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("ESCALATE CAPABILITY\nThe authority is sufficient, but this runtime cannot safely finish the diagnosis.\n")
        task=dsd_task.load_task(self.run,"P1","AN-DEEP"); task["attempts"].append({"task_id":"AN-DEEP","role":"discovery","tier":"analyst","driver":"opencode","model":"analyst/model","runtime_profile":"default","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","AN-DEEP"),task)
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="AN-DEEP"; a.report=report
        out=dsd_task.command_capability_escalate(a); self.assertEqual(out["route"],"same-authority-stronger-runtime"); self.assertEqual(out["to_profile"],"deep")
        routed=dsd_task.load_task(self.run,"P1","AN-DEEP"); self.assertEqual(routed["role"],"discovery"); self.assertEqual(routed["tier"],"analyst"); self.assertEqual(routed["pending_runtime_profile"],"deep")


    def test_capability_ladder_does_not_wrap_backward_when_current_one_shot_is_consumed(self):
        class A: pass
        for name,driver,model,max_uses in (("deep","claude","claude-opus-5",1),("frontier","codex","astra-high",None)):
            a=A(); a.run_root=self.run; a.tier="analyst"; a.name=name; a.driver=driver; a.model=model; a.max_uses=max_uses
            dsd_task.command_set_runtime_profile(a)
        dsd_task.consume_runtime_profile(self.run,"analyst","deep")
        info=dsd_task.load_run(self.run)
        self.assertIsNone(dsd_task.runtime_profile(info,"analyst","deep"))
        nxt=dsd_task.next_runtime_profile(info,"analyst","deep")
        self.assertIsNotNone(nxt); self.assertEqual(nxt["name"],"frontier")


    def test_phase_gate_is_fresh_bound_and_writes_legible_top_level_plan_report(self):
        self.write_plan([{"task_id":"T-GATE","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        t=dsd_task.load_task(self.run,"P1","T-GATE"); t["status"]="integrated"; t["integrated_at"]=dsd_task.now(); t["updated_at"]=t["integrated_at"]; dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-GATE"),t)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; prep=dsd_task.command_prepare_phase_gate(a); gate_id=prep["registered"][0]
        event=dsd_task.task_root(self.run,"P1",gate_id)/"attempts"/"phase-auditor-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("PASS\n## What is true now\nThe phase goal is satisfied through the integrated production path.\n")
        gate=dsd_task.load_task(self.run,"P1",gate_id); head=git(self.project,"rev-parse","HEAD"); gate["attempts"].append({"task_id":gate_id,"role":"phase-auditor","tier":"analyst","status":"gated","event_dir":str(event),"workspace_primary_head":head,"workspace_primary_status":""}); gate["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",gate_id),gate)
        (self.project/"a.txt").write_text("dirty\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id=gate_id; r.report=report
        with self.assertRaisesRegex(ValueError,"snapshot is stale"):
            dsd_task.command_phase_gate(r)
        (self.project/"a.txt").write_text("a\n")
        out=dsd_task.command_phase_gate(r); owner=Path(out["owner_gate_report"])
        self.assertEqual(owner.parent,self.run/"plan"); self.assertEqual(owner.name,"PHASE-P1-GATE-01.md"); self.assertIn("**Result:** PASS",owner.read_text()); self.assertIn("The phase goal is satisfied",owner.read_text())
        self.assertEqual(dsd_task.phase_gate_state(self.run,"P1")["reason"],"fresh-pass")

    def test_phase_gate_history_is_append_only_and_easy_to_browse(self):
        self.write_plan([{"task_id":"T-GATE-HIST","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        t=dsd_task.load_task(self.run,"P1","T-GATE-HIST"); t["status"]="integrated"; t["updated_at"]=dsd_task.now(); dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-GATE-HIST"),t)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; first=dsd_task.command_prepare_phase_gate(a); first_id=first["registered"][0]
        e1=dsd_task.task_root(self.run,"P1",first_id)/"attempts"/"phase-auditor-1"; e1.mkdir(parents=True); r1=e1/"report.md"; r1.write_text("BLOCKED\nA cross-task persistence seam is still unproven.\n")
        g1=dsd_task.load_task(self.run,"P1",first_id); g1["attempts"].append({"task_id":first_id,"role":"phase-auditor","tier":"analyst","status":"gated","event_dir":str(e1),"workspace_primary_head":git(self.project,"rev-parse","HEAD"),"workspace_primary_status":""}); g1["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",first_id),g1)
        q=A(); q.run_root=self.run; q.phase_id="P1"; q.task_id=first_id; q.report=r1; out1=dsd_task.command_phase_gate(q); self.assertEqual(out1["outcome"],"blocked")
        rr=A(); rr.run_root=self.run; rr.phase_id="P1"; rr.no_sweep=True; rr.details=False
        routed=dsd_task.command_reconcile_run(rr); self.assertTrue(any(x.get("action")=="launch-analyst-discovery" and x.get("task_id")==first_id for x in routed.get("first_useful_actions",[])))
        # Corrective replanning consumes the old gate task; the historical red report stays.
        g1=dsd_task.load_task(self.run,"P1",first_id); g1["status"]="accepted"; g1["updated_at"]=dsd_task.now(); dsd_task.write_json(dsd_task.task_file(self.run,"P1",first_id),g1)
        second=dsd_task.command_prepare_phase_gate(a); second_id=second["registered"][0]; self.assertEqual(second_id,"PHASE-GATE-02")
        e2=dsd_task.task_root(self.run,"P1",second_id)/"attempts"/"phase-auditor-1"; e2.mkdir(parents=True); r2=e2/"report.md"; r2.write_text("PASS\nThe corrective work closes the persistence seam and the phase goal is now proven.\n")
        g2=dsd_task.load_task(self.run,"P1",second_id); g2["attempts"].append({"task_id":second_id,"role":"phase-auditor","tier":"analyst","status":"gated","event_dir":str(e2),"workspace_primary_head":git(self.project,"rev-parse","HEAD"),"workspace_primary_status":""}); g2["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",second_id),g2)
        q.task_id=second_id; q.report=r2; out2=dsd_task.command_phase_gate(q); self.assertEqual(out2["outcome"],"pass")
        reports=sorted((self.run/"plan").glob("PHASE-P1-GATE-*.md")); self.assertEqual([x.name for x in reports],["PHASE-P1-GATE-01.md","PHASE-P1-GATE-02.md"]); self.assertIn("BLOCKED",reports[0].read_text()); self.assertIn("PASS",reports[1].read_text())

    def test_advance_prepares_phase_gate_then_stops_at_fresh_auditor_launch(self):
        self.write_plan([{"task_id":"T-GATE-ADV","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        t=dsd_task.load_task(self.run,"P1","T-GATE-ADV"); t["status"]="integrated"; t["updated_at"]=dsd_task.now(); dsd_task.write_json(dsd_task.task_file(self.run,"P1","T-GATE-ADV"),t)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.max_steps=4
        out=dsd_task.command_advance(a)
        self.assertEqual(out["applied"][0]["action"],"prepare-phase-gate")
        self.assertEqual(out["stopped"],"semantic-or-launch-boundary")
        self.assertEqual(out["next_action"]["action"],"launch-ready-task")
        gate=dsd_task.load_task(self.run,"P1",out["next_action"]["task_id"]); self.assertEqual(gate["role"],"phase-auditor")

    def test_advance_records_exact_verification_then_stops_before_worker_launch(self):
        self.write_plan([
            {"task_id":"V-ADV","kind":"verification","role":"verification","tier":"grunt","dependencies":[],"requires_integration":False},
            {"task_id":"T-ADV","kind":"implementation","role":"implementer","tier":"grunt","dependencies":["V-ADV"]},
        ])
        event=dsd_task.task_root(self.run,"P1","V-ADV")/"attempts"/"verification-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("PASS\nThe predicate is established.\n"); (event/"terminal.json").write_text("{}\n")
        v=dsd_task.load_task(self.run,"P1","V-ADV"); v["attempts"].append({"task_id":"V-ADV","role":"verification","tier":"grunt","status":"gated","event_dir":str(event)}); v["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1","V-ADV"),v)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.max_steps=4
        out=dsd_task.command_advance(a); self.assertEqual(out["applied"][0]["action"],"record-verification-result"); self.assertEqual(out["stopped"],"semantic-or-launch-boundary"); self.assertEqual(out["next_action"]["action"],"launch-ready-task")
        self.assertEqual(dsd_task.load_task(self.run,"P1","T-ADV").get("attempts"),[])

    def _integrated_task_with_followup(self, source="T-FOLLOW", dependent="T-DOWN"):
        self.write_plan([
            {"task_id":source,"kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
            {"task_id":dependent,"kind":"implementation","role":"implementer","tier":"grunt","dependencies":[source]},
        ])
        report=self.gated_review_report(source,text="PASS\n\n## Follow-up obligations\n- Production cutover wiring required by downstream work is still absent.\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id=source; a.report=report; a.outcome="pass"
        out=dsd_task.command_review(a); self.assertEqual(len(out["followup_findings"]),1)
        a.report=report; dsd_task.command_accept(a); dsd_task.command_integrated(a)
        return out["followup_findings"][0],report

    def test_review_followup_is_durable_and_blocks_new_phase_launches(self):
        finding_id,_=self._integrated_task_with_followup()
        source=dsd_task.load_task(self.run,"P1","T-FOLLOW")
        finding=source["review_history"][-1]["findings"][0]
        self.assertEqual(finding["finding_id"],finding_id); self.assertEqual(finding["status"],"open")
        self.assertFalse(dsd_task.dependency_satisfied(self.run,"P1","T-FOLLOW"))
        down=dsd_task.load_task(self.run,"P1","T-DOWN"); ok,missing=dsd_task.readiness(self.run,"P1",down)
        self.assertFalse(ok); self.assertIn("review-followup-triage",missing)
        self.assertEqual(dsd_task.phase_gate_state(self.run,"P1")["reason"],"phase-work-incomplete")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.max_steps=4
        advanced=dsd_task.command_advance(a)
        self.assertEqual(advanced["applied"][0]["action"],"prepare-followup-triage")
        self.assertEqual(advanced["stopped"],"semantic-or-launch-boundary")
        triage=dsd_task.load_task(self.run,"P1",advanced["next_action"]["task_id"])
        self.assertEqual(triage["role"],"planner"); self.assertEqual(triage["followup_finding_ids"],[finding_id])

    def test_followup_triage_can_run_alongside_source_fixer_without_releasing_other_phase_work(self):
        self.write_plan([
            {"task_id":"T-FAIL-SRC","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
            {"task_id":"T-INDEPENDENT","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]},
        ])
        report=self.gated_review_report("T-FAIL-SRC",text="FAIL\nThe assigned change has an in-scope defect.\n\n## Follow-up obligations\n- A separate production cutover seam must be reconciled with the phase plan.\n")
        (report.parent/"terminal.json").write_text("{}\n")
        class A: pass
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id="T-FAIL-SRC"; r.report=report; r.outcome="fail"
        dsd_task.command_review(r)
        adv=A(); adv.run_root=self.run; adv.phase_id="P1"; adv.max_steps=3
        out=dsd_task.command_advance(adv); self.assertEqual(out["applied"][0]["action"],"prepare-followup-triage")
        probe=A(); probe.run_root=self.run; probe.phase_id="P1"; probe.no_sweep=True; probe.details=True
        state=dsd_task.command_reconcile_run(probe); actions=state["actions"]
        self.assertTrue(any(x.get("action")=="launch-fixer" and x.get("task_id")=="T-FAIL-SRC" for x in actions))
        self.assertTrue(any(x.get("action")=="launch-ready-task" and str(x.get("task_id") or "").startswith("FOLLOWUP-TRIAGE-") for x in actions))
        independent=next(x for x in actions if x.get("task_id")=="T-INDEPENDENT")
        self.assertEqual(independent["action"],"waiting-dependencies"); self.assertIn("review-followup-triage",independent["blocked_by"])

    def test_followup_triage_resume_resolves_obligation_and_unblocks_plan(self):
        finding_id,_=self._integrated_task_with_followup(source="T-RESUME",dependent="T-AFTER")
        class A: pass
        prep=A(); prep.run_root=self.run; prep.phase_id="P1"; prep.task_id="T-RESUME"
        triage_id=dsd_task.command_prepare_followup_triage(prep)["triage_task"]
        report=self.gated_analysis_report(triage_id,role="planner",text="The existing downstream brief already owns the cutover wiring and remains sufficient.\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id=triage_id; r.report=report; r.outcome="resume"
        out=dsd_task.command_analysis_result(r); self.assertEqual(out["triaged_findings"],[finding_id])
        source=dsd_task.load_task(self.run,"P1","T-RESUME"); finding=source["review_history"][-1]["findings"][0]
        self.assertEqual(finding["status"],"triaged"); self.assertEqual(finding["resolution"],"analyst-resume")
        self.assertTrue(dsd_task.dependency_satisfied(self.run,"P1","T-RESUME"))
        self.assertTrue(dsd_task.readiness(self.run,"P1",dsd_task.load_task(self.run,"P1","T-AFTER"))[0])

    def test_human_can_explicitly_cancel_escalated_followup_obligation(self):
        finding_id,_=self._integrated_task_with_followup(source="T-CANCEL",dependent="T-CANCEL-DOWN")
        class A: pass
        prep=A(); prep.run_root=self.run; prep.phase_id="P1"; prep.task_id="T-CANCEL"
        triage_id=dsd_task.command_prepare_followup_triage(prep)["triage_task"]
        report=self.gated_analysis_report(triage_id,role="planner",text="This obligation may no longer be required; only the owner can cancel it.\n")
        ar=A(); ar.run_root=self.run; ar.phase_id="P1"; ar.task_id=triage_id; ar.report=report; ar.outcome="escalate"
        out=dsd_task.command_analysis_result(ar); self.assertEqual(out["status"],"blocked")
        decision=self.run/"cancel-followup.md"; decision.write_text("Cancel this follow-up obligation for the current phase.\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id=triage_id; r.decision=decision; r.route="accept"
        resolved=dsd_task.command_resolve_escalation(r); self.assertEqual(resolved["cancelled_findings"],[finding_id])
        source=dsd_task.load_task(self.run,"P1","T-CANCEL"); finding=source["review_history"][-1]["findings"][0]
        self.assertEqual(finding["status"],"cancelled"); self.assertEqual(finding["resolution"],"human-cancelled")
        self.assertTrue(Path(finding["resolution_decision"]).is_file())
        self.assertTrue(dsd_task.readiness(self.run,"P1",dsd_task.load_task(self.run,"P1","T-CANCEL-DOWN"))[0])

    def test_followup_replan_uses_bound_finding_set_and_replaces_stale_brief(self):
        finding_id,_=self._integrated_task_with_followup(source="T-UP",dependent="T-STALE-DOWN")
        class A: pass
        prep=A(); prep.run_root=self.run; prep.phase_id="P1"; prep.task_id="T-UP"
        triage_id=dsd_task.command_prepare_followup_triage(prep)["triage_task"]
        event=dsd_task.task_root(self.run,"P1",triage_id)/"attempts"/"planner-1"; tasks=event/"plan"/"tasks"; tasks.mkdir(parents=True)
        report=event/"report.md"; report.write_text("The frozen downstream brief is no longer executable; replace it.\n")
        (tasks/"T-FIXED-DOWN.md").write_text("# Fixed downstream\n\n## Objective\nCarry the newly discovered production cutover wiring through live acceptance.\n")
        graph=event/"plan"/"task-graph.json"
        graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"T-FIXED-DOWN","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/T-FIXED-DOWN.md","dependencies":["T-UP"],"supersedes":["T-STALE-DOWN"]}]}))
        triage=dsd_task.load_task(self.run,"P1",triage_id); triage["attempts"].append({"task_id":triage_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)}); triage["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P1",triage_id),triage)
        pf=A(); pf.run_root=self.run; pf.phase_id="P1"; pf.plan=graph
        self.assertTrue(dsd_task.command_preflight_plan(pf)["valid"])
        ar=A(); ar.run_root=self.run; ar.phase_id="P1"; ar.task_id=triage_id; ar.report=report; ar.outcome="replan"
        dsd_task.command_analysis_result(ar)
        reg=dsd_task.command_register_plan(pf); self.assertIn("T-FIXED-DOWN",reg["registered"])
        source=dsd_task.load_task(self.run,"P1","T-UP"); finding=source["review_history"][-1]["findings"][0]
        self.assertEqual(finding["finding_id"],finding_id); self.assertEqual(finding["status"],"triaged"); self.assertEqual(finding["resolution"],"analyst-replan")
        self.assertEqual(dsd_task.load_task(self.run,"P1","T-STALE-DOWN")["status"],"superseded")
        self.assertTrue(dsd_task.readiness(self.run,"P1",dsd_task.load_task(self.run,"P1","T-FIXED-DOWN"))[0])

    def test_followup_section_is_structural_not_freeform_prose_parser(self):
        self.write_plan([{"task_id":"T-BAD-FOLLOW","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}])
        report=self.gated_review_report("T-BAD-FOLLOW",text="PASS\n\n## Follow-up obligations\nThis prose is not a machine bullet.\n")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T-BAD-FOLLOW"; a.report=report; a.outcome="pass"
        with self.assertRaisesRegex(ValueError,"single-line"):
            dsd_task.command_review(a)

    def test_phase_gate_dossier_keeps_review_followup_and_analyst_resolution_visible(self):
        finding_id,_=self._integrated_task_with_followup(source="T-DOSSIER",dependent="T-DOSSIER-DOWN")
        class A: pass
        prep=A(); prep.run_root=self.run; prep.phase_id="P1"; prep.task_id="T-DOSSIER"
        triage_id=dsd_task.command_prepare_followup_triage(prep)["triage_task"]
        report=self.gated_analysis_report(triage_id,role="planner",text="Current phase plan already covers this obligation.\n")
        r=A(); r.run_root=self.run; r.phase_id="P1"; r.task_id=triage_id; r.report=report; r.outcome="resume"
        dsd_task.command_analysis_result(r)
        dossier=dsd_task.phase_gate_dossier_text(self.run,"P1")
        self.assertIn(finding_id,dossier); self.assertIn("analyst-resume",dossier); self.assertIn("cutover wiring",dossier)

    def test_followup_finding_ownership_is_bound_to_triage_task_not_plan_metadata(self):
        finding_id,_=self._integrated_task_with_followup(source="T-BOUND",dependent="T-BOUND-DOWN")
        class A: pass
        prep=A(); prep.run_root=self.run; prep.phase_id="P1"; prep.task_id="T-BOUND"
        triage_id=dsd_task.command_prepare_followup_triage(prep)["triage_task"]
        triage=dsd_task.load_task(self.run,"P1",triage_id)
        self.assertEqual(triage["followup_finding_ids"],[finding_id])
        source=dsd_task.load_task(self.run,"P1","T-BOUND")
        self.assertEqual(source["review_history"][-1]["findings"][0]["status"],"open")
        self.assertFalse(dsd_task.readiness(self.run,"P1",dsd_task.load_task(self.run,"P1","T-BOUND-DOWN"))[0])

    def test_owner_status_surfaces_open_review_followups_without_dumping_reports(self):
        finding_id,_=self._integrated_task_with_followup(source="T-OWNER-FOLLOW",dependent="T-OWNER-DOWN")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_owner_status(a); packet=out["open_review_followups"]
        self.assertEqual(packet["count"],1); self.assertEqual(packet["preview"][0]["finding_id"],finding_id)
        self.assertIn("cutover wiring",packet["preview"][0]["finding"])

    def test_owner_status_is_bounded_but_keeps_complete_backlog_counts(self):
        self.write_plan([
            {"task_id":f"T-STATUS-{i:02d}","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[]}
            for i in range(15)
        ])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_owner_status(a)
        self.assertEqual(out["backlog_count"],15); self.assertEqual(len(out["backlog_preview"]),12); self.assertTrue(out["backlog_preview_truncated"])
        self.assertEqual(sum(out["backlog_by_state"].values()),15)

    def test_owner_status_supplies_plain_language_purpose_before_internal_id(self):
        self.write_plan([{"task_id":"T-OWNER","kind":"implementation","role":"implementer","tier":"grunt","dependencies":[],"text":"# Boot cache writer\n\n## Objective\nMake startup reuse the persisted boot cache instead of recomputing it.\n"}])
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P1"
        out=dsd_task.command_owner_status(a); item=next(x for x in out["backlog_preview"] if x["task_id"]=="T-OWNER")
        self.assertIn("startup reuse the persisted boot cache",item["purpose"])



if __name__ == "__main__": unittest.main()

class RuntimeBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.project=self.root/'project'; self.project.mkdir(); git(self.project,'init','-q'); git(self.project,'config','user.email','t@example.com'); git(self.project,'config','user.name','T'); (self.project/'x').write_text('x'); git(self.project,'add','.'); git(self.project,'commit','-qm','init'); self.run=self.project/'TBag'/'runs'/'r'
    def tearDown(self): self.tmp.cleanup()
    def args(self):
        class A: pass
        a=A(); a.project_root=self.project; a.run_root=self.run; a.run_id='r'; a.runtime_root=str(self.root/'runtime'); a.max_workers=4; a.grunt_driver=None; a.grunt_model=None; a.analyst_driver=None; a.analyst_model=None; return a
    def test_new_run_has_no_silent_worker_defaults(self):
        out=dsd_task.command_init(self.args()); self.assertEqual(out['missing_runtime_config'],['analyst','grunt']); info=dsd_task.load_run(self.run); self.assertIsNone(info['worker_runtimes']['analyst']); self.assertIsNone(info['worker_runtimes']['grunt']); self.assertTrue(info['escalation_enabled'])
    def test_new_run_refuses_to_claim_nonempty_unowned_runtime_root(self):
        a=self.args(); runtime=Path(a.runtime_root); runtime.mkdir(); (runtime/'foreign.txt').write_text('foreign\n')
        with self.assertRaisesRegex(ValueError,'no T-BAG ownership marker'): dsd_task.command_init(a)
    def test_idempotent_init_backfills_runtime_owner_marker_for_upgraded_canonical_run(self):
        a=self.args(); a.runtime_root=None; dsd_task.command_init(a); info=dsd_task.load_run(self.run); marker=Path(info['runtime_root'])/'.tbag-run-owner.json'; marker.unlink()
        out=dsd_task.command_init(a); self.assertEqual(out['run_id'],'r'); owner=dsd_task.load_json(marker); self.assertEqual(owner['run_root'],str(self.run.resolve())); self.assertEqual(owner['project_root'],str(self.project.resolve())); self.assertEqual(owner['run_id'],'r')
    def test_idempotent_init_does_not_claim_legacy_custom_runtime(self):
        a=self.args(); dsd_task.command_init(a); info=dsd_task.load_run(self.run); marker=Path(info['runtime_root'])/'.tbag-run-owner.json'; marker.unlink()
        out=dsd_task.command_init(a); self.assertEqual(out['run_id'],'r'); self.assertFalse(marker.exists())
    def test_partial_runtime_reports_only_missing_tier(self):
        a=self.args(); a.analyst_driver='opencode'; a.analyst_model='strong'; out=dsd_task.command_init(a); self.assertEqual(out['missing_runtime_config'],['grunt'])
        class R: pass
        r=R(); r.run_root=self.run; status=dsd_task.command_runtime_status(r); self.assertEqual(status['missing_runtime_config'],['grunt']); self.assertEqual(status['worker_runtimes']['analyst']['model'],'strong')
    def test_set_runtime_records_driver_and_model_without_fallback(self):
        dsd_task.command_init(self.args())
        class R: pass
        r=R(); r.run_root=self.run; r.tier='grunt'; r.driver='opencode'; r.model='cheap'; r.allow_unwired_driver=False; out=dsd_task.command_set_runtime(r); self.assertEqual(out['runtime'],{'driver':'opencode','model':'cheap','options':{}}); self.assertEqual(out['missing_runtime_config'],['analyst'])
    def test_unwired_worker_driver_fails_loudly(self):
        dsd_task.command_init(self.args())
        class R: pass
        r=R(); r.run_root=self.run; r.tier='analyst'; r.driver='command-code'; r.model='strong'; r.allow_unwired_driver=False
        with self.assertRaises(ValueError): dsd_task.command_set_runtime(r)
    def test_escalation_toggle_and_terminal_run_status_are_durable(self):
        dsd_task.command_init(self.args())
        class R: pass
        r=R(); r.run_root=self.run; r.mode='off'; self.assertFalse(dsd_task.command_set_escalation(r)['escalation_enabled'])
        self.assertFalse(dsd_task.command_runtime_status(r)['escalation_enabled'])
        r.status='paused-by-user'; r.reason='owner requested pause'; out=dsd_task.command_set_run_status(r)
        self.assertEqual(out['status'],'paused-by-user'); self.assertEqual(dsd_task.load_run(self.run)['status_reason'],r.reason)
        r.status='active'; r.reason=None; dsd_task.command_set_run_status(r); self.assertEqual(dsd_task.load_run(self.run)['status'],'active')
