import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
sys.path.insert(0,str(SCRIPTS))
import dsd_task


def git(cwd,*args):
    cp=subprocess.run(["git",*args],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode: raise RuntimeError(cp.stderr)


class A: pass


class RoleCommandCoherenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.project=self.root/"project"; self.project.mkdir()
        git(self.project,"init","-q"); git(self.project,"config","user.email","t@example.com"); git(self.project,"config","user.name","T")
        (self.project/"a.txt").write_text("a\n"); git(self.project,"add","."); git(self.project,"commit","-qm","init")
        self.run=self.project/"TBag"/"runs"/"r1"; self.run.mkdir(parents=True)
        a=A(); a.project_root=self.project; a.run_root=self.run; a.run_id="r1"; a.runtime_root=str(self.root/"runtime"); a.max_workers=4; a.grunt_driver="opencode"; a.grunt_model="grunt/model"; a.analyst_driver="opencode"; a.analyst_model="analyst/model"
        dsd_task.command_init(a)
    def tearDown(self): self.tmp.cleanup()

    def task(self,tid,*,kind="implementation",role="implementer",status="active",followup=False):
        root=dsd_task.task_root(self.run,"P1",tid); root.mkdir(parents=True,exist_ok=True)
        brief=root/"brief.md"; brief.write_text(f"# {tid}\n")
        value={"format":dsd_task.FORMAT,"phase_id":"P1","task_id":tid,"kind":kind,"role":role,"tier":dsd_task.DEFAULT_TIER[role],"brief":str(brief),"dependencies":[],"requires_integration":kind=="implementation","status":status,"attempts":[],"review_rounds":0,"review_history":[]}
        if followup:
            value["followup_triage_for"]="SOURCE"; value["followup_finding_ids"]=["F-1"]
        dsd_task.write_json(root/"task.json",value); return value

    def gated(self,tid,role,text,name=None):
        task=dsd_task.load_task(self.run,"P1",tid); event=dsd_task.task_root(self.run,"P1",tid)/"attempts"/(name or f"{role}-1"); event.mkdir(parents=True,exist_ok=True)
        report=event/"report.md"; report.write_text(text)
        task["attempts"].append({"task_id":tid,"role":role,"tier":dsd_task.DEFAULT_TIER[role],"status":"gated","event_dir":str(event)})
        task["status"]="awaiting-review" if role=="reviewer" else "active"
        dsd_task.write_json(dsd_task.task_file(self.run,"P1",tid),task)
        return report,event

    def graph(self,event):
        plan=event/"plan"; plan.mkdir(exist_ok=True)
        graph=plan/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":"NEXT","kind":"analysis"}]}))
        return graph

    def test_analyst_report_token_drives_result_without_parent_outcome(self):
        self.task("T1"); report,event=self.gated("T1","discovery","`REPLAN`\nSplit the ownership boundary.\n"); self.graph(event)
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T1"; a.report=report
        out=dsd_task.command_analysis_result(a)
        self.assertEqual(out["outcome"],"replan")
        self.assertEqual(dsd_task.load_task(self.run,"P1","T1")["last_analysis"]["outcome"],"replan")

    def test_explicit_outcome_is_legacy_fallback_and_cannot_override_report(self):
        self.task("T2"); report,_=self.gated("T2","reviewer","**FAIL** — concrete defect\n")
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.task_id="T2"; a.report=report
        out=dsd_task.command_review(a); self.assertEqual(out["outcome"],"fail")

        self.task("T3"); report,_=self.gated("T3","reviewer","FAIL\n")
        b=A(); b.run_root=self.run; b.phase_id="P1"; b.task_id="T3"; b.report=report; b.outcome="pass"
        with self.assertRaisesRegex(ValueError,"do not make the parent reinterpret"):
            dsd_task.command_review(b)

        self.task("T4"); report,_=self.gated("T4","reviewer","Legacy reviewer prose without a routing token.\n")
        c=A(); c.run_root=self.run; c.phase_id="P1"; c.task_id="T4"; c.report=report; c.outcome="fail"
        self.assertEqual(dsd_task.command_review(c)["outcome"],"fail")

    def test_parser_no_longer_requires_parent_to_repeat_semantic_outcome(self):
        parser=dsd_task.parser()
        for command in ("review","plan-review","context-review","analysis-result"):
            args=parser.parse_args([command,"--run-root",str(self.run),"--phase-id","P1","--task-id","T","--report",str(self.run/"r.md")])
            self.assertIsNone(args.outcome,command)

    def test_followup_triage_and_explicit_analyst_tokens_use_analyst_disposition_route(self):
        self.task("TRIAGE",kind="analysis",role="planner",followup=True); self.gated("TRIAGE","planner","RESUME\nCurrent plan already owns it.\n")
        task=dsd_task.load_task(self.run,"P1","TRIAGE")
        action=dsd_task._reconcile_action(self.run,"P1",task)
        self.assertEqual(action["action"],"record-analyst-disposition")

        self.task("FIND",kind="analysis",role="discovery"); self.gated("FIND","discovery","Root cause evidence only; no lifecycle transition requested.\n")
        action=dsd_task._reconcile_action(self.run,"P1",dsd_task.load_task(self.run,"P1","FIND"))
        self.assertEqual(action["action"],"accept-specialist-result")

    def test_advance_records_worker_owned_analyst_resume(self):
        self.task("ADV"); self.gated("ADV","discovery","RESUME\nExisting brief remains sufficient.\n")
        a=A(); a.run_root=self.run; a.phase_id="P1"; a.max_steps=4
        out=dsd_task.command_advance(a)
        self.assertTrue(any(x.get("action")=="record-analyst-disposition" for x in out["applied"]),out)
        current=dsd_task.load_task(self.run,"P1","ADV")
        self.assertEqual(current["last_analysis"]["outcome"],"resume")
        self.assertEqual(current["status"],"planned")

    def test_decorated_capability_token_uses_same_normalization(self):
        report=self.run/"capability.md"; report.write_text("# Recovery report\n**ESCALATE CAPABILITY** — stronger reasoning needed\n")
        self.assertTrue(dsd_task.report_requests_capability(report))
        for role in dsd_task.ANALYST_DISPOSITION_ROLES:
            self.assertEqual(dsd_task.declared_report_outcome(report,role,required=False),"capability")


if __name__=="__main__": unittest.main()
