import json, os, signal, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import dsd_task, dsd_attempt, parent_tick


class Rc45ProtocolTests(unittest.TestCase):
    def test_explicit_routing_token_accepts_bounded_decoration_not_prose(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/"report.md"
            for text in ("PASS — all checks green\n", "**PASS**\n", "**PASS** — reviewer summary\n", "# PASS\n", "* PASS\n", "`PASS`\n", "# T-BAG Phase Auditor report\nPASS\n", "## Phase gate\n**PASS** — all predicates green\n", "ESCALATE CAPABILITY: provider exhausted\n"):
                report.write_text(text)
                role="verification" if not text.startswith("ESCALATE") else "reviewer"
                expected="pass" if role=="verification" else "capability"
                self.assertEqual(dsd_task.declared_report_outcome(report,role,required=True),expected)
            for invalid in ("The evidence looks like PASS to me.\n", "# Verdict: PASS\n", "# Phase gate\nNarrative first.\nPASS\n"):
                report.write_text(invalid)
                with self.assertRaisesRegex(ValueError,"must begin"):
                    dsd_task.declared_report_outcome(report,"verification",required=True)

    def test_gate_rejects_duplicate_task_ids(self):
        args=SimpleNamespace(run_root=Path('/run'),phase_id='P',task_id=['T1','T1'],event_dir=None)
        with self.assertRaisesRegex(ValueError,"duplicate --task-id"):
            dsd_attempt.command_gate(args)

    def test_followup_parser_handles_none_footer_and_wrapped_bullet(self):
        with tempfile.TemporaryDirectory() as td:
            report=Path(td)/"report.md"
            report.write_text("PASS\n\n## Follow-up obligations\nNone.\nAttempt: x\nBaseline: y\n")
            self.assertEqual(dsd_task.review_followup_items(report),[])
            report.write_text("PASS\n\n## Follow-up obligations\n- Preserve the public API while changing\n  the internal composition boundary.\nAttempt: x\nBaseline: y\n")
            self.assertEqual(dsd_task.review_followup_items(report),["Preserve the public API while changing the internal composition boundary."])

    def test_superseded_mutable_task_can_succeed_through_integrated_successor(self):
        task={"task_id":"OLD","status":"superseded","requires_integration":True}
        with mock.patch.object(dsd_task,"open_review_findings",return_value=[]), mock.patch.object(dsd_task,"dependency_satisfied",return_value=True) as dep:
            self.assertTrue(dsd_task._phase_task_success(Path('/run'),'P',task))
            dep.assert_called_once()

    def test_advance_quarantines_bad_action_and_continues_unrelated_work(self):
        args=SimpleNamespace(run_root=Path('/run'),phase_id=None,max_steps=6)
        bad={"action":"record-verification-result","phase_id":"P","task_id":"BAD","report":"/tmp/bad.md"}
        good={"action":"record-phase-gate","phase_id":"P","task_id":"GOOD","report":"/tmp/good.md"}
        states=[{"first_useful_actions":[bad,good]},{"first_useful_actions":[bad,good]},{"first_useful_actions":[bad]}]
        with mock.patch.object(dsd_task,"command_reconcile_run",side_effect=states), \
             mock.patch.object(dsd_task,"command_verification_result",side_effect=ValueError("bad report")), \
             mock.patch.object(dsd_task,"command_phase_gate",return_value={"recorded":True}) as phase_gate:
            out=dsd_task.command_advance(args)
        phase_gate.assert_called_once()
        self.assertEqual(out["stopped"],"control-error")
        self.assertEqual(len(out["blocked_actions"]),1)
        self.assertEqual(out["blocked_actions"][0]["task_id"],"BAD")
        self.assertEqual(out["applied"][0]["task_id"],"GOOD")


class Rc45ParentTickTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.run=Path(self.tmp.name)/"run"; self.run.mkdir()
        self.args=SimpleNamespace(
            run_root=self.run,phase_id=None,max_steps=12,owner_heartbeat_seconds=1800.0,
            changed_update_min_seconds=900.0,report_complete_grace_seconds=30.0,stall_confirm_seconds=300.0,
        )
    def tearDown(self): self.tmp.cleanup()

    def base_state(self,**extra):
        state={"run_id":"R","run_status":"active","worker_budget":{"max":2,"live":0,"free":2},"backlog_count":0,"waiting_dependency_count":0}
        state.update(extra); return state

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"quiescent","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    def test_quiescent_active_run_is_completion_candidate_and_update_due(self,_load,_advance,_owner):
        with mock.patch.object(parent_tick,"reconcile",return_value=self.base_state()):
            out=parent_tick.command_tick(self.args)
        self.assertEqual(out["classification"],"completion-candidate")
        self.assertEqual(out["turn"],"finish-or-replan")
        self.assertNotIn("owner_update",out)
        self.assertIn("project-end-candidate",out["owner_notice"]["reasons"])
        token=out["owner_notice"]["ack_token"]
        ack=parent_tick.command_ack_update(SimpleNamespace(run_root=self.run,token=token))
        self.assertTrue(ack["acknowledged"])

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    @mock.patch.object(parent_tick,"retire_attempt",return_value={"retired":True})
    @mock.patch.object(parent_tick,"inspect_attempt",return_value={"state":"running","report_state":"present","report_age_seconds":45.0,"log_age_seconds":20.0})
    def test_final_report_without_terminal_is_retired_mechanically(self,_inspect,_retire,_load,_advance,_owner):
        live={"phase_id":"P","task_id":"T","role":"discovery","event_dir":str(self.run/'e')}
        states=[self.base_state(live_attempts=[live],backlog_count=1,worker_budget={"max":2,"live":1,"free":1}), self.base_state(first_useful_actions=[{"action":"gate-finished-attempt","phase_id":"P","task_id":"T"}],backlog_count=1)]
        with mock.patch.object(parent_tick,"reconcile",side_effect=states):
            out=parent_tick.command_tick(self.args)
        _retire.assert_called_once()
        self.assertTrue(out["attention"][0]["retirement_requested"]["retired"])
        self.assertIn("worker-retired",out["owner_notice"]["reasons"])
        self.assertNotIn("monitoring",out)

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"quiescent","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    @mock.patch.object(parent_tick,"retire_attempt",return_value={"retired":True})
    @mock.patch.object(parent_tick,"inspect_attempt",return_value={"state":"running","report_state":"in-progress","report_age_seconds":4000.0,"log_age_seconds":4000.0,"attention":"silent-long-running"})
    def test_confirmed_silent_stall_is_bounded_then_retired(self,_inspect,_retire,_load,_advance,_owner):
        live={"phase_id":"P","task_id":"T","role":"implementer","event_dir":str(self.run/'e')}
        parent_tick.save_loop(self.run,{"format":parent_tick.FORMAT,"stall_observations":{live["event_dir"]:{"first_seen_at":__import__('datetime').datetime.fromtimestamp(time.time()-400,__import__('datetime').timezone.utc).isoformat()}}})
        states=[self.base_state(live_attempts=[live],backlog_count=1,worker_budget={"max":2,"live":1,"free":1}), self.base_state(first_useful_actions=[{"action":"gate-finished-attempt","phase_id":"P","task_id":"T"}],backlog_count=1)]
        with mock.patch.object(parent_tick,"reconcile",side_effect=states):
            out=parent_tick.command_tick(self.args)
        _retire.assert_called_once()
        self.assertTrue(out["attention"][0]["retirement_requested"]["retired"])
        self.assertNotIn("monitoring",out)


    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    def test_tick_filters_quarantined_action_but_exposes_other_work(self,_load,_owner):
        bad={"action":"record-verification-result","phase_id":"P","task_id":"BAD","report":"/tmp/bad.md"}
        good={"action":"launch-worker","phase_id":"P","task_id":"GOOD"}
        blocked={"key":parent_tick.action_key(bad),"action":bad["action"],"phase_id":"P","task_id":"BAD","error":"bad report"}
        with mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","blocked_actions":[blocked]}), \
             mock.patch.object(parent_tick,"reconcile",return_value=self.base_state(first_useful_actions=[bad,good],backlog_count=2)):
            out=parent_tick.command_tick(self.args)
        self.assertEqual(out["classification"],"actions-ready")
        self.assertEqual(out["actions"],[good])
        self.assertEqual(out["blocked_actions"][0]["task_id"],"BAD")

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    def test_inflight_launch_preparation_is_yield_not_recovery(self,_load,_poison,_advance,_owner):
        action={"action":"launch-ready-task","phase_id":"P","task_id":"T","role":"implementer"}
        state=self.base_state(first_useful_actions=[action],backlog_count=1)
        with mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"_launch_action_blocker",return_value="PREPARATION_IN_FLIGHT: P/T launch preparation is already running (pid=123)"), \
             mock.patch.object(parent_tick,"disk_usage_for_tick",return_value={}):
            out=parent_tick.command_tick(self.args)
        self.assertEqual(out["classification"],"workers-preparing")
        self.assertEqual(out["turn"],"yield")
        self.assertEqual(out["preparing"],[{"phase_id":"P","task_id":"T","action":"launch-ready-task"}])
        self.assertNotIn("blocked_actions",out)

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    def test_three_identical_action_ticks_stop_repeating_and_intervene(self,_load,_poison,_advance,_owner):
        action={"action":"launch-analyst-discovery","phase_id":"P","task_id":"T"}
        state=self.base_state(first_useful_actions=[action],backlog_count=1)
        with mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"_launch_action_blocker",return_value=None), \
             mock.patch.object(parent_tick,"disk_usage_for_tick",return_value={}):
            first=parent_tick.command_tick(self.args)
            second=parent_tick.command_tick(self.args)
            third=parent_tick.command_tick(self.args)
        self.assertEqual(first["classification"],"actions-ready")
        self.assertEqual(second["classification"],"actions-ready")
        self.assertEqual(third["classification"],"loop-suspected")
        self.assertEqual(third["turn"],"intervene")
        self.assertNotIn("actions",third)
        self.assertEqual(third["loop_suspected"]["count"],3)

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    @mock.patch.object(parent_tick.dsd_task,"command_set_run_status",return_value={"status":"human-blocked"})
    def test_human_block_is_native_question_boundary_not_notice(self,_status,_load,_poison,_advance,_owner):
        question={"id":"human-decision:P:T:1","blocking":True,"required_interface":"native-question","header":"T-BAG needs you","question":"Choose","options":[]}
        state=self.base_state(human_blocks=[{"phase_id":"P","task_id":"T","action":"await-human-decision","owner_question":question}],backlog_count=1)
        with mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"disk_usage_for_tick",return_value={}):
            out=parent_tick.command_tick(self.args)
        self.assertEqual(out["classification"],"owner-question-required")
        self.assertEqual(out["turn"],"ask-owner")
        self.assertTrue(out["owner_question_required"])
        self.assertEqual(out["owner_questions"],[question])
        self.assertNotIn("owner_notice",out)
        self.assertEqual(out["run_status"],"human-blocked")

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"quiescent","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    @mock.patch.object(parent_tick,"inspect_attempt",return_value={"state":"running","report_state":"in-progress","report_age_seconds":5.0,"log_age_seconds":1.0,"elapsed_seconds":20.0})
    def test_stable_worker_tick_is_compact_and_marks_unchanged(self,_inspect,_load,_poison,_advance,_owner):
        live={"phase_id":"P","task_id":"T","role":"implementer","event_dir":str(self.run/'e')}
        state=self.base_state(live_attempts=[live],backlog_count=1,worker_budget={"max":2,"live":1,"free":1})
        with mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"disk_usage_for_tick",return_value={"owned_total_bytes":123456}):
            first=parent_tick.command_tick(self.args)
            second=parent_tick.command_tick(self.args)
        self.assertTrue(first["state_changed"])
        self.assertFalse(second["state_changed"])
        self.assertEqual(second["classification"],"workers-running")
        self.assertNotIn("monitoring",second)
        self.assertNotIn("attention",second)
        self.assertNotIn("disk_usage",second)
        self.assertNotIn("owner_update",second)
        self.assertNotIn("live_attempts",second)
        self.assertLess(len(json.dumps(second)),900)

    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})
    @mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"quiescent","applied":[]})
    @mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]})
    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})
    @mock.patch.object(parent_tick.dsd_task,"command_set_run_status",side_effect=ValueError("ADVANCE_BEFORE_HUMAN_BLOCK: independent authorized work remains: P/X[ready]. Run parent_tick.py tick"))
    def test_human_block_transition_error_is_actionable_not_tick_crash(self,_status,_load,_poison,_advance,_owner):
        question={"id":"human-decision:P:T:1","blocking":True,"required_interface":"native-question","header":"T-BAG needs you","question":"Choose","options":[]}
        state=self.base_state(human_blocks=[{"phase_id":"P","task_id":"T","action":"await-human-decision","owner_question":question}],backlog_count=1)
        with mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"disk_usage_for_tick",return_value={}):
            out=parent_tick.command_tick(self.args)
        self.assertTrue(out["run_status_transition"]["deferred"])
        self.assertIn("ADVANCE_BEFORE_HUMAN_BLOCK",out["run_status_transition"]["error"])
        self.assertIn("Do not inspect control-plane source",out["run_status_transition"]["next"])

    @mock.patch.object(parent_tick.dsd_task,"command_set_run_status",return_value={"status":"completed"})
    def test_finish_refuses_nonquiescent_and_accepts_completion_candidate(self,set_status):
        with mock.patch.object(parent_tick,"reconcile",return_value=self.base_state(backlog_count=1)):
            with self.assertRaisesRegex(ValueError,"not a completion candidate"):
                parent_tick.command_finish(SimpleNamespace(run_root=self.run,phase_id=None,reason="done"))
        with mock.patch.object(parent_tick,"reconcile",return_value=self.base_state()):
            out=parent_tick.command_finish(SimpleNamespace(run_root=self.run,phase_id=None,reason="plan exhausted"))
        self.assertTrue(out["completed"]); set_status.assert_called_once()


class Rc45RetirementTests(unittest.TestCase):
    def test_retire_targets_worker_process_group_and_preserves_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); event=root/"event"; event.mkdir(); (event/"attempt.json").write_text(json.dumps({"worker_pid":1234,"launcher_pid":9999}))
            args=SimpleNamespace(run_root=root,phase_id="P",task_id="T",event_dir=event,reason="test")
            task={"attempts":[{"event_dir":str(event),"role":"implementer","status":"started"}]}
            with mock.patch.object(dsd_task,"load_task",return_value=task), mock.patch.object(dsd_attempt,"resolve_event",return_value=event), mock.patch.object(dsd_attempt,"command_inspect",return_value={"state":"running","report_state":"present","elapsed_seconds":50,"log_age_seconds":40}), mock.patch.object(dsd_attempt,"pid_alive",return_value=True), mock.patch.object(dsd_attempt.os,"getpgid",return_value=1234), mock.patch.object(dsd_attempt.os,"killpg") as killpg:
                out=dsd_attempt.command_retire(args)
            self.assertTrue(out["retired"]); self.assertEqual(out["mode"],"worker-process-group")
            killpg.assert_called_once_with(1234,signal.SIGTERM)
            self.assertTrue((event/"retirement-request.json").is_file())


if __name__ == '__main__': unittest.main()
