import json, subprocess, sys, tempfile, unittest, time
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/"scripts"; sys.path.insert(0,str(SCRIPTS))
import dsd_task, dsd_workspace, scope_snapshot

def git(cwd,*args,check=True):
    cp=subprocess.run(["git",*args],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if check and cp.returncode: raise RuntimeError(cp.stderr)
    return cp.stdout.strip()

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name); self.project=self.root/"project"; self.project.mkdir()
        git(self.project,"init","-q"); git(self.project,"config","user.email","t@example.com"); git(self.project,"config","user.name","T")
        (self.project/"a.txt").write_text("alpha\n"); (self.project/"b.txt").write_text("beta\n"); git(self.project,"add","."); git(self.project,"commit","-qm","init")
        self.run=self.project/"TBag"/"runs"/"r1"; self.run.mkdir(parents=True)
        class A:pass
        a=A();a.project_root=self.project;a.run_root=self.run;a.run_id="r1";a.runtime_root=str(self.root/"runtime");a.max_workers=4;a.grunt_driver="opencode";a.grunt_model="g";a.analyst_driver="opencode";a.analyst_model="a";dsd_task.command_init(a)
    def tearDown(self): self.tmp.cleanup()
    def register(self,tid,kind="implementation",text=None):
        brief=self.run/f"{tid}.md";brief.write_text(text or f"# {tid}\n")
        class A:pass
        if kind!="implementation":
            a=A();a.run_root=self.run;a.phase_id="P";a.task_id=tid;a.brief=brief;a.kind=kind;a.role="discovery";a.tier="analyst";a.dependency=[];a.requires_integration=False
            dsd_task.command_register_direct(a); return
        plan_id=f"PLAN-{tid}"; planner=self.run/f"{plan_id}.md"; planner.write_text(f"# Plan {tid}\n")
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id=plan_id;a.brief=planner;a.kind="analysis";a.role="planner";a.tier="analyst";a.dependency=[];a.requires_integration=False;dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P",plan_id)/"attempts"/"planner-1"; tasks=event/"plan"/"tasks"; tasks.mkdir(parents=True); report=event/"report.md"; report.write_text("plan\n")
        (tasks/f"{tid}.md").write_text(text or f"# {tid}\n"); graph=event/"plan"/"task-graph.json"; graph.write_text(json.dumps({"format":dsd_task.PLAN_FORMAT,"tasks":[{"task_id":tid,"kind":"implementation","role":"implementer","tier":"grunt","brief":f"tasks/{tid}.md","dependencies":[],"requires_integration":True}]}))
        st=dsd_task.load_task(self.run,"P",plan_id);st["attempts"].append({"task_id":plan_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)});st["status"]="active";dsd_task.write_json(dsd_task.task_file(self.run,"P",plan_id),st)
        a.report=report;dsd_task.command_accept(a);r=A();r.run_root=self.run;r.phase_id="P";r.plan=graph;dsd_task.command_register_plan(r)
    def register_replacement(self,new,old,text=None,carry=True,rederive=True):
        class A: pass
        plan_id=f"PLAN-{new}"; planner=self.run/f"{plan_id}.md"; planner.write_text(f"# Plan {new}\n")
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id=plan_id;a.brief=planner;a.kind="analysis";a.role="planner";a.tier="analyst";a.dependency=[];a.requires_integration=False;dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,"P",plan_id)/"attempts"/"planner-1";tasks=event/"plan"/"tasks";tasks.mkdir(parents=True);report=event/"report.md";report.write_text("replacement plan\n")
        (tasks/f"{new}.md").write_text(text or f"# {new}\n")
        item={"task_id":new,"kind":"implementation","role":"implementer","tier":"grunt","brief":f"tasks/{new}.md","dependencies":[],"requires_integration":True,"supersedes":[old]}
        if carry:item["carry_from"]=old
        graph_data={"format":dsd_task.PLAN_FORMAT,"tasks":[item]}
        if not carry and rederive: graph_data["rederive_from_primary"]=[old]
        graph=event/"plan"/"task-graph.json";graph.write_text(json.dumps(graph_data))
        st=dsd_task.load_task(self.run,"P",plan_id);st["attempts"].append({"task_id":plan_id,"role":"planner","tier":"analyst","status":"gated","event_dir":str(event)});st["status"]="active";dsd_task.write_json(dsd_task.task_file(self.run,"P",plan_id),st)
        a.report=report;dsd_task.command_accept(a);r=A();r.run_root=self.run;r.phase_id="P";r.plan=graph;return dsd_task.command_register_plan(r)

    def ws(self,tid):
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id=tid
        return dsd_workspace.command_create(a)
    def accept(self,tid):
        class A:pass
        c=A();c.run_root=self.run;c.phase_id="P";c.task_id=tid;c.label="reviewer-1"
        checkpoint=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        event=dsd_task.task_root(self.run,"P",tid)/"attempts"/"reviewer-1";event.mkdir(parents=True,exist_ok=True)
        report=event/"report.md";report.write_text("pass\n"); (event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0}))
        t=dsd_task.load_task(self.run,"P",tid);t.setdefault("attempts",[]).append({"task_id":tid,"role":"reviewer","status":"gated","event_dir":str(event),"checkpoint_ref":checkpoint});t["status"]="awaiting-review";dsd_task.write_json(dsd_task.task_file(self.run,"P",tid),t)
        r=A();r.run_root=self.run;r.phase_id="P";r.task_id=tid;r.outcome="pass";r.report=report;dsd_task.command_review(r)
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id=tid;a.report=report;dsd_task.command_accept(a)


    def test_integrate_can_collapse_explicit_reviewer_pass_accept_and_land(self):
        self.register("T-FAST-LAND"); ws=self.ws("T-FAST-LAND"); wt=Path(ws["worktree"]); (wt/"a.txt").write_text("landed\n")
        class A: pass
        c=A(); c.run_root=self.run; c.phase_id="P"; c.task_id="T-FAST-LAND"; c.label="reviewer-1"
        checkpoint=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        event=dsd_task.task_root(self.run,"P","T-FAST-LAND")/"attempts"/"reviewer-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("## Verdict\nPASS — exact reviewed delta is sound.\n")
        (event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0}))
        task=dsd_task.load_task(self.run,"P","T-FAST-LAND"); task.setdefault("attempts",[]).append({"task_id":"T-FAST-LAND","role":"reviewer","tier":"grunt","status":"gated","event_dir":str(event),"checkpoint_ref":checkpoint}); task["status"]="awaiting-review"; dsd_task.write_json(dsd_task.task_file(self.run,"P","T-FAST-LAND"),task)
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-FAST-LAND"; a.review_pass_report=report
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out["changed"]); self.assertEqual((self.project/"a.txt").read_text(),"landed\n")
        final=dsd_task.load_task(self.run,"P","T-FAST-LAND"); self.assertEqual(final["status"],"integrated"); self.assertEqual(final["last_review"]["outcome"],"pass")

    def test_integrate_shortcut_preserves_reviewer_followup_obligation(self):
        self.register("T-FOLLOWUP-LAND"); ws=self.ws("T-FOLLOWUP-LAND"); wt=Path(ws["worktree"]); (wt/"a.txt").write_text("landed-with-followup\n")
        class A: pass
        c=A(); c.run_root=self.run; c.phase_id="P"; c.task_id="T-FOLLOWUP-LAND"; c.label="reviewer-1"
        checkpoint=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        event=dsd_task.task_root(self.run,"P","T-FOLLOWUP-LAND")/"attempts"/"reviewer-1"; event.mkdir(parents=True)
        report=event/"report.md"; report.write_text("PASS\n\n## Follow-up obligations\n- Production cutover wiring still needs an explicit end-to-end task.\n")
        (event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0}))
        task=dsd_task.load_task(self.run,"P","T-FOLLOWUP-LAND"); task.setdefault("attempts",[]).append({"task_id":"T-FOLLOWUP-LAND","role":"reviewer","tier":"grunt","status":"gated","event_dir":str(event),"checkpoint_ref":checkpoint}); task["status"]="awaiting-review"; dsd_task.write_json(dsd_task.task_file(self.run,"P","T-FOLLOWUP-LAND"),task)
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-FOLLOWUP-LAND"; a.review_pass_report=report
        out=dsd_workspace.command_integrate(a)
        self.assertEqual(out["status"],"integrated"); self.assertEqual((self.project/"a.txt").read_text(),"landed-with-followup\n")
        final=dsd_task.load_task(self.run,"P","T-FOLLOWUP-LAND")
        findings=final["review_history"][-1]["findings"]
        self.assertEqual(len(findings),1); self.assertEqual(findings[0]["status"],"open")
        self.assertIn("cutover wiring",findings[0]["text"])
        self.assertFalse(dsd_task._phase_task_success(self.run,"P",final))

    def test_explicit_human_acceptance_lands_exact_red_reviewer_checkpoint(self):
        self.register("T-HUMAN-LAND"); ws=self.ws("T-HUMAN-LAND"); wt=Path(ws["worktree"]); (wt/"a.txt").write_text("human-authorized\n")
        class A: pass
        c=A(); c.run_root=self.run; c.phase_id="P"; c.task_id="T-HUMAN-LAND"; c.label="reviewer-1"
        checkpoint=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        review_event=dsd_task.task_root(self.run,"P","T-HUMAN-LAND")/"attempts"/"reviewer-1"; review_event.mkdir(parents=True)
        review=review_event/"report.md"; review.write_text("ESCALATE: owner must decide whether this red predicate is acceptable.\n")
        (review_event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0}))
        task=dsd_task.load_task(self.run,"P","T-HUMAN-LAND"); task.setdefault("attempts",[]).append({"task_id":"T-HUMAN-LAND","role":"reviewer","tier":"grunt","status":"gated","event_dir":str(review_event),"checkpoint_ref":checkpoint}); task["status"]="awaiting-review"; dsd_task.write_json(dsd_task.task_file(self.run,"P","T-HUMAN-LAND"),task)
        r=A(); r.run_root=self.run; r.phase_id="P"; r.task_id="T-HUMAN-LAND"; r.outcome="escalate"; r.report=review
        self.assertEqual(dsd_task.command_review(r)["status"],"needs-analysis")

        analysis_event=dsd_task.task_root(self.run,"P","T-HUMAN-LAND")/"attempts"/"discovery-1"; analysis_event.mkdir(parents=True)
        analysis=analysis_event/"report.md"; analysis.write_text("ESCALATE: explicit Human acceptance decision required.\n")
        (analysis_event/"terminal.json").write_text(json.dumps({"status":"process-exited","exit_code":0}))
        task=dsd_task.load_task(self.run,"P","T-HUMAN-LAND"); task["attempts"].append({"task_id":"T-HUMAN-LAND","role":"discovery","tier":"analyst","status":"gated","event_dir":str(analysis_event)}); dsd_task.write_json(dsd_task.task_file(self.run,"P","T-HUMAN-LAND"),task)
        r.outcome="escalate"; r.report=analysis
        self.assertEqual(dsd_task.command_analysis_result(r)["status"],"blocked")

        decision=self.run/"human-accept.md"; decision.write_text("Accept this exact reviewed checkpoint; preserve the Reviewer escalation as red evidence.\n")
        r.decision=decision; r.route="accept"
        accepted=dsd_task.command_resolve_escalation(r); self.assertEqual(accepted["status"],"accepted")
        r.review_pass_report=None
        landed=dsd_workspace.command_integrate(r)
        self.assertEqual(landed["status"],"integrated"); self.assertEqual(landed["acceptance_basis"],"explicit-human-authority")
        self.assertEqual((self.project/"a.txt").read_text(),"human-authorized\n")
        final=dsd_task.load_task(self.run,"P","T-HUMAN-LAND"); self.assertEqual(final["last_review"]["outcome"],"escalate")
        self.assertEqual(final["human_acceptance"]["review_checkpoint_ref"],checkpoint)

    def test_workspace_lock_allows_parallel_snapshots_but_blocks_on_integration(self):
        lock=self.run/'.workspace.lock'
        helper=(
            "import sys,time; from pathlib import Path; "
            f"sys.path.insert(0,{str(SCRIPTS)!r}); import dsd_task; "
            "lock=Path(sys.argv[1]); mode=sys.argv[2]; ready=Path(sys.argv[3]); go=Path(sys.argv[4]); acquired=Path(sys.argv[5]); "
            "ready.write_text('ready'); "
            "\nwhile not go.exists(): time.sleep(0.005)"
            "\nwith dsd_task.file_lock(lock, shared=(mode=='shared')): acquired.write_text(str(time.time())); time.sleep(0.30)"
        )
        go=self.root/'go'; r1=self.root/'r1'; r2=self.root/'r2'; a1=self.root/'a1'; a2=self.root/'a2'
        p1=subprocess.Popen([sys.executable,'-c',helper,str(lock),'shared',str(r1),str(go),str(a1)])
        p2=subprocess.Popen([sys.executable,'-c',helper,str(lock),'shared',str(r2),str(go),str(a2)])
        deadline=time.time()+3
        while time.time()<deadline and not (r1.exists() and r2.exists()): time.sleep(0.01)
        self.assertTrue(r1.exists() and r2.exists()); go.write_text('go')
        self.assertEqual(p1.wait(timeout=3),0); self.assertEqual(p2.wait(timeout=3),0)
        self.assertLess(abs(float(a1.read_text())-float(a2.read_text())),0.12)

        go2=self.root/'go2'; r3=self.root/'r3'; r4=self.root/'r4'; a3=self.root/'a3'; a4=self.root/'a4'
        holder=subprocess.Popen([sys.executable,'-c',helper,str(lock),'shared',str(r3),str(go2),str(a3)])
        exclusive=subprocess.Popen([sys.executable,'-c',helper,str(lock),'exclusive',str(r4),str(go2),str(a4)])
        deadline=time.time()+3
        while time.time()<deadline and not (r3.exists() and r4.exists()): time.sleep(0.01)
        self.assertTrue(r3.exists() and r4.exists()); go2.write_text('go')
        self.assertEqual(holder.wait(timeout=3),0); self.assertEqual(exclusive.wait(timeout=3),0)
        self.assertGreater(abs(float(a3.read_text())-float(a4.read_text())),0.20)

    def test_internal_snapshot_commits_bypass_project_hooks(self):
        hooks=self.project/".git"/"hooks"; hooks.mkdir(exist_ok=True)
        hook=hooks/"pre-commit"; hook.write_text("#!/bin/sh\necho project-hook-ran >&2\nexit 91\n"); hook.chmod(0o755)
        self.register("T-HOOK")
        ws=self.ws("T-HOOK")
        self.assertTrue(Path(ws["worktree"]).is_dir())
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-HOOK"; a.label="hook-checkpoint"
        out=dsd_workspace.command_checkpoint(a)
        self.assertTrue(out["checkpoint_ref"]); self.assertRegex(out["checkpoint_oid"],r"^[0-9a-f]{40,64}$")
        self.register("A-HOOK",kind="analysis")
        view=dsd_workspace.prepare_launch_workspace(self.run,"P","A-HOOK","discovery")
        self.assertEqual(view["mode"],"analysis-view")

    def test_failed_worktree_add_reclaims_branch_created_before_failure(self):
        self.register("T-ADD-FAIL")
        original=dsd_workspace.run_cmd
        seen={"failed":False}
        def flaky(cmd,cwd,*args,**kwargs):
            if not seen["failed"] and len(cmd)>=5 and cmd[0]=="git" and "worktree" in cmd and "add" in cmd and "-b" in cmd:
                seen["failed"]=True
                branch=cmd[cmd.index("-b")+1]
                original(["git","branch",branch,"HEAD"],cwd)
                raise ValueError("synthetic checkout failure")
            return original(cmd,cwd,*args,**kwargs)
        dsd_workspace.run_cmd=flaky
        try:
            with self.assertRaisesRegex(ValueError,"synthetic checkout failure"):
                self.ws("T-ADD-FAIL")
        finally:
            dsd_workspace.run_cmd=original
        refs=git(self.project,"for-each-ref","--format=%(refname:short)","refs/heads")
        self.assertNotIn("dsd/r1/P/T-ADD-FAIL-base",refs)
        self.assertNotIn("dsd/r1/P/T-ADD-FAIL",refs)

    def test_cleanup_phase_reclaims_legacy_failed_setup_branch_without_workspace(self):
        self.register("T-LEGACY-LEAK")
        branch="dsd/r1/P/T-LEGACY-LEAK-base"; git(self.project,"branch",branch,"HEAD")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"
        out=dsd_workspace.command_cleanup_phase(a)
        self.assertTrue(any(x["branch"]==branch for x in out["orphan_setup_branches_removed"]),out)
        refs=git(self.project,"for-each-ref","--format=%(refname:short)","refs/heads")
        self.assertNotIn(branch,refs)

    def test_workspace_captures_primary_tracked_dirty_but_not_ambient_untracked(self):
        self.register("T1"); (self.project/"a.txt").write_text("dirty\n"); (self.project/"new.txt").write_text("new\n")
        ws=self.ws("T1"); wt=Path(ws["worktree"])
        self.assertEqual((wt/"a.txt").read_text(),"dirty\n")
        self.assertFalse((wt/"new.txt").exists())
        self.assertFalse((wt/"TBag"/"runs"/"r1").exists())

    def test_large_ambient_untracked_file_is_not_copied_to_mutating_worktree(self):
        self.register("T-JUNK")
        junk=self.project/"generated-native.node"; junk.write_bytes(b"x"*(2*1024*1024))
        ws=self.ws("T-JUNK"); wt=Path(ws["worktree"])
        self.assertFalse((wt/junk.name).exists())

    def test_required_worktree_fixture_is_mirrored_explicitly(self):
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixtures")
        fixture=self.project/"fixtures"/"sample.world"; fixture.parent.mkdir(); fixture.write_text("fixture\n")
        text="# T1\n\n## Required worktree fixtures\n- `fixtures/sample.world`\n"
        self.register("T1",text=text); ws=self.ws("T1"); wt=Path(ws["worktree"])
        self.assertEqual((wt/"fixtures"/"sample.world").read_text(),"fixture\n")
        self.assertEqual(ws["fixture_mirrors"],["fixtures/sample.world"])
        self.assertNotIn("fixtures/sample.world",git(wt,"status","--porcelain"))

    def test_required_worktree_fixture_can_provision_ignored_dependency_tree(self):
        (self.project/".gitignore").write_text("node_modules/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore deps")
        pkg=self.project/"node_modules"/"pkg"; pkg.mkdir(parents=True); (pkg/"index.js").write_text("module.exports=1\n")
        text="# T\n\n## Required worktree fixtures\n- `node_modules`\n"
        self.register("T-DEPS",text=text); ws=self.ws("T-DEPS"); wt=Path(ws["worktree"])
        self.assertEqual((wt/"node_modules"/"pkg"/"index.js").read_text(),"module.exports=1\n")
        self.assertIn("node_modules",ws["fixture_mirrors"])
        self.assertNotIn("node_modules",git(wt,"status","--porcelain"))

    def test_dependency_fixture_uses_shared_store_and_private_mutable_clone(self):
        (self.project/".gitignore").write_text("node_modules/\n"); (self.project/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
        git(self.project,"add",".gitignore","package-lock.json"); git(self.project,"commit","-qm","dependency authority")
        pkg=self.project/"node_modules"/"pkg"; pkg.mkdir(parents=True); (pkg/"index.js").write_text("module.exports=1\n")
        (self.project/"node_modules"/".package-lock.json").write_text('{"lockfileVersion":3}\n')
        text="# T\n\n## Required worktree fixtures\n- `node_modules`\n"
        self.register("T-DEPS-STORE",text=text); ws=self.ws("T-DEPS-STORE"); wt=Path(ws["worktree"])
        self.assertEqual(len(ws["fixture_bindings"]),1); binding=ws["fixture_bindings"][0]
        store=Path(binding["store_payload"]); self.assertTrue(store.is_dir()); self.assertIn("fixture-store",store.parts)
        self.assertFalse((wt/"node_modules").is_symlink()); self.assertNotEqual((wt/"node_modules").resolve(),store.resolve())
        self.assertEqual((wt/"node_modules"/"pkg"/"index.js").read_text(),"module.exports=1\n")
        self.assertIsNone(ws.get("fixture_snapshot_root")); self.assertEqual((store/"pkg"/"index.js").read_text(),"module.exports=1\n")
        (wt/"node_modules"/"pkg"/"index.js").write_text("mutated\n")
        self.assertEqual((store/"pkg"/"index.js").read_text(),"module.exports=1\n")
        dsd_workspace.refresh_task_fixtures(self.run,"P","T-DEPS-STORE")
        self.assertEqual((wt/"node_modules"/"pkg"/"index.js").read_text(),"module.exports=1\n")

    def test_dependency_fixture_lockfile_divergence_preserves_private_task_install(self):
        (self.project/".gitignore").write_text("node_modules/\n"); (self.project/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
        git(self.project,"add",".gitignore","package-lock.json"); git(self.project,"commit","-qm","dependency authority")
        pkg=self.project/"node_modules"/"pkg"; pkg.mkdir(parents=True); (pkg/"index.js").write_text("base\n")
        text="# T\n\n## Required worktree fixtures\n- `node_modules`\n"
        self.register("T-DEPS-DIVERGE",text=text); ws=self.ws("T-DEPS-DIVERGE"); wt=Path(ws["worktree"])
        (wt/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{"new":{}}}\n')
        (wt/"node_modules"/"pkg"/"index.js").write_text("task-install\n")
        refreshed=dsd_workspace.refresh_task_fixtures(self.run,"P","T-DEPS-DIVERGE")
        self.assertNotIn("node_modules",refreshed)
        self.assertEqual((wt/"node_modules"/"pkg"/"index.js").read_text(),"task-install\n")

    def test_required_fixture_must_be_git_ignored(self):
        fixture=self.project/"visible-fixture.txt"; fixture.write_text("input\n")
        with self.assertRaisesRegex(ValueError,"not ignored"):
            self.register("T-NOT-IGNORED",text="# T\n\n## Required worktree fixtures\n- `visible-fixture.txt`\n")

    def test_required_fixture_is_refreshed_between_attempts(self):
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixtures")
        fixture=self.project/"fixtures"/"sample.world"; fixture.parent.mkdir(); fixture.write_text("authoritative\n")
        text="# T\n\n## Required worktree fixtures\n- `fixtures/sample.world`\n"
        self.register("T-REFRESH",text=text); ws=self.ws("T-REFRESH"); wt=Path(ws["worktree"])
        (wt/"fixtures"/"sample.world").write_text("worker-mutated\n")
        fixture.write_text("later-primary-change\n")
        dsd_workspace.refresh_task_fixtures(self.run,"P","T-REFRESH")
        self.assertEqual((wt/"fixtures"/"sample.world").read_text(),"authoritative\n")
        self.assertEqual((Path(ws["fixture_snapshot_root"])/"fixtures"/"sample.world").read_text(),"authoritative\n")

    def test_required_fixture_symlink_cannot_escape_primary_checkout(self):
        outside=self.root/"outside.txt"; outside.write_text("secret\n")
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixtures")
        (self.project/"fixtures").mkdir(); (self.project/"fixtures"/"escape").symlink_to(outside)
        text="# T1\n\n## Required worktree fixtures\n- `fixtures/escape`\n"
        self.register("T1",text=text)
        with self.assertRaisesRegex(ValueError,"fixture symlink escapes primary checkout"):
            self.ws("T1")

    def test_missing_required_worktree_fixture_fails_during_plan_preflight(self):
        with self.assertRaisesRegex(ValueError,"required worktree fixture is absent"):
            self.register("T1",text="# T1\n\n## Required worktree fixtures\n- `fixtures/missing.world`\n")

    def test_read_only_analysis_tasks_share_one_frozen_project_view(self):
        self.register("A1",kind="analysis"); self.register("A2",kind="analysis")
        (self.project/"a.txt").write_text("tracked-dirty\n"); (self.project/"ambient.bin").write_bytes(b"x"*1024)
        w1=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        w2=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertEqual(w1["mode"],"analysis-view"); self.assertEqual(w2["mode"],"analysis-view")
        self.assertEqual(w1["worktree"],w2["worktree"]); self.assertNotEqual(w1["db"],w2["db"])
        self.assertEqual((Path(w1["worktree"])/"a.txt").read_text(),"tracked-dirty\n")
        self.assertFalse((Path(w1["worktree"])/"ambient.bin").exists())
        self.assertEqual(Path(w1["worktree"]).stat().st_mode & 0o222,0)
        self.assertEqual((Path(w1["worktree"])/"a.txt").stat().st_mode & 0o222,0)

    def test_ambient_untracked_change_does_not_rotate_analysis_view(self):
        self.register("A1",kind="analysis")
        (self.project/"ambient.bin").write_text("one\n")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        (self.project/"ambient.bin").write_text("two\n"); (self.project/"another.tmp").write_text("junk\n")
        self.register("A2",kind="analysis")
        second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertEqual(first["worktree"],second["worktree"])
        self.assertFalse((Path(second["worktree"])/"ambient.bin").exists())
        self.assertFalse((Path(second["worktree"])/"another.tmp").exists())

    def test_analysis_view_index_reset_self_heals_without_manual_rm_or_prune(self):
        self.register("A1",kind="analysis")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        first_path=Path(first["worktree"]); self.assertTrue(first_path.is_dir())
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A1"))
        # Simulate the field incident: metadata reset while derived view directories and
        # Git worktree administration still exist.
        dsd_workspace._write_analysis_view_index(self.run,{"format":dsd_workspace.ANALYSIS_VIEW_FORMAT,"next_generation":1,"views":[],"current":None})
        self.register("A2",kind="analysis")
        second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertTrue(Path(second["worktree"]).is_dir())
        self.assertNotEqual(Path(second["worktree"]).resolve(),first_path.resolve())
        self.assertFalse(first_path.exists())
        self.assertGreaterEqual(int(second["analysis_view_generation"]),2)

    def test_referenced_orphan_analysis_view_is_preserved_but_not_reused(self):
        self.register("A1",kind="analysis")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        first_path=Path(first["worktree"]); self.assertTrue(first_path.is_dir())
        dsd_workspace._write_analysis_view_index(self.run,{"format":dsd_workspace.ANALYSIS_VIEW_FORMAT,"next_generation":1,"views":[],"current":None})
        self.register("A2",kind="analysis")
        second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertTrue(first_path.is_dir())
        self.assertNotEqual(Path(second["worktree"]).resolve(),first_path.resolve())
        index=dsd_workspace._load_analysis_view_index(self.run)
        recovered=[x for x in index["views"] if str(Path(str(x.get("path"))).resolve())==str(first_path.resolve())]
        self.assertEqual(len(recovered),1); self.assertTrue(recovered[0]["stale"])

    def test_external_analysis_view_deletion_prunes_stale_git_admin_and_rebuilds(self):
        self.register("A1",kind="analysis")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        view=Path(first["worktree"]); self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A1"))
        dsd_workspace._make_tree_owner_writable(view)
        import shutil
        shutil.rmtree(view)
        self.register("A2",kind="analysis")
        second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertTrue(Path(second["worktree"]).is_dir())
        self.assertNotEqual(Path(second["worktree"]).resolve(),view.resolve())

    def test_analyst_diagnosis_of_mutating_task_uses_that_task_worktree(self):
        self.register("T1"); impl=dsd_workspace.prepare_launch_workspace(self.run,"P","T1","implementer")
        diag=dsd_workspace.prepare_launch_workspace(self.run,"P","T1","discovery")
        self.assertEqual(impl["mode"],"isolated-worktree"); self.assertEqual(diag["worktree"],impl["worktree"])

    def test_read_only_dependency_fixture_reuses_shared_view_without_fat_task_room(self):
        (self.project/".gitignore").write_text("node_modules/\n"); (self.project/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
        git(self.project,"add",".gitignore","package-lock.json"); git(self.project,"commit","-qm","dependency authority")
        pkg=self.project/"node_modules"/"pkg"; pkg.mkdir(parents=True); (pkg/"index.js").write_text("shared\n")
        (self.project/"node_modules"/".package-lock.json").write_text('{"lockfileVersion":3}\n')
        text="# A\n\n## Required worktree fixtures\n- `node_modules`\n"
        self.register("A-DEPS-1",kind="analysis",text=text); self.register("A-DEPS-2",kind="analysis",text=text)
        one=dsd_workspace.prepare_launch_workspace(self.run,"P","A-DEPS-1","discovery")
        two=dsd_workspace.prepare_launch_workspace(self.run,"P","A-DEPS-2","discovery")
        self.assertEqual(one["mode"],"analysis-view"); self.assertEqual(two["mode"],"analysis-view"); self.assertEqual(one["worktree"],two["worktree"])
        view=Path(one["worktree"]); link=view/"node_modules"; self.assertTrue(link.is_symlink())
        target=link.resolve(); self.assertIn("fixture-store",target.parts); self.assertNotEqual(target,self.project/"node_modules")
        self.assertEqual((link/"pkg"/"index.js").read_text(),"shared\n")
        self.assertFalse((dsd_task.task_root(self.run,"P","A-DEPS-1")/"fixture-snapshot").exists())
        self.assertFalse((dsd_task.task_root(self.run,"P","A-DEPS-2")/"fixture-snapshot").exists())
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A-DEPS-1")); self.assertTrue(link.exists())
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A-DEPS-2"))
        self.register("A-PLAIN",kind="analysis"); plain=dsd_workspace.prepare_launch_workspace(self.run,"P","A-PLAIN","discovery")
        self.assertNotEqual(plain["worktree"],one["worktree"])
        removed_views=dsd_workspace.gc_analysis_views(self.run); self.assertIn(str(view.resolve()),removed_views)
        removed=dsd_workspace.gc_fixture_store(self.run); self.assertTrue(removed); self.assertFalse(target.exists())

    def test_dependency_fixture_store_never_uses_a_sibling_task_room_as_source(self):
        (self.project/".gitignore").write_text("node_modules/\n"); (self.project/"package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
        git(self.project,"add",".gitignore","package-lock.json"); git(self.project,"commit","-qm","dependency authority")
        pkg=self.project/"node_modules"/"pkg"; pkg.mkdir(parents=True); (pkg/"index.js").write_text("primary\n")
        text="# T\n\n## Required worktree fixtures\n- `node_modules`\n"
        self.register("T-DEPS-A",text=text); self.register("T-DEPS-B",text=text)
        a=self.ws("T-DEPS-A"); b=self.ws("T-DEPS-B"); aw=Path(a["worktree"]); bw=Path(b["worktree"])
        self.assertFalse((aw/"node_modules").is_symlink()); self.assertFalse((bw/"node_modules").is_symlink())
        self.assertNotEqual((aw/"node_modules").resolve(),(bw/"node_modules").resolve())
        for ws in (a,b):
            source=Path(ws["fixture_bindings"][0]["store_payload"]).resolve()
            self.assertIn("fixture-store",source.parts); self.assertNotIn("worktrees",source.parts)
        (aw/"node_modules"/"pkg"/"index.js").write_text("task-a\n")
        self.assertEqual((bw/"node_modules"/"pkg"/"index.js").read_text(),"primary\n")

    def test_analysis_task_with_private_ignored_fixture_falls_back_to_isolated_worktree(self):
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixtures")
        fixture=self.project/"fixtures"/"sample.world"; fixture.parent.mkdir(); fixture.write_text("fixture\n")
        self.register("A-FIXTURE",kind="analysis",text="# A\n\n## Required worktree fixtures\n- `fixtures/sample.world`\n")
        ws=dsd_workspace.prepare_launch_workspace(self.run,"P","A-FIXTURE","discovery")
        self.assertEqual(ws["mode"],"isolated-worktree"); self.assertEqual((Path(ws["worktree"])/"fixtures"/"sample.world").read_text(),"fixture\n")

    def test_primary_integration_invalidates_shared_analysis_view_for_new_tasks(self):
        self.register("A1",kind="analysis"); first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        self.register("T1"); mutable=dsd_workspace.prepare_launch_workspace(self.run,"P","T1","implementer"); (Path(mutable["worktree"])/"a.txt").write_text("changed\n"); self.accept("T1")
        class A: pass
        x=A(); x.run_root=self.run; x.phase_id="P"; x.task_id="T1"; out=dsd_workspace.command_integrate(x); self.assertTrue(out["changed"])
        self.register("A2",kind="analysis"); second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertNotEqual(first["worktree"],second["worktree"]); self.assertEqual((Path(second["worktree"])/"a.txt").read_text(),"changed\n")
        self.assertTrue(Path(first["worktree"]).exists())  # A1 still references its stable old generation.
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A1"))
        removed=dsd_workspace.gc_analysis_views(self.run); self.assertIn(str(Path(first["worktree"]).resolve()),removed); self.assertFalse(Path(first["worktree"]).exists())

    def test_accepted_analysis_releases_task_db_and_shared_view_binding(self):
        self.register("A1",kind="analysis"); ws=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery"); db=Path(ws["db"]); db.write_text("db")
        event=dsd_task.task_root(self.run,"P","A1")/"attempts"/"discovery-1"; event.mkdir(parents=True); report=event/"report.md"; report.write_text("analysis\n")
        task=dsd_task.load_task(self.run,"P","A1"); task["attempts"].append({"task_id":"A1","role":"discovery","tier":"analyst","status":"gated","event_dir":str(event)}); task["status"]="active"; dsd_task.write_json(dsd_task.task_file(self.run,"P","A1"),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="A1"; a.report=report; out=dsd_task.command_accept(a)
        self.assertTrue(out["runtime_released"]); self.assertFalse(db.exists()); self.assertTrue(dsd_workspace.load_workspace(self.run,"P","A1")["released"])


    def test_released_read_only_binding_reacquires_current_shared_view(self):
        self.register("A1",kind="analysis")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A1"))
        rebound=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        self.assertEqual(rebound["mode"],"analysis-view")
        self.assertEqual(rebound["worktree"],first["worktree"])
        self.assertFalse(rebound.get("released"))

    def test_out_of_band_primary_commit_rotates_analysis_view(self):
        self.register("A1",kind="analysis")
        first=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        (self.project/"a.txt").write_text("external-commit\n")
        git(self.project,"add","a.txt"); git(self.project,"commit","-qm","external")
        self.register("A2",kind="analysis")
        second=dsd_workspace.prepare_launch_workspace(self.run,"P","A2","discovery")
        self.assertNotEqual(first["worktree"],second["worktree"])
        self.assertEqual((Path(second["worktree"])/"a.txt").read_text(),"external-commit\n")
        self.assertTrue(Path(first["worktree"]).exists())  # A1 still owns its stable old view.

    def test_phase_cleanup_drops_unreferenced_current_analysis_view(self):
        self.register("A1",kind="analysis")
        ws=dsd_workspace.prepare_launch_workspace(self.run,"P","A1","discovery")
        view=Path(ws["worktree"])
        task=dsd_task.load_task(self.run,"P","A1"); task["status"]="accepted"; dsd_task.write_json(dsd_task.task_file(self.run,"P","A1"),task)
        self.assertTrue(dsd_task.release_read_only_runtime(self.run,"P","A1"))
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"
        out=dsd_workspace.command_cleanup_phase(a)
        self.assertIn(str(view.resolve()),out["analysis_views_removed"])
        self.assertFalse(view.exists())

    def test_independent_worktrees_do_not_share_changes(self):
        self.register("T1"); self.register("T2"); w1=Path(self.ws("T1")["worktree"]); w2=Path(self.ws("T2")["worktree"])
        (w1/"a.txt").write_text("one\n")
        self.assertEqual((w2/"a.txt").read_text(),"alpha\n"); self.assertEqual((self.project/"a.txt").read_text(),"alpha\n")

    def test_scope_means_movement_since_checkpoint(self):
        self.register("T1"); ws=self.ws("T1")
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1";a.label="implementer-1";ref=dsd_workspace.command_checkpoint(a)["checkpoint_ref"]
        baseline=scope_snapshot.capture(Path(ws["worktree"]),ref); (Path(ws["worktree"])/"a.txt").write_text("changed\n")
        comp=scope_snapshot.compare(Path(ws["worktree"]),baseline)
        self.assertIn("a.txt",comp["changed_since_attempt_baseline"]); self.assertNotIn("unchanged",comp)

    def test_carry_forward_survives_predecessor_cleanup_and_preserves_untracked_delta(self):
        self.register("OLD-CARRY"); old=self.ws("OLD-CARRY"); wt=Path(old["worktree"])
        (wt/"a.txt").write_text("carried tracked\n"); (wt/"new-carried.txt").write_text("carried untracked\n")
        out=self.register_replacement("NEW-CARRY","OLD-CARRY")
        self.assertEqual(out["carry_forward"],{"NEW-CARRY":"OLD-CARRY"})
        task=dsd_task.load_task(self.run,"P","NEW-CARRY"); self.assertTrue(Path(task["carry_forward_patch"]).is_file())
        class A: pass
        clean=A();clean.run_root=self.run;clean.phase_id="P";clean.task_id="OLD-CARRY";clean.force=False;dsd_workspace.command_cleanup(clean)
        self.assertFalse(Path(old["worktree"]).exists())
        fresh=self.ws("NEW-CARRY"); new_wt=Path(fresh["worktree"])
        self.assertEqual(fresh["carry_from"],"OLD-CARRY")
        self.assertEqual((new_wt/"a.txt").read_text(),"carried tracked\n"); self.assertEqual((new_wt/"new-carried.txt").read_text(),"carried untracked\n")

    def test_cleanup_refuses_superseded_workspace_until_successor_integrates_or_captures_carry(self):
        self.register("OLD-RETAIN"); old=self.ws("OLD-RETAIN"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("unintegrated predecessor delta\n")
        class A: pass
        sup=A(); sup.run_root=self.run; sup.phase_id="P"; sup.task_id="OLD-RETAIN"; sup.by="NEW-RETAIN"
        dsd_task.command_supersede(sup)
        clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="OLD-RETAIN"; clean.force=False
        with self.assertRaisesRegex(ValueError,"unintegrated delta with no durable disposition"):
            dsd_workspace.command_cleanup(clean)
        self.assertTrue(wt.exists())
        out=self.register_replacement("NEW-RETAIN","OLD-RETAIN")
        self.assertEqual(out["carry_forward"],{"NEW-RETAIN":"OLD-RETAIN"})
        dsd_workspace.command_cleanup(clean)
        self.assertFalse(wt.exists())

    def test_registered_successor_without_carry_keeps_predecessor_workspace_retained(self):
        self.register("OLD-REGISTERED-RETAIN"); old=self.ws("OLD-REGISTERED-RETAIN"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("registered successor still needs predecessor safety\n")
        self.register("NEW-REGISTERED-RETAIN")
        class A: pass
        sup=A(); sup.run_root=self.run; sup.phase_id="P"; sup.task_id="OLD-REGISTERED-RETAIN"; sup.by="NEW-REGISTERED-RETAIN"
        dsd_task.command_supersede(sup)
        for forced in (False, True):
            clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="OLD-REGISTERED-RETAIN"; clean.force=forced
            with self.assertRaisesRegex(ValueError,"unintegrated delta with no durable disposition"):
                dsd_workspace.command_cleanup(clean)
            self.assertTrue(wt.exists())
        phase=A(); phase.run_root=self.run; phase.phase_id="P"
        out=dsd_workspace.command_cleanup_phase(phase)
        skipped={row["task_id"]:row["reason"] for row in out["skipped"]}
        self.assertIn("unintegrated delta with no durable disposition",skipped["OLD-REGISTERED-RETAIN"])
        self.assertTrue(wt.exists())

    def test_force_cannot_destroy_superseded_workspace_before_carry_is_durable(self):
        self.register("OLD-FORCE-RETAIN"); old=self.ws("OLD-FORCE-RETAIN"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("must survive forced cleanup\n")
        class A: pass
        sup=A(); sup.run_root=self.run; sup.phase_id="P"; sup.task_id="OLD-FORCE-RETAIN"; sup.by="NEW-FORCE-RETAIN"
        dsd_task.command_supersede(sup)
        clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="OLD-FORCE-RETAIN"; clean.force=True
        with self.assertRaisesRegex(ValueError,"unintegrated delta with no durable disposition"):
            dsd_workspace.command_cleanup(clean)
        self.assertTrue(wt.exists())

    def test_cleanup_allows_superseded_workspace_after_all_successors_integrated(self):
        self.register("OLD-DONE"); old=self.ws("OLD-DONE"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("discarded predecessor delta\n")
        self.register_replacement("NEW-DONE","OLD-DONE",carry=False)
        successor=dsd_task.load_task(self.run,"P","NEW-DONE"); successor["status"]="integrated"; dsd_task.write_json(dsd_task.task_file(self.run,"P","NEW-DONE"),successor)
        class A: pass
        clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="OLD-DONE"; clean.force=False
        dsd_workspace.command_cleanup(clean)
        self.assertFalse(wt.exists())

    def test_replacement_plan_cannot_silently_drop_retained_predecessor_delta(self):
        self.register("OLD-OMITTED-CARRY"); old=self.ws("OLD-OMITTED-CARRY"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("valuable unintegrated delta\n")
        with self.assertRaisesRegex(ValueError,"Choose carry_from: OLD-OMITTED-CARRY.*rederive_from_primary"):
            self.register_replacement("NEW-OMITTED-CARRY","OLD-OMITTED-CARRY",carry=False,rederive=False)
        self.assertEqual(dsd_task.load_task(self.run,"P","OLD-OMITTED-CARRY")["status"],"planned")
        self.assertTrue(wt.exists())

    def test_replacement_plan_may_explicitly_rederive_and_release_predecessor_delta_immediately(self):
        self.register("OLD-REDERIVE"); old=self.ws("OLD-REDERIVE"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("intentionally discarded delta\n")
        out=self.register_replacement("NEW-REDERIVE","OLD-REDERIVE",carry=False,rederive=True)
        self.assertEqual(out.get("carry_forward"),{})
        self.assertEqual(dsd_task.load_task(self.run,"P","OLD-REDERIVE")["status"],"superseded")
        self.assertTrue(wt.exists())
        class A: pass
        clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="OLD-REDERIVE"; clean.force=False; clean.reason=None
        result=dsd_workspace.command_cleanup(clean)
        self.assertEqual(result["reason"],"analyst-explicit-rederive")
        self.assertFalse(wt.exists())

    def test_carry_forward_respects_replacement_write_boundary(self):
        self.register("OLD-SCOPE"); wt=Path(self.ws("OLD-SCOPE")["worktree"]); (wt/"a.txt").write_text("outside scope\n")
        text="# NEW-SCOPE\n\n## Allowed source changes\n- `b.txt`\n"
        with self.assertRaisesRegex(ValueError,"outside this replacement's explicit Allowed source changes"):
            self.register_replacement("NEW-SCOPE","OLD-SCOPE",text=text)
        self.assertNotEqual(dsd_task.load_task(self.run,"P","OLD-SCOPE")["status"],"superseded")

    def test_carry_forward_accepts_directory_tree_spelling_as_prefix(self):
        self.register("OLD-TREE"); wt=Path(self.ws("OLD-TREE")["worktree"]); (wt/"src").mkdir(); (wt/"src"/"nested.txt").write_text("carried\n")
        text="# NEW-TREE\n\n## Allowed source changes\n- `src/**`\n"
        out=self.register_replacement("NEW-TREE","OLD-TREE",text=text)
        self.assertEqual(out["carry_forward"],{"NEW-TREE":"OLD-TREE"})


    def test_carry_forward_conflict_with_new_primary_fails_closed(self):
        self.register("OLD-CONFLICT"); old=self.ws("OLD-CONFLICT"); wt=Path(old["worktree"]); (wt/"a.txt").write_text("predecessor version\n")
        self.register_replacement("NEW-CONFLICT","OLD-CONFLICT")
        (self.project/"a.txt").write_text("new primary version\n"); git(self.project,"add","a.txt"); git(self.project,"commit","-qm","primary changes same path")
        with self.assertRaisesRegex(ValueError,"routed to needs-analysis"):
            self.ws("NEW-CONFLICT")
        routed=dsd_task.load_task(self.run,"P","NEW-CONFLICT"); self.assertEqual(routed["status"],"needs-analysis")
        evidence=Path(routed["last_workspace_conflict"]["evidence"]); self.assertTrue(evidence.is_file()); self.assertEqual(json.loads(evidence.read_text())["carry_from"],"OLD-CONFLICT")

    def test_integrate_uses_merge_base_after_clean_task_rebase(self):
        self.register("T-REBASE"); ws=self.ws("T-REBASE"); wt=Path(ws["worktree"])
        (wt/"a.txt").write_text("task-change\n"); git(wt,"add","a.txt"); git(wt,"commit","-qm","task change")
        (self.project/"b.txt").write_text("primary-moved\n"); git(self.project,"add","b.txt"); git(self.project,"commit","-qm","primary move")
        primary_head=git(self.project,"rev-parse","HEAD")
        git(wt,"rebase","--onto",primary_head,ws["baseline_branch"],ws["task_branch"])
        self.accept("T-REBASE")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-REBASE"
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out["rebased_baseline_fallback"]); self.assertEqual((self.project/"a.txt").read_text(),"task-change\n"); self.assertEqual((self.project/"b.txt").read_text(),"primary-moved\n")

    def test_integrate_applies_only_task_delta_not_preexisting_dirty(self):
        (self.project/"b.txt").write_text("owner-dirty\n"); self.register("T1"); ws=self.ws("T1"); wt=Path(ws["worktree"]); (wt/"a.txt").write_text("task-change\n"); self.accept("T1")
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1";out=dsd_workspace.command_integrate(a)
        self.assertEqual(out["status"],"integrated"); self.assertTrue(out["changed"]); self.assertNotIn("verification_note",out); self.assertNotIn("integrated_state_verification_policy",out)
        self.assertEqual((self.project/"a.txt").read_text(),"task-change\n"); self.assertEqual((self.project/"b.txt").read_text(),"owner-dirty\n")

    def test_integration_accepts_byte_identical_ambient_untracked_path_as_already_applied(self):
        owner=self.project/"owner-identical.txt"; owner.write_text("same-bytes\n")
        self.register("T-UNTRACKED-IDENTICAL"); ws=self.ws("T-UNTRACKED-IDENTICAL"); wt=Path(ws["worktree"])
        self.assertFalse((wt/"owner-identical.txt").exists())
        (wt/"owner-identical.txt").write_text("same-bytes\n")
        self.accept("T-UNTRACKED-IDENTICAL")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-UNTRACKED-IDENTICAL"
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out["already_applied"]); self.assertFalse(out["changed"])
        self.assertEqual(owner.read_text(),"same-bytes\n")
        self.assertEqual(dsd_task.load_task(self.run,"P","T-UNTRACKED-IDENTICAL")["status"],"integrated")

    def test_integration_refuses_to_overwrite_preexisting_ambient_untracked_path(self):
        owner=self.project/"owner-local.txt"; owner.write_text("owner-local\n")
        self.register("T-UNTRACKED-COLLISION"); ws=self.ws("T-UNTRACKED-COLLISION"); wt=Path(ws["worktree"])
        self.assertFalse((wt/"owner-local.txt").exists())
        (wt/"owner-local.txt").write_text("task-version\n")
        self.accept("T-UNTRACKED-COLLISION")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="T-UNTRACKED-COLLISION"
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out["integration_conflict"]); self.assertEqual(out["status"],"needs-analysis")
        self.assertTrue(out["acceptance_preserved"]); self.assertEqual(out["next_action"],"diagnose-or-fix-primary-precondition-then-retry-integrate")
        self.assertTrue(Path(out["evidence"]).is_file())
        self.assertEqual(owner.read_text(),"owner-local\n")
        # Fixing a purely primary-tree precondition does not invalidate the reviewed task ref.
        owner.unlink()
        retried=dsd_workspace.command_integrate(a)
        self.assertTrue(retried["changed"]); self.assertTrue(retried["retried_prior_integration_conflict"])
        self.assertEqual((self.project/"owner-local.txt").read_text(),"task-version\n")
        self.assertEqual(dsd_task.load_task(self.run,"P","T-UNTRACKED-COLLISION")["status"],"integrated")

    def test_conflicting_integrations_fail_without_overwriting_primary(self):
        self.register("T1");self.register("T2");w1=Path(self.ws("T1")["worktree"]);w2=Path(self.ws("T2")["worktree"])
        (w1/"a.txt").write_text("one\n");(w2/"a.txt").write_text("two\n");self.accept("T1");self.accept("T2")
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1";dsd_workspace.command_integrate(a)
        a.task_id="T2"
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out["integration_conflict"]); self.assertEqual(out["next_action"],"diagnose-or-fix-primary-precondition-then-retry-integrate")
        self.assertTrue(out["acceptance_preserved"])
        state=dsd_task.load_task(self.run,"P","T2"); self.assertEqual(state["status"],"needs-analysis")
        self.assertTrue(Path(state["last_integration_conflict"]["evidence"]).is_file())
        r=A(); r.run_root=self.run; r.phase_id="P"; r.no_sweep=True
        reconciled=dsd_task.command_reconcile_run(r)
        self.assertTrue(any(x.get("task_id")=="T2" and x.get("action")=="launch-analyst-discovery" for x in reconciled["first_useful_actions"]),reconciled)
        self.assertFalse(any(x.get("task_id")=="T2" and x.get("action")=="integrate-accepted-task" for x in reconciled.get("first_useful_actions",[])),reconciled)
        self.assertEqual((self.project/"a.txt").read_text(),"one\n")


    def test_integrated_ignored_addition_is_carried_into_declared_dependent_workspace(self):
        (self.project/".gitignore").write_text("ignored/\n")
        git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore generated-like tree")
        self.register("IGNORED-PRODUCER"); ws1=self.ws("IGNORED-PRODUCER"); wt1=Path(ws1["worktree"])
        added=wt1/"ignored"/"NarrativeEvidenceViewBuilder.ts"; added.parent.mkdir(); added.write_text("export const builder = 1;\n")
        # Simulate a worker explicitly authoring an ignored production file. Once it is
        # part of the reviewed checkpoint, ignore rules must not make it disappear from
        # dependency state.
        git(wt1,"add","-f","ignored/NarrativeEvidenceViewBuilder.ts")
        self.accept("IGNORED-PRODUCER")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="IGNORED-PRODUCER"
        out=dsd_workspace.command_integrate(a); self.assertTrue(out["changed"],out)
        self.assertTrue((self.project/"ignored/NarrativeEvidenceViewBuilder.ts").is_file())
        self.assertIn(b"NarrativeEvidenceViewBuilder.ts",(dsd_task.task_root(self.run,"P","IGNORED-PRODUCER")/"accepted.patch").read_bytes())
        producer=dsd_task.load_task(self.run,"P","IGNORED-PRODUCER")
        self.assertIn("ignored/NarrativeEvidenceViewBuilder.ts",producer.get("integration_untracked_paths",[]))
        c=A(); c.run_root=self.run; c.phase_id="P"; c.task_id="IGNORED-PRODUCER"; c.force=False; dsd_workspace.command_cleanup(c)

        self.register("IGNORED-CONSUMER"); state=dsd_task.load_task(self.run,"P","IGNORED-CONSUMER"); state["dependencies"]=["IGNORED-PRODUCER"]; dsd_task.write_json(dsd_task.task_file(self.run,"P","IGNORED-CONSUMER"),state)
        ws2=self.ws("IGNORED-CONSUMER"); wt2=Path(ws2["worktree"])
        self.assertEqual((wt2/"ignored/NarrativeEvidenceViewBuilder.ts").read_text(),"export const builder = 1;\n")
        self.assertEqual(ws2.get("integrated_primary_inputs"),[{"path":"ignored/NarrativeEvidenceViewBuilder.ts","producer_phase":"P","producer_task":"IGNORED-PRODUCER"}])
        self.assertEqual(git(wt2,"ls-files","--","ignored/NarrativeEvidenceViewBuilder.ts"),"ignored/NarrativeEvidenceViewBuilder.ts")

    def test_integrate_does_not_claim_success_if_reviewed_patch_is_not_fully_materialized(self):
        self.register("MATERIALIZE"); ws=self.ws("MATERIALIZE"); wt=Path(ws["worktree"]); (wt/"new-file.txt").write_text("reviewed\n"); self.accept("MATERIALIZE")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="MATERIALIZE"
        original=dsd_workspace.run_cmd; sabotaged={"done":False}
        def run_with_loss(cmd,cwd,*,input_bytes=None,check=True):
            cp=original(cmd,cwd,input_bytes=input_bytes,check=check)
            if cwd==self.project and len(cmd)==3 and cmd[:2]==["git","apply"] and not sabotaged["done"]:
                sabotaged["done"]=True
                (self.project/"new-file.txt").unlink(missing_ok=True)
            return cp
        dsd_workspace.run_cmd=run_with_loss
        try:
            out=dsd_workspace.command_integrate(a)
        finally:
            dsd_workspace.run_cmd=original
        self.assertTrue(out["integration_conflict"],out); self.assertEqual(out["status"],"needs-analysis")
        self.assertEqual(json.loads(Path(out["evidence"]).read_text())["kind"],"integration-materialization-mismatch")
        self.assertEqual(dsd_task.load_task(self.run,"P","MATERIALIZE")["status"],"needs-analysis")

    def test_dependent_workspace_inherits_only_tbag_integrated_untracked_outputs(self):
        self.register("PRODUCER"); ws1=self.ws("PRODUCER"); wt1=Path(ws1["worktree"]); (wt1/"authority.json").write_text("v1\n"); self.accept("PRODUCER")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="PRODUCER"
        first=dsd_workspace.command_integrate(a); self.assertTrue(first["changed"]); self.assertTrue((self.project/"authority.json").is_file())
        producer=dsd_task.load_task(self.run,"P","PRODUCER"); self.assertIn("authority.json",producer.get("integration_untracked_paths",[]))
        # An unrelated ambient untracked file must remain excluded.
        (self.project/"owner-note.txt").write_text("owner only\n")
        self.register("CONSUMER")
        ws2=self.ws("CONSUMER"); wt2=Path(ws2["worktree"]); self.assertEqual((wt2/"authority.json").read_text(),"v1\n"); self.assertFalse((wt2/"owner-note.txt").exists())
        self.assertEqual(ws2.get("integrated_primary_inputs"),[{"path":"authority.json","producer_phase":"P","producer_task":"PRODUCER"}])
        # The dependency output is now part of the consumer baseline, so editing it
        # integrates as a normal modification instead of colliding with an unseen file.
        (wt2/"authority.json").write_text("v2\n"); self.accept("CONSUMER"); a.task_id="CONSUMER"
        second=dsd_workspace.command_integrate(a); self.assertTrue(second["changed"]); self.assertEqual((self.project/"authority.json").read_text(),"v2\n")

    def test_dependent_workspace_inherits_current_primary_bytes_for_known_tbag_untracked_path(self):
        self.register("PRODUCER-DRIFT"); ws1=self.ws("PRODUCER-DRIFT"); wt1=Path(ws1["worktree"]); (wt1/"authority-drift.json").write_text("reviewed\n"); self.accept("PRODUCER-DRIFT")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="PRODUCER-DRIFT"; dsd_workspace.command_integrate(a)
        # Once T-BAG established this untracked path as project output, primary is
        # current authority just as it is for tracked dirty state. Owner edits should
        # be visible to declared dependents, not hidden until a later conflict.
        (self.project/"authority-drift.json").write_text("owner-current\n")
        self.register("CONSUMER-DRIFT")
        ws2=self.ws("CONSUMER-DRIFT"); self.assertEqual((Path(ws2["worktree"])/"authority-drift.json").read_text(),"owner-current\n")

    def test_stale_workspace_divergent_untracked_conflict_identifies_prior_tbag_producer(self):
        self.register("INDEPENDENT"); ws2=self.ws("INDEPENDENT"); wt2=Path(ws2["worktree"]); self.assertFalse((wt2/"shared.json").exists())
        self.register("PRODUCER2"); ws1=self.ws("PRODUCER2"); wt1=Path(ws1["worktree"]); (wt1/"shared.json").write_text("producer\n"); self.accept("PRODUCER2")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="PRODUCER2"; dsd_workspace.command_integrate(a)
        (wt2/"shared.json").write_text("different\n"); self.accept("INDEPENDENT"); a.task_id="INDEPENDENT"
        out=dsd_workspace.command_integrate(a); self.assertTrue(out["integration_conflict"]); self.assertEqual(out["status"],"needs-analysis")
        evidence=json.loads(Path(out["evidence"]).read_text()); self.assertEqual(evidence["kind"],"divergent-untracked-authority"); self.assertEqual(evidence["untracked_collisions"],["shared.json"]); self.assertEqual(evidence["known_tbag_producers"].get("shared.json"),["P/PRODUCER2"])

    def test_integration_refuses_post_review_mutation(self):
        self.register("T1"); ws=self.ws("T1"); wt=Path(ws["worktree"]); (wt/"a.txt").write_text("reviewed\n"); self.accept("T1")
        (wt/"a.txt").write_text("changed-after-review\n")
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1"
        with self.assertRaises(ValueError): dsd_workspace.command_integrate(a)
        self.assertEqual((self.project/"a.txt").read_text(),"alpha\n")


    def test_forced_cleanup_retires_workspace_binding_and_allows_clean_recreate(self):
        self.register("FORCE-RECREATE"); first=self.ws("FORCE-RECREATE"); old_wt=Path(first["worktree"]); self.assertTrue(old_wt.is_dir())
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="FORCE-RECREATE"; a.force=True; a.reason="explicit test abandonment"
        dsd_workspace.command_cleanup(a)
        self.assertFalse(dsd_workspace.workspace_path(self.run,"P","FORCE-RECREATE").exists()); self.assertNotIn("workspace",dsd_task.load_task(self.run,"P","FORCE-RECREATE"))
        second=self.ws("FORCE-RECREATE"); self.assertTrue(Path(second["worktree"]).is_dir()); self.assertNotEqual(second["created_at"],first["created_at"])

    def test_shared_analysis_view_includes_cross_phase_integrated_untracked_primary_state(self):
        self.register("CROSS-PRODUCER"); ws=self.ws("CROSS-PRODUCER"); wt=Path(ws["worktree"]); (wt/"cross-phase.json").write_text("integrated\n"); self.accept("CROSS-PRODUCER")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="CROSS-PRODUCER"; dsd_workspace.command_integrate(a)
        brief=self.run/"cross-analysis.md"; brief.write_text("# Cross phase analysis\n")
        d=A(); d.run_root=self.run; d.phase_id="Q"; d.task_id="READ-CROSS"; d.brief=brief; d.kind="analysis"; d.role="discovery"; d.tier="analyst"; d.dependency=[]; d.requires_integration=False; d.reviews_task=None; d.owner_authority=None
        dsd_task.command_register_direct(d)
        view=dsd_workspace.prepare_launch_workspace(self.run,"Q","READ-CROSS","discovery"); root=Path(view["worktree"])
        self.assertEqual((root/"cross-phase.json").read_text(),"integrated\n")
        self.assertEqual(git(root,"ls-files","--","cross-phase.json"),"cross-phase.json")

    def test_cleanup_refuses_accepted_but_unintegrated_implementation(self):
        self.register("T1"); self.ws("T1"); self.accept("T1")
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1";a.force=False
        with self.assertRaisesRegex(ValueError,"not integrated"): dsd_workspace.command_cleanup(a)
        self.assertTrue(Path(dsd_workspace.load_workspace(self.run,"P","T1")["worktree"]).exists())

    def test_cleanup_t1_does_not_delete_t10_branches(self):
        self.register("T1"); self.register("T10"); self.ws("T1"); ws10=self.ws("T10")
        p=dsd_task.task_file(self.run,"P","T1"); t=dsd_task.load_json(p); t["status"]="superseded"; dsd_task.write_json(p,t)
        Path(self.run/"phases/P/tasks/T1/workspace.json").exists()
        class A:pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T1";a.force=False;dsd_workspace.command_cleanup(a)
        refs=git(self.project,"for-each-ref","--format=%(refname:short)","refs/heads").splitlines()
        self.assertIn(ws10["task_branch"],refs)
        self.assertNotIn("dsd/r1/P/T1",refs); self.assertNotIn("dsd/r1/P/T1-base",refs)

    def test_automatic_cleanup_refuses_corrupted_out_of_run_targets(self):
        self.register("OWNED",kind="analysis"); self.ws("OWNED")
        state=dsd_task.load_task(self.run,"P","OWNED"); state["status"]="accepted"; dsd_task.write_json(dsd_task.task_file(self.run,"P","OWNED"),state)
        ws_path=dsd_workspace.workspace_path(self.run,"P","OWNED"); ws=dsd_task.load_json(ws_path); victim=self.root/"victim.sqlite"; victim.write_text("keep")
        ws["db"]=str(victim); dsd_task.write_json(ws_path,ws)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="OWNED"; a.force=False; a.reason=None
        with self.assertRaisesRegex(ValueError,"outside its exact run-owned location"):
            dsd_workspace.command_cleanup(a)
        self.assertEqual(victim.read_text(),"keep")

    def test_cleanup_removes_task_db_and_sqlite_sidecars(self):
        self.register("T4", kind="analysis")
        self.ws("T4"); task=dsd_task.load_task(self.run,"P","T4"); task["status"]="accepted"; dsd_task.write_json(dsd_task.task_file(self.run,"P","T4"),task)
        ws=dsd_workspace.load_workspace(self.run,"P","T4"); db=Path(ws["db"]); db.parent.mkdir(parents=True,exist_ok=True)
        for pth in (db,Path(str(db)+"-wal"),Path(str(db)+"-shm")): pth.write_text("x")
        class A: pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T4";a.force=False;dsd_workspace.command_cleanup(a)
        for pth in (db,Path(str(db)+"-wal"),Path(str(db)+"-shm")): self.assertFalse(pth.exists())

    def test_closed_task_db_is_deleted_and_next_task_uses_fresh_db(self):
        self.register("T4", kind="analysis"); ws4=self.ws("T4")
        task=dsd_task.load_task(self.run,"P","T4"); task["status"]="accepted"; dsd_task.write_json(dsd_task.task_file(self.run,"P","T4"),task)
        db4=Path(ws4["db"]); db4.parent.mkdir(parents=True,exist_ok=True); db4.write_text("session-four")
        class A: pass
        a=A();a.run_root=self.run;a.phase_id="P";a.task_id="T4";a.force=False;dsd_workspace.command_cleanup(a)
        self.assertFalse(db4.exists())

        self.register("T5", kind="analysis"); ws5=self.ws("T5"); db5=Path(ws5["db"])
        self.assertNotEqual(db4,db5)
        self.assertFalse(db5.exists())

    def test_integrated_task_automatically_retires_worktree_fixture_snapshot_and_db(self):
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixture")
        fixture=self.project/"fixtures"/"deps"; fixture.mkdir(parents=True); (fixture/"cache.bin").write_text("input\n")
        self.register("AUTO-CLEAN",text="# AUTO\n\n## Required worktree fixtures\n- `fixtures/deps`\n")
        ws=self.ws("AUTO-CLEAN"); wt=Path(ws["worktree"]); db=Path(ws["db"]); snapshot=Path(ws["fixture_snapshot_root"]); db.write_text("db")
        Path(str(db)+"-wal").write_text("wal"); Path(str(db)+"-shm").write_text("shm")
        (wt/"a.txt").write_text("integrated\n"); self.accept("AUTO-CLEAN")
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id="P"; a.task_id="AUTO-CLEAN"
        out=dsd_workspace.command_integrate(a)
        self.assertTrue(out.get("runtime_cleaned"),out); self.assertFalse(wt.exists()); self.assertFalse(snapshot.exists())
        self.assertFalse(db.exists()); self.assertFalse(Path(str(db)+"-wal").exists()); self.assertFalse(Path(str(db)+"-shm").exists())
        state=dsd_task.load_task(self.run,"P","AUTO-CLEAN"); self.assertEqual(state["workspace_cleanup_reason"],"reviewed-delta-integrated"); self.assertNotIn("workspace",state)

    def test_superseded_readonly_fixture_room_releases_without_successor_integration(self):
        (self.project/".gitignore").write_text("fixtures/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore fixture")
        fixture=self.project/"fixtures"/"analysis.bin"; fixture.parent.mkdir(); fixture.write_text("input\n")
        self.register("READ-OLD",kind="analysis",text="# A\n\n## Required worktree fixtures\n- `fixtures/analysis.bin`\n")
        ws=dsd_workspace.prepare_launch_workspace(self.run,"P","READ-OLD","discovery"); wt=Path(ws["worktree"]); self.assertEqual(ws["mode"],"isolated-worktree")
        class A: pass
        sup=A(); sup.run_root=self.run; sup.phase_id="P"; sup.task_id="READ-OLD"; sup.by="READ-NEW"; dsd_task.command_supersede(sup)
        clean=A(); clean.run_root=self.run; clean.phase_id="P"; clean.task_id="READ-OLD"; clean.force=False; clean.reason=None
        out=dsd_workspace.command_cleanup(clean)
        self.assertEqual(out["reason"],"non-mutating-result-is-durable"); self.assertFalse(wt.exists())

    def test_launcher_fixture_changes_are_excluded_from_scope_and_checkpoint(self):
        (self.project/".gitignore").write_text("node_modules/\n"); git(self.project,"add",".gitignore"); git(self.project,"commit","-qm","ignore deps")
        fixture=self.project/"node_modules"/"pkg"; fixture.mkdir(parents=True); (fixture/"index.js").write_text("input\n")
        self.register("FIXTURE-SCOPE",text="# T\n\n## Required worktree fixtures\n- `node_modules`\n")
        ws=self.ws("FIXTURE-SCOPE"); wt=Path(ws["worktree"]);
        class A: pass
        c=A(); c.run_root=self.run; c.phase_id="P"; c.task_id="FIXTURE-SCOPE"; c.label="impl"; ref=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        baseline=scope_snapshot.capture(wt,ref,["node_modules"]); (wt/"node_modules/pkg/index.js").write_text("worker-cache-change\n")
        comp=scope_snapshot.compare(wt,baseline); self.assertEqual(comp["changed_since_attempt_baseline"],[])
        c.label="review"; reviewed=dsd_workspace.command_checkpoint(c)["checkpoint_ref"]
        self.assertEqual(git(wt,"diff","--name-only",f"{ref}..{reviewed}"),"")

    def test_clean_room_refresh_detects_second_edit_to_already_dirty_primary_path(self):
        (self.project/"a.txt").write_text("owner-dirty-v1\n")
        self.register("DIRTY-REFRESH"); ws=self.ws("DIRTY-REFRESH"); wt=Path(ws["worktree"]); self.assertEqual((wt/"a.txt").read_text(),"owner-dirty-v1\n")
        # Same porcelain status (' M a.txt'), different bytes. Old HEAD+status markers missed this.
        (self.project/"a.txt").write_text("owner-dirty-v2\n")
        out=dsd_workspace.refresh_clean_task_workspace(self.run,"P","DIRTY-REFRESH")
        self.assertTrue(out["refreshed"],out); self.assertEqual((wt/"a.txt").read_text(),"owner-dirty-v2\n")

    def test_cleanup_phase_cli_does_not_require_task_id(self):
        cp=subprocess.run([sys.executable,str(SCRIPTS/"dsd_workspace.py"),"cleanup-phase","--run-root",str(self.run),"--phase-id","P"],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertEqual(json.loads(cp.stdout)["phase_id"],"P")

    def test_phase_cleanup_skips_unfinished_and_sweeps_orphan_sidecars(self):
        self.register("DONE", kind="analysis"); self.ws("DONE")
        done=dsd_task.load_task(self.run,"P","DONE"); done["status"]="accepted"; dsd_task.write_json(dsd_task.task_file(self.run,"P","DONE"),done)
        self.register("LIVE", kind="analysis"); self.ws("LIVE")
        info=dsd_task.load_run(self.run); dbdir=Path(info["runtime_root"])/"opencode-db"/"P"; dbdir.mkdir(parents=True,exist_ok=True)
        orphan=dbdir/"old.sqlite-wal"; orphan.write_text("x")
        class A: pass
        a=A();a.run_root=self.run;a.phase_id="P";out=dsd_workspace.command_cleanup_phase(a)
        self.assertIn("DONE",out["cleaned"]); self.assertTrue(any(x["task_id"]=="LIVE" for x in out["skipped"])); self.assertFalse(orphan.exists())

    def test_clean_stale_workspace_refreshes_to_current_primary_before_cold_retry(self):
        self.register("T-REFRESH")
        ws=self.ws("T-REFRESH"); wt=Path(ws["worktree"])
        self.assertEqual((wt/"a.txt").read_text(),"alpha\n")
        (self.project/"a.txt").write_text("engine-v2\n"); git(self.project,"add","a.txt"); git(self.project,"commit","-qm","engine fix")
        out=dsd_workspace.refresh_clean_task_workspace(self.run,"P","T-REFRESH")
        self.assertTrue(out["refreshed"],out)
        self.assertEqual((wt/"a.txt").read_text(),"engine-v2\n")
        rebound=dsd_workspace.load_workspace(self.run,"P","T-REFRESH")
        self.assertEqual(rebound["refresh_count"],1)
        self.assertEqual(git(wt,"diff","--name-only",f"{rebound['baseline_branch']}..{rebound['task_branch']}"),"")

    def test_workspace_with_task_delta_is_never_auto_refreshed(self):
        self.register("T-NO-REFRESH")
        ws=self.ws("T-NO-REFRESH"); wt=Path(ws["worktree"])
        (wt/"a.txt").write_text("task-work\n")
        (self.project/"b.txt").write_text("engine-v2\n"); git(self.project,"add","b.txt"); git(self.project,"commit","-qm","engine fix")
        out=dsd_workspace.refresh_clean_task_workspace(self.run,"P","T-NO-REFRESH")
        self.assertFalse(out["refreshed"],out); self.assertEqual(out["reason"],"task-delta-present-primary-changed")
        self.assertEqual(out["primary_change"],"primary-tracked-state-changed")
        self.assertNotEqual(out["workspace_primary_head"],out["current_primary_head"])
        self.assertEqual((wt/"a.txt").read_text(),"task-work\n")
        self.assertEqual((wt/"b.txt").read_text(),"beta\n")

    def test_purge_run_dry_run_reports_active_status_without_mutation(self):
        info=dsd_task.load_run(self.run); runtime=Path(info["runtime_root"]); (runtime/"junk.bin").write_text("cache\n")
        class A: pass
        p=A(); p.run_root=self.run; p.dry_run=True
        preview=dsd_workspace.command_purge_run(p)
        self.assertFalse(preview["safe_to_purge"]); self.assertTrue(runtime.exists())
        self.assertTrue(any(x["reason"]=="run-not-completed:active" for x in preview["blockers"]))

    def test_completed_run_automatically_purges_only_its_owned_runtime(self):
        info=dsd_task.load_run(self.run); runtime=Path(info["runtime_root"]); sibling=self.root/"other-project-cache"; sibling.mkdir(); (sibling/"keep.txt").write_text("keep\n")
        (runtime/"junk.bin").write_text("cache\n")
        class A: pass
        s=A(); s.run_root=self.run; s.status="completed"; s.reason=None; out=dsd_task.command_set_run_status(s)
        self.assertTrue(out.get("runtime_purged"),out)
        self.assertFalse(runtime.exists()); self.assertEqual((sibling/"keep.txt").read_text(),"keep\n")
        self.assertTrue((self.run/"run.json").is_file())

    def test_purge_run_refuses_unintegrated_workspace_and_owner_marker_mismatch(self):
        self.register("PURGE-BLOCK"); self.ws("PURGE-BLOCK")
        class A: pass
        s=A(); s.run_root=self.run; s.status="completed"; s.reason=None; dsd_task.command_set_run_status(s)
        p=A(); p.run_root=self.run; p.dry_run=True
        preview=dsd_workspace.command_purge_run(p)
        self.assertFalse(preview["safe_to_purge"]); self.assertTrue(any(x["task_id"]=="PURGE-BLOCK" for x in preview["blockers"]))
        p.dry_run=False
        with self.assertRaisesRegex(ValueError,"not cleanup-safe"): dsd_workspace.command_purge_run(p)
        marker=Path(dsd_task.load_run(self.run)["runtime_root"])/".tbag-run-owner.json"; owner=dsd_task.load_json(marker); owner["run_id"]="other"; dsd_task.write_json(marker,owner)
        p.dry_run=True
        with self.assertRaisesRegex(ValueError,"ownership marker"): dsd_workspace.command_purge_run(p)

if __name__=="__main__":unittest.main()
