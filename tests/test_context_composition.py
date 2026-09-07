import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _contract import allowed_source_changes, has_explicit_write_restriction, worker_skill_tags
from _rules_snapshot import verify_snapshot
import dsd_attempt


class ContextCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.run = self.project / "TBag" / "runs" / "r1"
        self.run.mkdir(parents=True)
        self.plan = self.project / "PLAN.md"
        self.plan.write_text("# authority\n")

    def tearDown(self):
        self.tmp.cleanup()

    def prepare(self, *extra, revision=1):
        cp = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "prepare_worker_rules.py"),
                "--project-root",
                str(self.project.resolve()),
                "--run-root",
                str(self.run.resolve()),
                "--skill-root",
                str(ROOT.resolve()),
                "--plan",
                str(self.plan.resolve()),
                "--revision",
                str(revision),
                *map(str, extra),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        return self.run / "worker-rules" / f"r{revision:04d}" / "WORKER_RULES.md"

    def render(self, rules: Path, brief_text: str, role: str = "implementer", extra_args: list[str] | None = None):
        brief = self.run / "brief.md"
        brief.write_text(brief_text)
        report = self.run / "report.md"
        out = self.run / f"prompt-{role}.txt"
        if out.exists(): out.unlink()
        cp = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "render_worker_prompt.py"),
                "--role",
                role,
                "--task-id",
                "T1",
                "--run-root",
                str(self.run.resolve()),
                "--worker-rules",
                str(rules.resolve()),
                "--task",
                str(brief.resolve()),
                "--report",
                str(report.resolve()),
                "--output",
                str(out.resolve()),
                *(extra_args or []),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        return cp, out

    def mark_context_review_pass(self, attempt: Path):
        snapshot = self.run / "context-review-fixtures" / attempt.parent.parent.name / attempt.name
        if snapshot.exists(): shutil.rmtree(snapshot)
        for rel in (Path("project-protocol/PROJECT-PROTOCOL.md"),):
            source=attempt/rel
            if source.is_file() and not source.is_symlink():
                dest=snapshot/rel; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,dest)
        skills=attempt/"worker-skills"
        if skills.is_dir() and not skills.is_symlink():
            for source in skills.rglob("*"):
                if source.is_file() and not source.is_symlink():
                    dest=snapshot/source.relative_to(attempt); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(source,dest)
        report=snapshot.parent/(snapshot.name+"-review.md"); report.parent.mkdir(parents=True,exist_ok=True); report.write_text("PASS context review\n")
        task_state=attempt.parents[1]/"task.json"; data=json.loads(task_state.read_text())
        data["last_context_review"]={"outcome":"pass","source_attempt":str(attempt.resolve()),"context_snapshot":str(snapshot.resolve()),"report":str(report.resolve())}
        task_state.write_text(json.dumps(data))

    def test_initial_rules_can_exist_without_authoritative_plan_for_goal_bootstrap(self):
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "1"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        rules = self.run / "worker-rules" / "r0001" / "WORKER_RULES.md"
        info = verify_snapshot(rules)
        self.assertIsNone(info["authority_plan"])
        self.assertIn("goal-only bootstrap", rules.read_text())

    def test_plan_can_be_added_after_goal_only_bootstrap_and_then_inherited(self):
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "1"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r2 = self.prepare(revision=2)
        self.assertEqual(Path(verify_snapshot(r2)["authority_plan"]).read_text(), self.plan.read_text())
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "3"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r3 = self.run / "worker-rules" / "r0003" / "WORKER_RULES.md"
        self.assertEqual(Path(verify_snapshot(r3)["authority_plan"]).read_text(), self.plan.read_text())

    def test_worker_rules_do_not_disclose_primary_checkout_as_project_source(self):
        rules=self.prepare()
        text=rules.read_text()
        self.assertNotIn(f"Project root: `{self.project.resolve()}`",text)
        self.assertNotIn("Project source boundary",text)
        self.assertIn("COMMON.md holds universal worker rules",text)
        self.assertIn("QUALITY.md holds shared technical method",text)

    def test_planless_rules_hard_gate_normal_execution_roles(self):
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "1"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode,0,cp.stderr)
        rules=self.run/"worker-rules"/"r0001"/"WORKER_RULES.md"
        with self.assertRaisesRegex(ValueError,"NO_ACCEPTED_PLAN"):
            dsd_attempt.validate_plan_authority_for_launch(rules,"P1","planner")
        dsd_attempt.validate_plan_authority_for_launch(rules,"bootstrap","goal-planner")
        dsd_attempt.validate_plan_authority_for_launch(rules,"bootstrap","plan-reviewer")
        dsd_attempt.validate_plan_authority_for_launch(rules,"bootstrap","context-reviewer")

    def test_planless_rules_allow_only_frozen_direct_owner_authorized_task_local_execution(self):
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "1"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode,0,cp.stderr)
        rules=self.run/"worker-rules"/"r0001"/"WORKER_RULES.md"
        authority=self.run/"owner-direct.md"; authority.write_text("Human directs one bounded implementation.\n")
        dsd_attempt.validate_plan_authority_for_launch(rules,"P1","implementer",{"direct_owner_authority":str(authority)})
        authority.unlink()
        with self.assertRaisesRegex(ValueError,"NO_ACCEPTED_PLAN"):
            dsd_attempt.validate_plan_authority_for_launch(rules,"P1","implementer",{"direct_owner_authority":str(authority)})

    def test_internal_goal_plan_cannot_become_authority_before_review_and_acceptance(self):
        event=self.run/"phases"/"bootstrap"/"tasks"/"GOAL"/"attempts"/"goal-planner-1"
        (event/"plan").mkdir(parents=True)
        plan=event/"plan"/"PLAN.md"; plan.write_text("# internal draft\n")
        report=event/"report.md"; report.write_text("planned\n")
        task_path=self.run/"phases"/"bootstrap"/"tasks"/"GOAL"/"task.json"
        task_path.write_text(json.dumps({"role":"goal-planner","status":"active","accepted_report":None}))
        cmd=[sys.executable,str(SCRIPTS/"prepare_worker_rules.py"),"--project-root",str(self.project.resolve()),"--run-root",str(self.run.resolve()),"--skill-root",str(ROOT.resolve()),"--plan",str(plan.resolve()),"--revision","1"]
        cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertNotEqual(cp.returncode,0); self.assertIn("must be accepted",cp.stderr)

        review_event=event.parent.parent.parent/"REVIEW"/"attempts"/"plan-reviewer-1"
        review_report=review_event/"report.md"; review_report.parent.mkdir(parents=True); review_report.write_text("PASS\n")
        plan_snapshot=review_event/"plan-under-review"/"PLAN.md"; plan_snapshot.parent.mkdir(); plan_snapshot.write_bytes(plan.read_bytes())
        task_path.write_text(json.dumps({
            "role":"goal-planner","status":"accepted","accepted_report":str(report.resolve()),
            "last_plan_review":{"outcome":"pass","planner_attempt":str(event.resolve()),"plan":str(plan.resolve()),"plan_snapshot":str(plan_snapshot.resolve()),"report":str(review_report.resolve())}
        }))
        cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertEqual(cp.returncode,0,cp.stderr)

        plan.write_text("# mutated after acceptance\n")
        cp=subprocess.run([*cmd[:-1],"2"],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertNotEqual(cp.returncode,0); self.assertIn("changed after the fresh Plan Reviewer PASS",cp.stderr)

    def test_internal_goal_plan_symlink_cannot_bypass_review_provenance(self):
        event=self.run/"phases"/"bootstrap"/"tasks"/"GOAL-LINK"/"attempts"/"goal-planner-1"
        (event/"plan").mkdir(parents=True)
        external=self.project/"external-plan.md"; external.write_text("# external-looking draft\n")
        plan=event/"plan"/"PLAN.md"; plan.symlink_to(external)
        cmd=[sys.executable,str(SCRIPTS/"prepare_worker_rules.py"),"--project-root",str(self.project.resolve()),"--run-root",str(self.run.resolve()),"--skill-root",str(ROOT.resolve()),"--plan",str(plan),"--revision","1"]
        cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        self.assertNotEqual(cp.returncode,0); self.assertIn("must not use symlinks",cp.stderr)

    def test_snapshot_rejects_live_context_paths_outside_revision(self):
        protocol = self.project / "PROJECT-PROTOCOL.md"
        protocol.write_text("# frozen first\n")
        rules = self.prepare("--project-protocol", str(protocol.resolve()))
        manifest_path = rules.parent / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["project_protocol"] = str(protocol.resolve())
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "frozen revision copy"):
            verify_snapshot(rules)

    def test_snapshot_rejects_symlinked_rules_and_manifest_identity_files(self):
        rules = self.prepare()
        original_rules = rules.read_text()
        live_rules = self.project / "WORKER_RULES.md"
        live_rules.write_text(original_rules)
        rules.unlink()
        rules.symlink_to(live_rules)
        with self.assertRaisesRegex(ValueError, "worker rules must be a frozen regular file"):
            verify_snapshot(rules)

        # Recreate a clean revision, then attack the manifest identity file instead.
        rules.unlink()
        rules.write_text(original_rules)
        manifest = rules.parent / "MANIFEST.json"
        live_manifest = self.project / "MANIFEST.json"
        live_manifest.write_text(manifest.read_text())
        manifest.unlink()
        manifest.symlink_to(live_manifest)
        with self.assertRaisesRegex(ValueError, "manifest must be a frozen regular file"):
            verify_snapshot(rules)

    def test_snapshot_rejects_revision_identity_mismatch(self):
        rules = self.prepare()
        manifest_path = rules.parent / "MANIFEST.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["revision"] = 77
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "revision mismatch"):
            verify_snapshot(rules)

    def test_partial_rules_tmp_directory_is_never_treated_as_latest_revision(self):
        r1 = self.prepare()
        debris = self.run / "worker-rules" / "r9999.tmp"
        debris.mkdir(parents=True)
        (debris / "WORKER_RULES.md").write_text("partial\n")
        self.assertEqual(dsd_attempt.latest_rules(self.run), r1.resolve())

    def test_rule_revision_order_is_numeric_not_lexicographic(self):
        r1 = self.prepare()
        # Reuse the valid snapshot bytes under high numeric directory names to test
        # discovery ordering without needing thousands of real revisions.
        import shutil
        for name, revision in (("r9999", 9999), ("r10000", 10000)):
            dest = self.run / "worker-rules" / name
            shutil.copytree(r1.parent, dest)
            manifest = json.loads((dest / "MANIFEST.json").read_text())
            manifest["revision"] = revision
            # Re-point contained frozen paths to the copied revision.
            manifest["path"] = str((dest / "WORKER_RULES.md").resolve())
            manifest["protocol_dir"] = str((dest / "protocol").resolve())
            manifest["authority_plan"] = str((dest / "authority" / Path(manifest["authority_plan"]).name).resolve())
            manifest["authority_files"] = [str((dest / "authority" / Path(x).name).resolve()) for x in manifest["authority_files"]]
            if manifest.get("project_protocol"):
                manifest["project_protocol"] = str((dest / "project-context" / "PROJECT-PROTOCOL.md").resolve())
            manifest["worker_skill_catalog"] = str((dest / "WORKER-SKILL-CATALOG.md").resolve())
            manifest["worker_skills"] = {k: str((dest / "worker-skills" / k / "SKILL.md").resolve()) for k in manifest.get("worker_skills", {})}
            (dest / "MANIFEST.json").write_text(json.dumps(manifest))
        self.assertEqual(dsd_attempt.latest_rules(self.run).parent.name, "r10000")
        verify_snapshot(dsd_attempt.latest_rules(self.run))

    def test_approved_analyst_context_can_be_adopted_without_parent_enumeration(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "P1" / "attempts" / "planner-1"
        (attempt / "project-protocol").mkdir(parents=True)
        (attempt / "project-protocol" / "PROJECT-PROTOCOL.md").write_text("# distilled protocol\n")
        skill = attempt / "worker-skills" / "project-build" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: project-build\n---\n# Build procedure\n")
        (attempt / "report.md").write_text("# approved context\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "planner"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({
            "status": "accepted",
            "accepted_report": str((attempt / "report.md").resolve()),
            "attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}],
        }))

        self.mark_context_review_pass(attempt)
        rules = self.prepare("--adopt-context-from", str(attempt.resolve()))
        info = verify_snapshot(rules)
        self.assertEqual(Path(info["project_protocol"]).read_text(), "# distilled protocol\n")
        self.assertEqual(Path(info["worker_skills"]["project-build"]).read_text(), skill.read_text())


    def test_context_adoption_rejects_grunt_or_ungated_attempt(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "P1" / "attempts" / "implementer-1"
        attempt.mkdir(parents=True)
        (attempt / "report.md").write_text("# report\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "grunt", "role": "implementer"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({"attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}]}))
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"), "--project-root", str(self.project.resolve()),
             "--run-root", str(self.run.resolve()), "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()),
             "--revision", "1", "--adopt-context-from", str(attempt.resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("Analyst attempts", cp.stderr)

        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "discovery"}))
        task_state.write_text(json.dumps({"attempts": [{"event_dir": str(attempt.resolve()), "status": "started"}]}))
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"), "--project-root", str(self.project.resolve()),
             "--run-root", str(self.run.resolve()), "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()),
             "--revision", "1", "--adopt-context-from", str(attempt.resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("requires a gated Analyst attempt", cp.stderr)

    def test_context_adoption_rejects_non_attempt_directory(self):
        outside = self.project / "some-context"
        outside.mkdir()
        cp = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
                "--project-root", str(self.project.resolve()),
                "--run-root", str(self.run.resolve()),
                "--skill-root", str(ROOT.resolve()),
                "--plan", str(self.plan.resolve()),
                "--revision", "1",
                "--adopt-context-from", str(outside.resolve()),
            ],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("Analyst attempt directory", cp.stderr)

    def test_gated_but_unapproved_analyst_context_cannot_be_adopted(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "P1" / "attempts" / "planner-1"
        attempt.mkdir(parents=True)
        (attempt / "report.md").write_text("# not yet approved\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "planner"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({"status": "active", "attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}]}))
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"), "--project-root", str(self.project.resolve()),
             "--run-root", str(self.run.resolve()), "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()),
             "--revision", "1", "--adopt-context-from", str(attempt.resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("has not been approved", cp.stderr)

    def test_routed_recovery_context_can_be_adopted_without_accepting_implementation_task(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "T1" / "attempts" / "recovery-1"
        protocol = attempt / "project-protocol" / "PROJECT-PROTOCOL.md"
        protocol.parent.mkdir(parents=True)
        protocol.write_text("# recovered invariant\n")
        report = attempt / "report.md"
        report.write_text("# recovery diagnosis\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "recovery"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({
            "status": "planned",
            "attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}],
            "last_analysis": {"outcome": "resume", "report": str(report.resolve()), "attempt": str(attempt.resolve())},
        }))
        self.mark_context_review_pass(attempt)
        rules = self.prepare("--adopt-context-from", str(attempt.resolve()))
        self.assertEqual(Path(verify_snapshot(rules)["project_protocol"]).read_text(), "# recovered invariant\n")

    def test_adopted_context_rejects_symlink_escape(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "P1" / "attempts" / "planner-1"
        attempt.mkdir(parents=True)
        report = attempt / "report.md"
        report.write_text("# approved\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "planner"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({
            "status": "accepted", "accepted_report": str(report.resolve()),
            "attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}],
        }))
        live = self.project / "LIVE-PROTOCOL.md"
        live.write_text("# mutable live source\n")
        pp = attempt / "project-protocol"
        pp.mkdir()
        (pp / "PROJECT-PROTOCOL.md").symlink_to(live)
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"), "--project-root", str(self.project.resolve()),
             "--run-root", str(self.run.resolve()), "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()),
             "--revision", "1", "--adopt-context-from", str(attempt.resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("must be a regular file", cp.stderr)

    def test_project_protocol_is_snapshotted_and_loaded_for_new_worker(self):
        protocol = self.project / "PROJECT-PROTOCOL.md"
        protocol.write_text("# protocol\n- stable project invariant\n")
        rules = self.prepare("--project-protocol", str(protocol.resolve()))
        info = verify_snapshot(rules)
        snap = Path(info["project_protocol"])
        self.assertEqual(snap.read_text(), protocol.read_text())

        protocol.write_text("# changed live protocol\n")
        self.assertIn("stable project invariant", snap.read_text())

        cp, out = self.render(rules, "# Task T1\n\n## Objective\nDo bounded work.\n")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        prompt = out.read_text()
        self.assertIn(str(snap.resolve()), prompt)
        self.assertLess(prompt.index("PROJECT-PROTOCOL.md"), prompt.index("brief.md"))

    def test_only_selected_reusable_worker_skills_are_loaded(self):
        rules = self.prepare()
        info = verify_snapshot(rules)
        self.assertIn("llm-boundary", info["worker_skills"])
        self.assertIn("production-proof", info["worker_skills"])

        cp, out = self.render(
            rules,
            "# Task T1\n\n## Objective\nDiagnose.\n\n## Worker skills\n- llm-boundary\n",
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        prompt = out.read_text()
        self.assertIn(info["worker_skills"]["llm-boundary"], prompt)
        self.assertNotIn(info["worker_skills"]["production-proof"], prompt)

    def test_project_specific_worker_skill_can_be_snapshotted_and_selected(self):
        custom = self.project / "python-testing"
        custom.mkdir()
        (custom / "SKILL.md").write_text("---\nname: python-testing\ndescription: Run the project's focused Python test workflow.\n---\n# Python testing\n")
        (custom / "REFERENCE.md").write_text("# Extra testing reference\n")
        rules = self.prepare("--worker-skill", f"python-testing={custom.resolve()}")
        info = verify_snapshot(rules)
        snap = Path(info["worker_skills"]["python-testing"])
        (custom / "SKILL.md").write_text("changed live\n")
        self.assertIn("Python testing", snap.read_text())
        self.assertEqual((snap.parent / "REFERENCE.md").read_text(), "# Extra testing reference\n")
        cp, out = self.render(rules, "# Task T1\n\n## Objective\nTest.\n\n## Worker skills\n- python-testing\n")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(str(snap.resolve()), out.read_text())


    def test_new_revision_inherits_worker_context_without_parent_restatement(self):
        instruction = self.project / "AGENTS.md"
        instruction.write_text("stable project instruction\n")
        protocol = self.project / "PROJECT-PROTOCOL.md"
        protocol.write_text("# protocol r1\n")
        custom = self.project / "custom-skill"
        custom.mkdir()
        (custom / "SKILL.md").write_text("---\nname: custom-skill\ndescription: Stable project-specific procedure.\n---\n# custom\n")
        r1 = self.prepare(
            "--project-instruction", str(instruction.resolve()),
            "--project-protocol", str(protocol.resolve()),
            "--worker-skill", f"custom-skill={custom.resolve()}",
        )
        r1_info = verify_snapshot(r1)
        self.assertIn("custom-skill", r1_info["worker_skills"])

        # Revision 2 changes only the authoritative plan snapshot. The parent should
        # not need to remember and restate recurring worker context.
        self.plan.write_text("# authority r2\n")
        r2 = self.prepare(revision=2)
        r2_info = verify_snapshot(r2)
        self.assertEqual(Path(r2_info["project_protocol"]).read_text(), "# protocol r1\n")
        self.assertIn("custom-skill", r2_info["worker_skills"])
        inherited_instructions = [Path(x).read_text() for x in r2_info["authority_files"][1:]]
        self.assertEqual(inherited_instructions, ["stable project instruction\n"])

    def test_fresh_context_does_not_drop_existing_authoritative_plan(self):
        r1 = self.prepare()
        expected = Path(verify_snapshot(r1)["authority_plan"]).read_text()
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
             "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
             "--skill-root", str(ROOT.resolve()), "--revision", "2", "--fresh-context"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        r2 = self.run / "worker-rules" / "r0002" / "WORKER_RULES.md"
        self.assertEqual(Path(verify_snapshot(r2)["authority_plan"]).read_text(), expected)

    def test_context_can_be_explicitly_removed_on_later_revision(self):
        protocol = self.project / "PROJECT-PROTOCOL.md"
        protocol.write_text("# protocol\n")
        custom = self.project / "custom-skill"
        custom.mkdir()
        (custom / "SKILL.md").write_text("---\nname: custom-skill\ndescription: Temporary custom procedure.\n---\n# custom\n")
        self.prepare("--project-protocol", str(protocol.resolve()), "--worker-skill", f"custom-skill={custom.resolve()}")
        r2 = self.prepare("--clear-project-protocol", "--drop-worker-skill", "custom-skill", revision=2)
        info = verify_snapshot(r2)
        self.assertIsNone(info["project_protocol"])
        self.assertNotIn("custom-skill", info["worker_skills"])


    def test_resumed_session_stays_pinned_to_original_rules_revision(self):
        r1 = self.prepare()
        self.plan.write_text("# authority r2\n")
        r2 = self.prepare(revision=2)
        event = self.run / "attempts" / "implementer-1"
        event.mkdir(parents=True)
        (event / "terminal.json").write_text(json.dumps({"session_id": "ses-1"}))
        (event / "launch-reservation.json").write_text(json.dumps({"worker_rules": str(r1.resolve())}))
        task = {"attempts": [{"role": "implementer", "event_dir": str(event)}]}
        self.assertEqual(dsd_attempt.rules_for_resumed_session(task, "ses-1"), r1.resolve())
        self.assertNotEqual(dsd_attempt.rules_for_resumed_session(task, "ses-1"), r2.resolve())


    def test_worker_rules_do_not_expose_full_skill_catalog(self):
        rules = self.prepare()
        text = rules.read_text()
        self.assertNotIn("llm-boundary", text)
        self.assertNotIn("production-proof", text)
        self.assertNotIn(str(Path(verify_snapshot(rules)["authority_plan"])), text)
        self.assertIn("Authority/context paths are disclosed only to roles that need them", text)

    def test_new_revision_inherits_run_specific_rules_without_parent_restatement(self):
        r1 = self.prepare("--rule", "Never regenerate checked-in fixtures during review.")
        self.assertIn("Never regenerate checked-in fixtures during review.", r1.read_text())
        self.plan.write_text("# authority r2\n")
        r2 = self.prepare(revision=2)
        info = verify_snapshot(r2)
        self.assertEqual(info["run_rules"], ["Never regenerate checked-in fixtures during review."])
        self.assertIn("Never regenerate checked-in fixtures during review.", r2.read_text())

    def test_inherited_run_specific_rules_can_be_explicitly_cleared(self):
        self.prepare("--rule", "Temporary run constraint.")
        r2 = self.prepare("--clear-run-rules", revision=2)
        self.assertEqual(verify_snapshot(r2)["run_rules"], [])
        self.assertNotIn("Temporary run constraint.", r2.read_text())

    def test_snapshot_rejects_symlinked_project_protocol(self):
        live = self.project / "PROJECT-PROTOCOL.md"
        live.write_text("# live\n")
        rules = self.prepare("--project-protocol", str(live.resolve()))
        frozen = rules.parent / "project-context" / "PROJECT-PROTOCOL.md"
        frozen.unlink()
        frozen.symlink_to(live)
        with self.assertRaisesRegex(ValueError, "not a symlink"):
            verify_snapshot(rules)

    def test_snapshot_rejects_symlinked_authority_plan(self):
        rules = self.prepare()
        frozen = rules.parent / "authority" / "PLAN.md"
        live = self.project / "LIVE-PLAN.md"
        live.write_text("# live replacement\n")
        frozen.unlink()
        frozen.symlink_to(live)
        with self.assertRaisesRegex(ValueError, "authority snapshot must be a frozen regular file"):
            verify_snapshot(rules)

    def test_snapshot_rejects_symlinked_worker_skill(self):
        rules = self.prepare()
        frozen = rules.parent / "worker-skills" / "llm-boundary" / "SKILL.md"
        live = self.project / "live-skill.md"
        live.write_text("# live skill\n")
        frozen.unlink()
        frozen.symlink_to(live)
        with self.assertRaisesRegex(ValueError, "not a symlink"):
            verify_snapshot(rules)

    def test_analyst_adoption_cannot_silently_shadow_builtin_skill(self):
        attempt = self.run / "phases" / "phase-1" / "tasks" / "P1" / "attempts" / "planner-1"
        skill = attempt / "worker-skills" / "llm-boundary" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# accidental shadow\n")
        (attempt / "report.md").write_text("# approved context\n")
        (attempt / "task-attempt.json").write_text(json.dumps({"tier": "analyst", "role": "planner"}))
        task_state = attempt.parents[1] / "task.json"
        task_state.write_text(json.dumps({
            "status": "accepted",
            "accepted_report": str((attempt / "report.md").resolve()),
            "attempts": [{"event_dir": str(attempt.resolve()), "status": "gated"}],
        }))
        self.mark_context_review_pass(attempt)
        cp = subprocess.run(
            [sys.executable, str(SCRIPTS / "prepare_worker_rules.py"), "--project-root", str(self.project.resolve()),
             "--run-root", str(self.run.resolve()), "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()),
             "--revision", "1", "--adopt-context-from", str(attempt.resolve())],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("collides with built-in skill", cp.stderr)

    def test_planning_analyst_gets_metadata_catalog_but_implementer_does_not(self):
        rules = self.prepare()
        info = verify_snapshot(rules)
        catalog = Path(info["worker_skill_catalog"])
        self.assertIn("`llm-boundary`", catalog.read_text())
        self.assertIn("Diagnose structured LLM/provider/parser failures", catalog.read_text())

        brief = self.run / "planner-brief.md"
        brief.write_text("# Task P1\n\n## Objective\nPlan downstream work.\n")
        report = self.run / "planner-report.md"
        out = self.run / "planner-prompt.txt"
        cp = subprocess.run([
            sys.executable, str(SCRIPTS / "render_worker_prompt.py"),
            "--role", "planner", "--task-id", "P1", "--phase-id", "phase-1", "--run-root", str(self.run.resolve()),
            "--worker-rules", str(rules.resolve()), "--task", str(brief.resolve()),
            "--report", str(report.resolve()), "--output", str(out.resolve()),
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(str(catalog.resolve()), out.read_text())
        self.assertIn("PLAN-AUTHORING.md", out.read_text())
        self.assertIn("preflight-plan", out.read_text())
        self.assertIn("--phase-id phase-1", out.read_text())
        self.assertIn("never leave mechanical brief repair to the parent", out.read_text())

        cp, review_out = self.render(rules, "# Plan review\n", role="plan-reviewer")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn(str(catalog.resolve()), review_out.read_text())
        self.assertNotIn("PLAN-AUTHORING.md", review_out.read_text())

        cp, worker_out = self.render(rules, "# Task T1\n\n## Objective\nImplement bounded work.\n")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertNotIn(str(catalog.resolve()), worker_out.read_text())

    def test_rendered_prompt_composes_shared_quality_instead_of_repeating_it(self):
        rules = self.prepare()
        info=verify_snapshot(rules); quality=str((Path(info["protocol_dir"])/"QUALITY.md").resolve())
        for role in ("reviewer","discovery","implementer","verification"):
            with self.subTest(role=role):
                cp, out = self.render(rules, "# Task T1\n\n## Objective\nDo the assigned work.\n", role=role)
                self.assertEqual(cp.returncode, 0, cp.stderr)
                rendered = out.read_text()
                self.assertIn(quality, rendered)
                self.assertIn("COMMON defines universal boundaries; QUALITY", rendered)
                self.assertNotIn("Quality bar: production-grade", rendered)
                self.assertNotIn("Acceptance integrity:", rendered)
        for role in ("evidence-clerk","context-reviewer"):
            cp, out = self.render(rules, "# Task T1\n\n## Objective\nDo bounded non-technical review/index work.\n", role=role)
            self.assertEqual(cp.returncode,0,cp.stderr)
            self.assertNotIn(quality,out.read_text())


    def test_legacy_rules_revision_without_quality_remains_readable(self):
        rules=self.prepare()
        manifest=rules.parent/"MANIFEST.json"
        data=json.loads(manifest.read_text())
        data["protocol_files"]=[x for x in data["protocol_files"] if x!="QUALITY.md"]
        manifest.write_text(json.dumps(data,indent=2,sort_keys=True)+"\n")
        (rules.parent/"protocol"/"QUALITY.md").unlink()
        info=verify_snapshot(rules)
        self.assertEqual(info["revision"],1)
        cp,out=self.render(rules,"# Task T1\n\n## Objective\nReview legacy frozen context.\n",role="reviewer")
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertNotIn("/QUALITY.md",out.read_text())

    def test_rules_revisions_cannot_be_backfilled_after_later_revision(self):
        self.prepare(revision=1)
        self.prepare(revision=3)
        cp = subprocess.run([
            sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
            "--project-root", str(self.project.resolve()), "--run-root", str(self.run.resolve()),
            "--skill-root", str(ROOT.resolve()), "--plan", str(self.plan.resolve()), "--revision", "2",
        ], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("later completed revisions already exist", cp.stderr)

    def test_unknown_worker_skill_fails_loudly(self):
        rules = self.prepare()
        cp, _ = self.render(rules, "# Task T1\n\n## Objective\nWork.\n\n## Worker skills\n- imaginary-skill\n")
        self.assertNotEqual(cp.returncode, 0)
        self.assertIn("absent from this worker-rules revision", cp.stderr)

    def test_worker_skill_tags_are_explicit_loading_hints(self):
        self.assertEqual(worker_skill_tags("## Worker skills\n- llm-boundary\n- production-proof\n"), ["llm-boundary", "production-proof"])
        self.assertEqual(worker_skill_tags("## Worker skills\n- none\n"), [])
        self.assertEqual(worker_skill_tags("## Worker skills\n- NONE\n"), [])
        with self.assertRaisesRegex(ValueError, "must be bare skill IDs"):
            worker_skill_tags("## Worker skills\n- ../../escape\n")

    def test_quoted_skill_sections_inside_code_fences_are_not_control_data(self):
        brief = """# Diagnose malformed brief

The previous brief contained this invalid section:

```markdown
## Analyst skills
- dsd-phase-surveyor
```

## Analyst skills
- llm-boundary
"""
        self.assertEqual(worker_skill_tags(brief, "discovery"), ["llm-boundary"])

    def test_allowed_source_changes_tree_suffix_canonicalizes_to_prefix(self):
        text="# T\n\n## Allowed source changes\n- `src/feature/**`\n"
        self.assertEqual(allowed_source_changes(text),["src/feature"])

    def test_allowed_source_changes_rejects_other_glob_syntax(self):
        text="# T\n\n## Allowed source changes\n- `src/*.py`\n"
        with self.assertRaisesRegex(ValueError,"path prefixes, not globs"):
            allowed_source_changes(text)

    def test_quoted_allowed_source_changes_inside_fence_is_not_a_write_restriction(self):
        brief = """# Diagnose prior contract

```markdown
## Allowed source changes
NONE
```
"""
        self.assertFalse(has_explicit_write_restriction(brief))

    def test_role_scoped_worker_skills_do_not_anchor_fresh_reviewer(self):
        rules=self.prepare()
        brief_text="# Task T1\n\n## Worker skills\n- positive-control\n\n## Implementer skills\n- production-proof\n\n## Reviewer skills\n- registered-baseline\n\n## Analyst skills\n- llm-boundary\n"
        cp,impl=self.render(rules,brief_text,role="implementer"); self.assertEqual(cp.returncode,0,cp.stderr)
        text=impl.read_text(); self.assertIn("positive-control/SKILL.md",text); self.assertIn("production-proof/SKILL.md",text); self.assertNotIn("registered-baseline/SKILL.md",text); self.assertNotIn("llm-boundary/SKILL.md",text)
        cp,review=self.render(rules,brief_text,role="reviewer"); self.assertEqual(cp.returncode,0,cp.stderr)
        text=review.read_text(); self.assertIn("positive-control/SKILL.md",text); self.assertIn("registered-baseline/SKILL.md",text); self.assertNotIn("production-proof/SKILL.md",text); self.assertNotIn("llm-boundary/SKILL.md",text)
        cp,analysis=self.render(rules,brief_text,role="discovery"); self.assertEqual(cp.returncode,0,cp.stderr)
        text=analysis.read_text(); self.assertIn("positive-control/SKILL.md",text); self.assertIn("llm-boundary/SKILL.md",text); self.assertNotIn("production-proof/SKILL.md",text); self.assertNotIn("registered-baseline/SKILL.md",text)

    def test_typed_exact_inputs_render_with_semantic_labels(self):
        rules=self.prepare(); paths=[]
        flags=[("--authority-input","Governing authority inputs"),("--owner-decision","Owner decisions"),("--analyst-finding","Accepted Analyst findings"),("--dependency-finding","Accepted dependency findings"),("--escalation-context","Current escalation packet"),("--decision-context","Legacy decision-boundary evidence"),("--review-finding","Current Review findings"),("--worker-report","Prior worker report / claims"),("--recovery-evidence","Recovery evidence")]
        args=[]
        for i,(flag,_) in enumerate(flags):
            p=self.run/f"input-{i}.md"; p.write_text(str(i)); paths.append(p); args += [flag,str(p.resolve())]
        cp,out=self.render(rules,"# Task T1\n",extra_args=args); self.assertEqual(cp.returncode,0,cp.stderr)
        text=out.read_text()
        for (_,label),path in zip(flags,paths): self.assertIn(label+":",text); self.assertIn(str(path.resolve()),text)
        self.assertNotIn("Additional exact inputs",text)

    def test_context_promotion_requires_review_and_rejects_post_review_mutation(self):
        attempt=self.run/"phases"/"phase-1"/"tasks"/"CTX"/"attempts"/"planner-1"; skill=attempt/"worker-skills"/"project-build"/"SKILL.md"; skill.parent.mkdir(parents=True); skill.write_text("# Build v1\n")
        report=attempt/"report.md"; report.write_text("# technical result\n"); (attempt/"task-attempt.json").write_text(json.dumps({"tier":"analyst","role":"planner"}))
        state=attempt.parents[1]/"task.json"; state.write_text(json.dumps({"status":"accepted","accepted_report":str(report.resolve()),"attempts":[{"event_dir":str(attempt.resolve()),"status":"gated","tier":"analyst","role":"planner"}]}))
        cmd=[sys.executable,str(SCRIPTS/"prepare_worker_rules.py"),"--project-root",str(self.project.resolve()),"--run-root",str(self.run.resolve()),"--skill-root",str(ROOT.resolve()),"--plan",str(self.plan.resolve()),"--revision","1","--adopt-context-from",str(attempt.resolve())]
        cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30); self.assertNotEqual(cp.returncode,0); self.assertIn("Context-Reviewer PASS",cp.stderr)
        self.mark_context_review_pass(attempt); skill.write_text("# Build v2 mutated\n")
        cp=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30); self.assertNotEqual(cp.returncode,0); self.assertIn("changed after review",cp.stderr)

    def test_proof_patterns_are_unified_as_reusable_skills(self):
        rules=self.prepare(); info=verify_snapshot(rules)
        self.assertFalse((Path(info["protocol_dir"])/"PROOF-PATTERNS.md").exists())
        for skill_id in ("production-proof","llm-boundary","preregistered-acceptance","positive-control","registered-baseline"):
            self.assertIn(skill_id,info["worker_skills"])

    def test_context_docs_keep_parent_notes_separate(self):
        context = (ROOT / "CONTEXT.md").read_text()
        self.assertIn("Do not attach this wholesale to workers", context)
        self.assertIn("Project Protocol", context)
        self.assertIn("only role-applicable task-selected skills", context)
        self.assertIn("skills never widen task authority", context.lower())


if __name__ == "__main__":
    unittest.main()
