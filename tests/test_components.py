import contextlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from types import SimpleNamespace
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
import dsd_task, dsd_attempt, report_surface, run_worker
from _rules_snapshot import verify_snapshot


def git(cwd,*args):
    cp=subprocess.run(['git',*args],cwd=cwd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if cp.returncode: raise RuntimeError(cp.stderr)
    return cp.stdout.strip()

class ComponentsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.project=self.root/'project'; self.project.mkdir()
        git(self.project,'init','-q'); git(self.project,'config','user.email','t@example.com'); git(self.project,'config','user.name','T')
        (self.project/'a.txt').write_text('a\n'); (self.project/'PLAN.md').write_text('# plan\n')
        git(self.project,'add','.'); git(self.project,'commit','-qm','init')
        self.run=self.project/'TBag'/'runs'/'r1'; self.run.mkdir(parents=True)
        class A: pass
        a=A(); a.project_root=self.project; a.run_root=self.run; a.run_id='r1'; a.runtime_root=str(self.root/'runtime'); a.max_workers=4; a.grunt_driver='opencode'; a.grunt_model='grunt/model'; a.analyst_driver='opencode'; a.analyst_model='analyst/model'
        dsd_task.command_init(a)
    def tearDown(self): self.tmp.cleanup()

    def register_impl(self, task='T1', phase='P1'):
        class A: pass
        plan_id=f'PLAN-{task}'
        planner=self.root/f'{phase}-{plan_id}.md'; planner.write_text(f'# Plan {task}\n')
        a=A(); a.run_root=self.run; a.phase_id=phase; a.task_id=plan_id; a.brief=planner; a.kind='analysis'; a.role='planner'; a.tier='analyst'; a.dependency=[]; a.requires_integration=False
        dsd_task.command_register_direct(a)
        event=dsd_task.task_root(self.run,phase,plan_id)/'attempts'/'planner-1'; tasks=event/'plan'/'tasks'; tasks.mkdir(parents=True)
        report=event/'report.md'; report.write_text('Analyst plan accepted.\n')
        brief=tasks/f'{task}.md'; brief.write_text(f'# {task}\n\nBounded implementation.\n')
        graph=event/'plan'/'task-graph.json'; graph.write_text(json.dumps({'format':dsd_task.PLAN_FORMAT,'tasks':[{'task_id':task,'kind':'implementation','role':'implementer','tier':'grunt','brief':f'tasks/{task}.md','dependencies':[],'requires_integration':True}]}))
        st=dsd_task.load_task(self.run,phase,plan_id); st['attempts'].append({'task_id':plan_id,'role':'planner','tier':'analyst','status':'gated','event_dir':str(event)}); st['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,phase,plan_id),st)
        a.report=report; dsd_task.command_accept(a)
        r=A(); r.run_root=self.run; r.phase_id=phase; r.plan=graph; dsd_task.command_register_plan(r)
        return dsd_task.load_task(self.run,phase,task)

    def gated_attempt(self,task,role='implementer',name=None,text='result\n',tier=None,phase='P1',status='gated'):
        name=name or f'{role}-1'; event=dsd_task.task_root(self.run,phase,task)/'attempts'/name; event.mkdir(parents=True,exist_ok=True)
        report=event/'report.md'; report.write_text(text)
        t=dsd_task.load_task(self.run,phase,task)
        t.setdefault('attempts',[]).append({'task_id':task,'role':role,'tier':tier or ('analyst' if role in {'discovery','recovery','planner','phase-surveyor'} else 'grunt'),'status':status,'event_dir':str(event),'checkpoint_ref':f'checkpoint-{name}'})
        t['status']='active'
        dsd_task.write_json(dsd_task.task_file(self.run,phase,task),t)
        return report,event

    def test_direct_owner_authorized_implementation_is_snapshotted_and_injected(self):
        brief=self.root/'owner-task.md'; brief.write_text('# Owner task\n\nImplement the explicitly requested bounded documentation change.\n')
        authority=self.root/'owner-decision.md'; authority.write_text('Owner explicitly directs this implementation.\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='OWNER-1'; a.brief=brief; a.kind='implementation'; a.role='implementer'; a.tier='grunt'; a.dependency=[]; a.requires_integration=True; a.reviews_task=None; a.owner_authority=authority
        out=dsd_task.command_register_direct(a); durable=Path(out['owner_authority'])
        self.assertTrue(durable.is_file()); self.assertNotEqual(durable,authority.resolve()); self.assertEqual(durable.read_text(),authority.read_text())
        authority.write_text('mutated external authority\n'); self.assertEqual(durable.read_text(),'Owner explicitly directs this implementation.\n')
        task=dsd_task.load_task(self.run,'P1','OWNER-1'); self.assertEqual(task['kind'],'implementation')
        inputs=dsd_attempt.task_input_groups(self.run,'P1',task,'implementer',[])
        self.assertIn(str(durable.resolve()),inputs['owner_decision'])

    def test_direct_implementation_without_explicit_owner_authority_is_rejected(self):
        brief=self.root/'bad-owner-task.md'; brief.write_text('# task\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='OWNER-2'; a.brief=brief; a.kind='implementation'; a.role='implementer'; a.tier='grunt'; a.dependency=[]; a.requires_integration=True; a.reviews_task=None; a.owner_authority=None
        with self.assertRaisesRegex(ValueError,'requires --owner-authority'):
            dsd_task.command_register_direct(a)

    def test_cold_base_role_launch_refreshes_clean_stale_workspace_before_worker_start(self):
        self.register_impl("T-COLD-REFRESH")
        dsd_workspace=__import__("dsd_workspace")
        ws=dsd_workspace.prepare_launch_workspace(self.run,"P1","T-COLD-REFRESH","implementer")
        wt=Path(ws["worktree"]); self.assertEqual((wt/"a.txt").read_text(),"a\n")
        (self.project/"a.txt").write_text("engine-v2\n"); git(self.project,"add","a.txt"); git(self.project,"commit","-qm","engine-v2")
        original=dsd_attempt._command_launch
        try:
            dsd_attempt._command_launch=lambda args: {"worktree_text":(wt/"a.txt").read_text()}
            a=SimpleNamespace(run_root=self.run,phase_id="P1",task_id="T-COLD-REFRESH",role="implementer",resume_last=False,resume_session=None)
            out=dsd_attempt.command_launch(a)
        finally:
            dsd_attempt._command_launch=original
        self.assertEqual(out["worktree_text"],"engine-v2\n")
        rebound=dsd_workspace.load_workspace(self.run,"P1","T-COLD-REFRESH")
        self.assertEqual(rebound.get("refresh_count"),1)

    def test_cold_retry_with_retained_delta_warns_when_primary_moved(self):
        self.register_impl("T-COLD-STALE")
        dsd_workspace=__import__("dsd_workspace")
        ws=dsd_workspace.prepare_launch_workspace(self.run,"P1","T-COLD-STALE","implementer")
        wt=Path(ws["worktree"]); (wt/"a.txt").write_text("task-delta\n")
        (self.project/"b.txt").write_text("engine-v2\n"); git(self.project,"add","b.txt"); git(self.project,"commit","-qm","engine-v2")
        original=dsd_attempt._command_launch
        try:
            dsd_attempt._command_launch=lambda args: {"status":"started","task_id":"T-COLD-STALE"}
            a=SimpleNamespace(run_root=self.run,phase_id="P1",task_id="T-COLD-STALE",role="implementer",resume_last=False,resume_session=None)
            out=dsd_attempt.command_launch(a)
        finally:
            dsd_attempt._command_launch=original
        warning=out["workspace_warning"]
        self.assertEqual(warning["code"],"retained-task-delta-on-stale-primary")
        self.assertEqual(warning["primary_change"],"primary-tracked-state-changed")
        self.assertEqual((wt/"a.txt").read_text(),"task-delta\n")
        self.assertFalse((wt/"b.txt").exists())

    def test_idle_check_catches_ready_work_before_parent_returns(self):
        self.register_impl('T-IDLE')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'
        out=dsd_task.command_idle_check(a)
        self.assertFalse(out['safe_to_end_routine_turn']); self.assertEqual(out['reason'],'authorized-action-remains')
        self.assertTrue(any(x.get('action')=='launch-ready-task' for x in out['required_actions']))
        self.assertEqual(out['routine_user_update'],'suppress')

    def test_idle_check_requires_harness_supervision_without_foreground_wait(self):
        self.register_impl('T-LIVE-SUP')
        event=dsd_task.task_root(self.run,'P1','T-LIVE-SUP')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T-LIVE-SUP'); task['attempts'].append({'task_id':'T-LIVE-SUP','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'monitor_pid':os.getpid()}); task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-LIVE-SUP'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'
        out=dsd_task.command_idle_check(a)
        self.assertTrue(out['safe_to_end_routine_turn']); self.assertEqual(out['reason'],'workers-live')
        self.assertTrue(out['observer_required']); self.assertNotIn('live_supervision_rule',out); self.assertNotIn('rule',out)

    def test_follow_is_per_attempt_observation_only(self):
        self.register_impl('T-FOLLOW')
        event=dsd_task.task_root(self.run,'P1','T-FOLLOW')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        (event/'terminal.json').write_text(json.dumps({'status':'process-exited','exit_code':0}))
        task=dsd_task.load_task(self.run,'P1','T-FOLLOW')
        task['attempts'].append({'task_id':'T-FOLLOW','role':'implementer','tier':'grunt','status':'started','event_dir':str(event)})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-FOLLOW'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T-FOLLOW'; a.event_dir=event; a.interval=.01; a.timeout=.05; a.tail_every=10
        out=dsd_attempt.command_follow(a)
        self.assertEqual(out['follow_status'],'terminal')
        unchanged=dsd_task.load_task(self.run,'P1','T-FOLLOW')
        self.assertEqual(unchanged['status'],'active'); self.assertEqual(unchanged['attempts'][-1]['status'],'started')

    def test_follow_returns_dead_unresolved_without_mutating_attempt(self):
        self.register_impl('T-FOLLOW-DEAD')
        event=dsd_task.task_root(self.run,'P1','T-FOLLOW-DEAD')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T-FOLLOW-DEAD')
        task['attempts'].append({'task_id':'T-FOLLOW-DEAD','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'monitor_pid':99999999})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-FOLLOW-DEAD'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T-FOLLOW-DEAD'; a.event_dir=event; a.interval=1; a.timeout=1; a.tail_every=10
        out=dsd_attempt.command_follow(a)
        self.assertEqual(out['follow_status'],'dead-unresolved')
        self.assertEqual(dsd_task.load_task(self.run,'P1','T-FOLLOW-DEAD')['attempts'][-1]['status'],'started')

    def test_follow_is_quiet_while_running(self):
        self.register_impl('T-FOLLOW-QUIET')
        event=dsd_task.task_root(self.run,'P1','T-FOLLOW-QUIET')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        (event/'worker.log').write_text('very large worker body\n'*200)
        task=dsd_task.load_task(self.run,'P1','T-FOLLOW-QUIET')
        task['attempts'].append({'task_id':'T-FOLLOW-QUIET','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'monitor_pid':os.getpid()})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-FOLLOW-QUIET'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T-FOLLOW-QUIET'; a.event_dir=event; a.interval=1; a.timeout=1
        buf=io.StringIO()
        with contextlib.redirect_stdout(buf): out=dsd_attempt.command_follow(a)
        printed=buf.getvalue()
        self.assertEqual(out['follow_status'],'deadline')
        self.assertEqual(printed.count('\n'),2,printed)
        self.assertNotIn('very large worker body',printed)

    def test_report_surface_prefers_bounded_decision_section(self):
        report=self.root/'large-report.md'
        report.write_text('# Detail\n' + ('dense evidence line\n'*200) + '\n## Conclusion\nPASS — exact frontier reconciled.\nOnly MIG-004 remains separate.\n\n## Appendix\n' + ('huge\n'*200))
        lines=report_surface.surface(report,max_lines=4,max_chars=300)
        text='\n'.join(lines)
        self.assertIn('Conclusion',text); self.assertIn('MIG-004',text)
        self.assertNotIn('dense evidence line',text); self.assertNotIn('Appendix',text)

    def test_gate_result_can_carry_bounded_report_surface_without_second_parent_read(self):
        # The selection helper is owned by report_surface; gate embeds only that bounded
        # surface and never infers semantic PASS/FAIL from it.
        report=self.root/'gate-report.md'
        report.write_text('# Evidence\n' + ('large detail\n'*200) + '\n## Verdict\nPASS — reviewed frontier is sound.\nOne bounded note.\n')
        surfaced=report_surface.surface(report,max_lines=6,max_chars=1000)
        self.assertLessEqual(len(surfaced),6); self.assertIn('Verdict','\n'.join(surfaced)); self.assertNotIn('large detail','\n'.join(surfaced))

    def test_gate_batches_multiple_task_ids_without_event_dir(self):
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id=['T1','T2']; a.event_dir=None
        seen=[]
        original=dsd_attempt._gate_one
        try:
            dsd_attempt._gate_one=lambda run,phase,tid,event: (seen.append((phase,tid,event)) or {'task_id':tid,'ready_for_interpretation':True})
            out=dsd_attempt.command_gate(a)
        finally:
            dsd_attempt._gate_one=original
        self.assertEqual([x[1] for x in seen],['T1','T2'])
        self.assertEqual(out['count'],2); self.assertEqual(out['errors'],[])

    def test_follow_default_deadline_is_shorter_for_grunt_than_analyst(self):
        self.assertEqual(dsd_attempt._default_follow_timeout("implementer"),7200.0)
        self.assertEqual(dsd_attempt._default_follow_timeout("reviewer"),7200.0)
        self.assertEqual(dsd_attempt._default_follow_timeout("planner"),21600.0)
        self.assertEqual(dsd_attempt._default_follow_timeout("recovery"),21600.0)

    def test_background_follow_does_not_rescan_run_duration_history_every_poll(self):
        self.register_impl('T-FOLLOW-CHEAP')
        event=dsd_task.task_root(self.run,'P1','T-FOLLOW-CHEAP')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T-FOLLOW-CHEAP')
        task['attempts'].append({'task_id':'T-FOLLOW-CHEAP','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'monitor_pid':os.getpid()})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-FOLLOW-CHEAP'),task)
        original=dsd_attempt._completed_role_duration_reference
        dsd_attempt._completed_role_duration_reference=lambda *a,**k: (_ for _ in ()).throw(AssertionError('follow should skip historical scan'))
        try:
            class A: pass
            a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T-FOLLOW-CHEAP'; a.event_dir=event; a.interval=1; a.timeout=1
            out=dsd_attempt.command_follow(a)
        finally:
            dsd_attempt._completed_role_duration_reference=original
        self.assertEqual(out['follow_status'],'deadline')

    def test_follow_deadline_is_observation_not_lifecycle_transition(self):
        self.register_impl('T-FOLLOW-DEADLINE')
        event=dsd_task.task_root(self.run,'P1','T-FOLLOW-DEADLINE')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T-FOLLOW-DEADLINE')
        task['attempts'].append({'task_id':'T-FOLLOW-DEADLINE','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'monitor_pid':os.getpid()})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-FOLLOW-DEADLINE'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T-FOLLOW-DEADLINE'; a.event_dir=event; a.interval=1; a.timeout=1; a.tail_every=10
        out=dsd_attempt.command_follow(a)
        self.assertEqual(out['follow_status'],'deadline')
        self.assertEqual(dsd_task.load_task(self.run,'P1','T-FOLLOW-DEADLINE')['status'],'active')

    def test_idle_check_surfaces_human_decision_as_nonroutine_communication(self):
        self.register_impl('T-HUMAN')
        task=dsd_task.load_task(self.run,'P1','T-HUMAN'); task['status']='blocked'; task['last_escalation']={'target':'human','report':'decision-needed.md'}
        dsd_task.write_json(dsd_task.task_file(self.run,'P1','T-HUMAN'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'
        out=dsd_task.command_idle_check(a)
        self.assertTrue(out['safe_to_end_routine_turn']); self.assertEqual(out['reason'],'human-blocked-with-no-independent-action')
        self.assertEqual(out['routine_user_update'],'human-decision')

    def test_idle_check_run_level_human_block_still_requests_decision(self):
        run=dsd_task.load_json(self.run/'run.json'); run['status']='human-blocked'; dsd_task.write_json(self.run/'run.json',run)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'
        out=dsd_task.command_idle_check(a)
        self.assertEqual(out['routine_user_update'],'human-decision')


    def test_live_attempt_session_evidence_is_reusable_before_terminal(self):
        event=self.root/'live-session'; event.mkdir(); (event/'attempt.json').write_text(json.dumps({'session_id':'live-ses'}))
        attempt={'role':'reviewer','event_dir':str(event)}
        self.assertEqual(dsd_attempt.attempt_session_id(attempt),'live-ses')
        self.assertEqual(dsd_attempt.latest_session({'attempts':[attempt]},'reviewer'),'live-ses')

    def test_live_codex_session_capture_uses_thread_started_without_waiting_for_terminal(self):
        log=self.root/'live-codex.jsonl'; log.write_text(json.dumps({'type':'thread.started','thread_id':'live-thread'})+'\n')
        class Proc:
            def poll(self): return None
        args=SimpleNamespace(driver='codex',resume_session=None)
        self.assertEqual(run_worker.capture_live_session_id(args,{},'ignored',log,Proc(),attempts=1,delay_seconds=0),('live-thread',None))

    def test_codex_jsonl_thread_id_and_command_are_lifecycle_wired(self):
        log=self.root/'codex.jsonl'; log.write_text('noise\n'+json.dumps({'type':'thread.started','thread_id':'thr-123'})+'\n')
        self.assertEqual(run_worker.codex_session_id(log),('thr-123',None))
        project=self.project; event=self.root/'attempt'; event.mkdir(); task=self.root/'codex-task.md'; task.write_text('# Task\n\nRead only.\n'); prompt=self.root/'prompt.txt'; prompt.write_text('do work')
        p={'project_root':project,'event_dir':event,'task':task,'prompt':prompt,'db':self.root/'unused.sqlite'}
        args=SimpleNamespace(driver='codex',task_id='T',role='discovery',attempt=1,model='gpt-test',title=None,force_read_only=True,resume_session=None,auto_flag='--auto')
        old=run_worker.shutil.which; run_worker.shutil.which=lambda name: '/usr/bin/codex' if name=='codex' else old(name)
        try: cmd,_,_,cwd=run_worker.worker_command(args,p,{})
        finally: run_worker.shutil.which=old
        self.assertEqual(cmd[0],'codex'); self.assertIn('--json',cmd); self.assertNotIn('--add-dir',cmd); self.assertEqual(cwd,event); self.assertEqual(cmd[cmd.index('--cd')+1],str(event)); self.assertIn('workspace-write',cmd)
        args.force_read_only=False; args.role='implementer'; task.write_text('# Task\n\nImplement.\n')
        run_worker.shutil.which=lambda name: '/usr/bin/codex' if name=='codex' else old(name)
        try: mut_cmd,_,_,mut_cwd=run_worker.worker_command(args,p,{})
        finally: run_worker.shutil.which=old
        self.assertEqual(mut_cwd,project); self.assertIn('--add-dir',mut_cmd); self.assertIn(str(event),mut_cmd); self.assertEqual(mut_cmd[mut_cmd.index('--cd')+1],str(project))

    def test_codex_protocol_parsing_never_trusts_merged_stderr(self):
        fake_bin=self.root/'fake-bin'; fake_bin.mkdir(); fake=fake_bin/'codex'
        fake.write_text('#!/usr/bin/env python3\nimport sys\nprint("{\\"type\\":\\"thread.started\\",\\"thread_id\\":\\"stdout-thread\\"}")\nprint("{\\"type\\":\\"thread.started\\",\\"thread_id\\":\\"stderr-spoof\\"}", file=sys.stderr)\n')
        fake.chmod(0o755)
        event=self.root/'codex-attempt'; event.mkdir(); prompt=event/'prompt.txt'; prompt.write_text('work'); task=event/'task.md'; task.write_text('# read only\n'); report=event/'report.md'; report.write_text('done\n')
        p={'project_root':self.project,'run_root':self.run,'prompt':prompt,'task':task,'rules':event/'unused-rules','baseline':event/'unused-baseline','report':report,'event_dir':event,'log':event/'worker.log','db':self.root/'unused.sqlite'}
        args=SimpleNamespace(driver='codex',task_id='T',role='discovery',attempt=1,model='gpt-test',title=None,force_read_only=True,resume_session=None,auto_flag='--auto',tier='analyst')
        old_path=os.environ.get('PATH',''); old_freeze=run_worker.freeze_scope
        os.environ['PATH']=str(fake_bin)+os.pathsep+old_path; run_worker.freeze_scope=lambda _: (None,None)
        try: rc=run_worker.child(args,p,'reserved-now')
        finally: os.environ['PATH']=old_path; run_worker.freeze_scope=old_freeze
        self.assertEqual(rc,0)
        terminal=json.loads((event/'terminal.json').read_text()); self.assertEqual(terminal['session_id'],'stdout-thread')
        self.assertIn('stderr-spoof',(event/'worker.stderr.log').read_text()); self.assertNotIn('stderr-spoof',(event/'worker.log').read_text())

    def test_grunt_escalation_routes_to_analyst_not_human(self):
        self.register_impl()
        report,_=self.gated_attempt('T1',text='ESCALATE: ownership is uncertain; needs stronger analysis.\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=report
        out=dsd_task.command_escalate(a)
        self.assertEqual(out['status'],'needs-analysis'); self.assertEqual(out['escalation_target'],'analyst')
        task=dsd_task.load_task(self.run,'P1','T1')
        self.assertEqual(task['last_escalation']['from_tier'],'grunt')
        inputs=dsd_attempt.task_input_groups(self.run,'P1',task,'discovery',[])
        self.assertIn(str(report.resolve()),inputs['escalation_context'])

    def test_analyst_escalation_blocks_for_human_and_decision_flows_back(self):
        self.register_impl()
        grunt,_=self.gated_attempt('T1',text='ESCALATE: needs diagnosis.\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=grunt; dsd_task.command_escalate(a)
        analyst,_=self.gated_attempt('T1','discovery','discovery-1','ESCALATE: owner must choose between A and B.\n',tier='analyst')
        a.outcome='escalate'; a.report=analyst
        out=dsd_task.command_analysis_result(a)
        self.assertEqual(out['status'],'blocked')
        task=dsd_task.load_task(self.run,'P1','T1'); self.assertEqual(task['last_escalation']['target'],'human')
        launch=SimpleNamespace(run_root=self.run,phase_id='P1',task_id='T1',role='implementer',tier='grunt',model=None,worker_rules=None,db=None,attempt=None,input=[],resume_session=None,resume_last=False,auto_flag='--auto')
        with self.assertRaisesRegex(ValueError,'Human-targeted escalation'):
            dsd_attempt._command_launch(launch)
        decision=self.root/'decision.md'; decision.write_text('Choose option A.\n')
        r=A(); r.run_root=self.run; r.phase_id='P1'; r.task_id='T1'; r.decision=decision; r.route='resume'
        resumed=dsd_task.command_resolve_escalation(r); self.assertEqual(resumed['status'],'planned')
        task=dsd_task.load_task(self.run,'P1','T1')
        inputs=[x for group in dsd_attempt.task_input_groups(self.run,'P1',task,'implementer',[]).values() for x in group]
        durable=Path(resumed['decision']); self.assertTrue(durable.is_file()); self.assertNotEqual(durable,decision.resolve())
        self.assertEqual(durable.read_text(),'Choose option A.\n')
        decision.write_text('mutated external decision\n')
        self.assertEqual(durable.read_text(),'Choose option A.\n')
        self.assertIn(str(durable),inputs)
        self.assertIn(str(analyst.resolve()),inputs)

    def test_human_decision_can_route_back_to_analyst(self):
        self.register_impl()
        analyst,_=self.gated_attempt('T1','discovery','discovery-1','ESCALATE: owner architecture choice.\n',tier='analyst')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.outcome='escalate'; a.report=analyst; dsd_task.command_analysis_result(a)
        decision=self.root/'architecture-decision.md'; decision.write_text('Use redesigned ownership; Analyst should decompose it.\n')
        a.decision=decision; a.route='analysis'; out=dsd_task.command_resolve_escalation(a)
        self.assertEqual(out['status'],'needs-analysis')
        task=dsd_task.load_task(self.run,'P1','T1'); dsd_attempt.validate_launch_role(task,'discovery')
        inputs=[x for group in dsd_attempt.task_input_groups(self.run,'P1',task,'discovery',[]).values() for x in group]
        self.assertIn(out['decision'],inputs)

    def test_escalation_can_be_disabled_without_changing_worker_roles(self):
        self.register_impl(); report,_=self.gated_attempt('T1',text='ESCALATE: needs diagnosis.\n')
        class A: pass
        cfg=A(); cfg.run_root=self.run; cfg.mode='off'; out=dsd_task.command_set_escalation(cfg); self.assertFalse(out['escalation_enabled'])
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=report
        with self.assertRaisesRegex(ValueError,'ESCALATION_DISABLED'): dsd_task.command_escalate(a)
        self.assertEqual(dsd_task.load_task(self.run,'P1','T1')['status'],'active')

    def test_stale_worker_escalation_and_analysis_results_are_rejected(self):
        self.register_impl(); first,_=self.gated_attempt('T1','implementer','implementer-1','ESCALATE old\n')
        self.gated_attempt('T1','implementer','implementer-2','newer result\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=first
        with self.assertRaisesRegex(ValueError,'stale'): dsd_task.command_escalate(a)

        # Analyst semantic results are equally bound to the current attempt.
        task=dsd_task.load_task(self.run,'P1','T1'); task['status']='needs-analysis'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),task)
        old,_=self.gated_attempt('T1','discovery','discovery-1','old analysis\n',tier='analyst')
        self.gated_attempt('T1','discovery','discovery-2','new analysis\n',tier='analyst')
        a.outcome='resume'; a.report=old
        with self.assertRaisesRegex(ValueError,'stale'): dsd_task.command_analysis_result(a)

    def test_generic_escalate_cannot_bypass_reviewer_semantics(self):
        self.register_impl(); report,_=self.gated_attempt('T1','reviewer','reviewer-1','ESCALATE review\n',tier='grunt')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=report
        with self.assertRaisesRegex(ValueError,'semantic outcome command'): dsd_task.command_escalate(a)

    def test_human_blocked_run_requires_no_other_authorized_work(self):
        self.register_impl('T1'); self.register_impl('T2')
        analyst,_=self.gated_attempt('T1','discovery','discovery-1','ESCALATE: owner choice required.\n',tier='analyst')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.outcome='escalate'; a.report=analyst
        dsd_task.command_analysis_result(a)
        r=A(); r.run_root=self.run; r.status='human-blocked'; r.reason='waiting for owner'
        with self.assertRaisesRegex(ValueError,'can advance without the Human decision'):
            dsd_task.command_set_run_status(r)
        s=A(); s.run_root=self.run; s.phase_id='P1'; s.task_id='T2'; s.by=None; dsd_task.command_supersede(s)
        self.assertEqual(dsd_task.command_set_run_status(r)['status'],'human-blocked')

    def test_escalate_rejects_parent_authored_report(self):
        self.register_impl(); fake=self.root/'fake.md'; fake.write_text('escalate please\n')
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.report=fake
        with self.assertRaises(ValueError) as cm: dsd_task.command_escalate(a)
        msg=str(cm.exception)
        self.assertIn('gated worker report',msg)
        self.assertIn('analysis-result --outcome escalate',msg)
        self.assertIn('do not author a parent escalation report',msg)

    def test_reviewer_escalation_hands_exact_evidence_to_analyst(self):
        self.register_impl()
        worker,_=self.gated_attempt('T1','implementer','implementer-1','implemented attempt\n')
        t=dsd_task.load_task(self.run,'P1','T1'); t['status']='awaiting-review'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),t)
        class A: pass
        review1,_=self.gated_attempt('T1','reviewer','reviewer-1','concrete defect\n',tier='grunt')
        t=dsd_task.load_task(self.run,'P1','T1'); t['status']='awaiting-review'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),t)
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.outcome='fail'; a.report=review1
        self.assertEqual(dsd_task.command_review(a)['status'],'needs-fix')
        fixer,_=self.gated_attempt('T1','fixer','fixer-1','fixer result\n',tier='grunt')
        t=dsd_task.load_task(self.run,'P1','T1'); t['status']='awaiting-review'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),t)
        review2,_=self.gated_attempt('T1','reviewer','reviewer-2','ESCALATE: substantial diagnosis required.\n',tier='grunt')
        t=dsd_task.load_task(self.run,'P1','T1'); t['status']='awaiting-review'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),t)
        a.outcome='escalate'; a.report=review2
        out=dsd_task.command_review(a); self.assertEqual(out['status'],'needs-analysis'); self.assertEqual(out['escalation_target'],'analyst')
        task=dsd_task.load_task(self.run,'P1','T1')
        inputs=dsd_attempt.task_input_groups(self.run,'P1',task,'discovery',[])
        self.assertIn(str(review2.resolve()),inputs['escalation_context'])
        self.assertIn(str(fixer.resolve()),inputs['worker_report'])

    def test_grunt_review_session_topology(self):
        task={'attempts':[{'role':'implementer','session_id':'ses-impl'}, {'role':'reviewer','session_id':'ses-review-1'}]}
        self.assertEqual(dsd_attempt.DEFAULT_TIER['reviewer'],'grunt')
        self.assertIsNone(dsd_attempt.resolve_resume_session(task,'reviewer','awaiting-review',None,False))
        with self.assertRaisesRegex(ValueError,'fresh session'):
            dsd_attempt.resolve_resume_session(task,'reviewer','awaiting-review','ses-impl',False)
        self.assertEqual(dsd_attempt.resolve_resume_session(task,'fixer','needs-fix',None,False),'ses-review-1')
        with self.assertRaisesRegex(ValueError,'does not match'):
            dsd_attempt.resolve_resume_session(task,'fixer','needs-fix','ses-wrong',False)
        self.assertEqual(dsd_attempt.resolve_resume_session(task,'fixer','needs-fix','ses-review-1',False),'ses-review-1')
        task['attempts'].append({'role':'fixer','session_id':'ses-review-1'})
        self.assertEqual(dsd_attempt.resolve_resume_session(task,'fixer','active',None,True),'ses-review-1')

    def test_awaiting_review_cold_implementer_is_not_a_valid_continuation(self):
        self.register_impl(); path=dsd_task.task_file(self.run,'P1','T1'); task=dsd_task.load_json(path); task['status']='awaiting-review'; dsd_task.write_json(path,task)
        launch=SimpleNamespace(run_root=self.run,phase_id='P1',task_id='T1',role='implementer',tier='grunt',model=None,worker_rules=None,db=None,attempt=None,input=[],resume_session=None,resume_last=False,auto_flag='--auto')
        with self.assertRaisesRegex(ValueError,'awaiting Review'):
            dsd_attempt._command_launch(launch)


    def test_reportless_no_change_preserves_same_role_resume_path(self):
        self.register_impl()
        event=dsd_task.task_root(self.run,'P1','T1')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T1')
        task['attempts'].append({'task_id':'T1','role':'implementer','tier':'grunt','status':'started','event_dir':str(event),'session_id':'ses-1'})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.event_dir=event; a.status='report-recovery'; a.gate=self.root/'gate.json'; a.gate.write_text('{}'); a.session_id='ses-1'
        out=dsd_task.command_update_attempt(a)
        self.assertEqual(out['task_status'],'active')
        task=dsd_task.load_task(self.run,'P1','T1')
        dsd_attempt.validate_launch_role(task,'implementer',continuing=True)

    def test_legacy_mutating_report_recovery_status_still_routes_recovery(self):
        self.register_impl()
        event=dsd_task.task_root(self.run,'P1','T1')/'attempts'/'implementer-1'; event.mkdir(parents=True)
        task=dsd_task.load_task(self.run,'P1','T1')
        task['attempts'].append({'task_id':'T1','role':'implementer','tier':'grunt','status':'started','event_dir':str(event)})
        task['status']='active'; dsd_task.write_json(dsd_task.task_file(self.run,'P1','T1'),task)
        class A: pass
        a=A(); a.run_root=self.run; a.phase_id='P1'; a.task_id='T1'; a.event_dir=event; a.status='mutating-report-recovery'; a.gate=self.root/'gate2.json'; a.gate.write_text('{}'); a.session_id=None
        out=dsd_task.command_update_attempt(a)
        self.assertEqual(out['task_status'],'recovery-required')
        task=dsd_task.load_task(self.run,'P1','T1')
        with self.assertRaises(ValueError): dsd_attempt.validate_launch_role(task,'implementer',continuing=True)
        dsd_attempt.validate_launch_role(task,'recovery')

    def test_worker_rules_snapshot_authority_instead_of_following_live_files(self):
        instruction=self.project/'AGENTS.md'; instruction.write_text('original instruction\n')
        cp=subprocess.run([sys.executable,str(SCRIPTS/'prepare_worker_rules.py'),'--project-root',str(self.project.resolve()),'--run-root',str(self.run.resolve()),'--plan',str((self.project/'PLAN.md').resolve()),'--project-instruction',str(instruction.resolve()),'--revision','1'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,0,cp.stderr)
        rules=self.run/'worker-rules'/'r0001'/'WORKER_RULES.md'; info=verify_snapshot(rules)
        snap_plan=Path(info['authority_plan']); snap_instruction=Path(info['authority_files'][1])
        self.assertEqual(snap_plan.read_text(),'# plan\n'); self.assertEqual(snap_instruction.read_text(),'original instruction\n')
        (self.project/'PLAN.md').write_text('# changed live plan\n'); instruction.write_text('changed live instruction\n')
        self.assertEqual(snap_plan.read_text(),'# plan\n'); self.assertEqual(snap_instruction.read_text(),'original instruction\n')
        snap_instruction.unlink()
        with self.assertRaisesRegex(ValueError,'authority snapshot incomplete'): verify_snapshot(rules)

    def test_context_checkpoint_is_orientation_only_and_reconcile_first(self):
        self.register_impl('T1','P1')
        cp=subprocess.run([sys.executable,str(SCRIPTS/'context_checkpoint.py'),'--project-root',str(self.project),'--run-root',str(self.run),'instruction'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertIn('reconcile-run',cp.stdout)
        self.assertNotIn('ready --run-root',cp.stdout)
        self.assertFalse((self.run/'checkpoints').exists())
        help_text=subprocess.run([sys.executable,str(SCRIPTS/'context_checkpoint.py'),'--help'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True).stdout
        self.assertIn('instruction',help_text); self.assertIn('hook',help_text)
        for obsolete in ('prepare','rehydrate','verify-resume'):
            self.assertNotIn(obsolete,help_text)

    def test_compaction_run_selection_never_guesses_between_multiple_resumable_runs(self):
        other=self.project/'TBag'/'runs'/'r2'; other.mkdir(parents=True); (other/'run.json').write_text(json.dumps({'run_id':'r2','status':'human-blocked'}))
        cp=subprocess.run([sys.executable,str(SCRIPTS/'context_checkpoint.py'),'--project-root',str(self.project),'instruction'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,5); self.assertIn('AMBIGUOUS_RUN',cp.stderr); self.assertIn('TBAG_RUN_ROOT',cp.stderr)
        env=os.environ.copy(); env['TBAG_RUN_ROOT']=str(other)
        cp=subprocess.run([sys.executable,str(SCRIPTS/'context_checkpoint.py'),'--project-root',str(self.project),'instruction'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        self.assertEqual(cp.returncode,0,cp.stderr); self.assertIn(str(other),cp.stdout); self.assertIn('reconcile-run',cp.stdout)

    def test_all_parent_harness_adapters_install_without_legacy_control_plane(self):
        for harness in ('codex','claude-code','opencode','kilo'):
            with self.subTest(harness=harness):
                project=self.root/f'adapter-{harness}'; project.mkdir(); git(project,'init','-q')
                cp=subprocess.run([sys.executable,str(SCRIPTS/'install_harness_adapter.py'),'--harness',harness,'--project-root',str(project),'--skill-root',str(ROOT)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                self.assertEqual(cp.returncode,0,cp.stderr)
                data=json.loads(cp.stdout)
                helper=project/'TBag'/'tools'/'context_checkpoint.py'; task_helper=project/'TBag'/'tools'/'dsd_task.py'; attempt_helper=project/'TBag'/'tools'/'dsd_attempt.py'
                self.assertTrue(helper.is_file()); self.assertTrue(task_helper.is_file()); self.assertTrue(attempt_helper.is_file())
                self.assertFalse((project/'TBag'/'tools'/'dsd_state.py').exists())
                self.assertIn(str((SCRIPTS/'context_checkpoint.py').resolve()),helper.read_text())
                self.assertIn(str((SCRIPTS/'dsd_task.py').resolve()),task_helper.read_text()); self.assertIn(str((SCRIPTS/'dsd_attempt.py').resolve()),attempt_helper.read_text())
                if harness=='opencode':
                    self.assertEqual(data['interactive_supervision'],'detached-core-launch-then-tbag-follow')
                    self.assertEqual(data['autonomous_supervision'],'per-attempt-tbag-follow-wake')
                    self.assertEqual(data['required_live_tool'],'tbag_follow'); self.assertFalse(data['live_capability_verified'])
                    self.assertTrue(data['disk_matches_source']); self.assertEqual(data['source_sha256'],data['installed_sha256'])
                    plugin=project/'.opencode'/'plugins'/'tbag.js'; self.assertTrue(plugin.is_file())
                    text=plugin.read_text(); self.assertIn('tbag_follow: tool({',text); self.assertNotIn('tbag_launch: tool({',text)

    def test_reinstall_prunes_obsolete_managed_compaction_hooks(self):
        project=self.root/'adapter-prune'; project.mkdir(); git(project,'init','-q')
        settings=project/'.claude'/'settings.json'; settings.parent.mkdir(parents=True)
        old={'hooks':{
            'PreCompact':[{'matcher':'x','hooks':[{'type':'command','command':'python3 TBag/tools/context_checkpoint.py hook --harness claude-code --event precompact'}]}],
            'PostCompact':[{'matcher':'x','hooks':[{'type':'command','command':'python3 TBag/tools/context_checkpoint.py hook --harness claude-code --event postcompact'}]}],
            'PostToolUse':[{'matcher':'Bash','hooks':[{'type':'command','command':'python3 TBag/tools/claude_worker_rewake.py','asyncRewake':True}]}],
        }}
        settings.write_text(json.dumps(old))
        cp=subprocess.run([sys.executable,str(SCRIPTS/'install_harness_adapter.py'),'--harness','claude-code','--project-root',str(project),'--skill-root',str(ROOT)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,0,cp.stderr); data=json.loads(settings.read_text())
        self.assertNotIn('PreCompact',data.get('hooks',{})); self.assertNotIn('PostCompact',data.get('hooks',{}))
        self.assertIn('SessionStart',data['hooks']); self.assertNotIn('PostToolUse',data['hooks']); self.assertFalse((project/'TBag'/'tools'/'claude_worker_rewake.py').exists())

    def test_opencode_adapter_installs_plugin_native_supervision_and_prunes_legacy_plugin(self):
        project=self.root/'adapter-opencode-plugin'; project.mkdir(); git(project,'init','-q')
        plugins=project/'.opencode'/'plugins'; plugins.mkdir(parents=True)
        legacy=plugins/'dsd-compaction.ts'; legacy.write_text('legacy')
        previous=plugins/'tbag.js'; previous.write_text('export default async () => ({ tool: { tbag_follow: {} } })\n')
        cp=subprocess.run([sys.executable,str(SCRIPTS/'install_harness_adapter.py'),'--harness','opencode','--project-root',str(project),'--skill-root',str(ROOT)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,0,cp.stderr); data=json.loads(cp.stdout)
        self.assertEqual(data['interactive_supervision'],'detached-core-launch-then-tbag-follow')
        self.assertEqual(data['autonomous_supervision'],'per-attempt-tbag-follow-wake')
        self.assertEqual(data['required_live_tool'],'tbag_follow'); self.assertFalse(data['live_capability_verified'])
        self.assertTrue(data['changed']); self.assertTrue(data['disk_matches_source']); self.assertEqual(data['source_sha256'],data['installed_sha256'])
        self.assertTrue(Path(data['backup']).is_file())
        self.assertEqual(data['activation'],'restart-required-to-load-refreshed-adapter')
        self.assertTrue(data['legacy_plugin_removed']); self.assertFalse(legacy.exists())
        plugin=plugins/'tbag.js'; self.assertTrue(plugin.is_file())
        text=plugin.read_text(); self.assertIn('tbag_follow: tool({',text); self.assertNotIn('tbag_launch: tool({',text); self.assertIn('client.session.prompt',text); self.assertNotIn('tbag_supervise',text)
        self.assertIn('proves only the project adapter file on disk',data['manual_step']); self.assertIn('current OpenCode tool registry',data['manual_step'])

        # A second refresh is idempotent and still refuses to claim live-host state.
        cp2=subprocess.run([sys.executable,str(SCRIPTS/'install_harness_adapter.py'),'--harness','opencode','--project-root',str(project),'--skill-root',str(ROOT)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp2.returncode,0,cp2.stderr); second=json.loads(cp2.stdout)
        self.assertFalse(second['changed']); self.assertIsNone(second['backup']); self.assertTrue(second['disk_matches_source'])
        self.assertFalse(second['live_capability_verified']); self.assertEqual(second['activation'],'disk-current-live-registry-unverified')

    def test_opencode_plugin_runtime_launch_follow_compatibility_and_wake(self):
        node=shutil.which('node')
        if not node: self.skipTest('node unavailable')
        script=ROOT/'tests'/'opencode_plugin_runtime.mjs'
        plugin=ROOT/'adapters'/'opencode'/'tbag.js'
        cp=subprocess.run([node,str(script),str(plugin)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertIn('OPENCODE_PLUGIN_RUNTIME_PASS',cp.stdout)

    def test_opencode_plugin_uses_stable_follow_tool_and_session_wake_not_background_subagent_protocol(self):
        plugin=ROOT/'adapters'/'opencode'/'tbag.js'; text=plugin.read_text()
        self.assertIn('import { tool } from "@opencode-ai/plugin"',text)
        self.assertIn('tbag_follow: tool({',text); self.assertNotIn('tbag_launch: tool({',text)
        self.assertIn('"tool.execute.after"',text); self.assertIn('isCoreAttemptCommand(input?.args?.command, "launch")',text)
        self.assertIn('armAttempt(ctx.client, sessionID, root, launch)',text)
        self.assertIn('validateAttempt(root, args)',text)
        self.assertIn('Bun.spawn(attemptCli(root, args, "follow")',text)
        self.assertIn('client.session.prompt',text); self.assertNotIn('delivery: "queue"',text)
        self.assertIn('pendingWakeSessions',text); self.assertIn('wakeInflightSessions',text); self.assertIn('deletedSessions',text)
        self.assertIn('event?.properties?.info?.id',text)
        self.assertIn('event.type === "session.status"',text); self.assertIn('event.type === "session.idle"',text)
        self.assertIn('if (delivered && pendingWakeSessions.has(sessionID)',text)
        self.assertIn('"tool.execute.before"',text); self.assertIn('must use non-blocking tbag_follow',text)
        self.assertNotIn('must use tbag_launch',text); self.assertNotIn('String(args.timeout ?? 21600)',text)
        self.assertNotIn('sessionRuntime',text); self.assertNotIn('sessionIsIdle',text); self.assertNotIn('runtime.model',text)
        self.assertNotIn('OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS',text); self.assertNotIn('promptAsync',text)
        self.assertNotIn('setInterval(',text); self.assertNotIn('setTimeout(',text)
        self.assertEqual(text.count('export default TBagPlugin'),1); self.assertNotIn('export const TBagPlugin',text)
        node=shutil.which('node')
        if node:
            cp=subprocess.run([node,'--check',str(plugin)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr)

if __name__=='__main__': unittest.main()
