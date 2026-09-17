import json
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

SCRIPTS=Path(__file__).resolve().parents[1]/"scripts"
sys.path.insert(0,str(SCRIPTS))

import dsd_attempt
import dsd_task
import parent_tick
import tbag_status


class ProcessSupervisionTests(unittest.TestCase):
    def test_process_observation_parses_cpu_and_zombie_is_not_alive(self):
        cp=SimpleNamespace(returncode=0,stdout="123 1 S+ 4.5 01:02:03\n")
        with mock.patch.object(dsd_attempt,"pid_alive",return_value=True), mock.patch.object(dsd_attempt.subprocess,"run",return_value=cp), mock.patch.object(dsd_attempt.shutil,"which",return_value="/bin/ps"):
            out=dsd_attempt.process_observation(123)
        self.assertTrue(out["alive"])
        self.assertEqual(out["ppid"],1)
        self.assertEqual(out["cpu_percent"],4.5)
        self.assertEqual(out["cpu_seconds"],3723.0)
        zombie=SimpleNamespace(returncode=0,stdout="123 1 Z 0.0 00:00\n")
        with mock.patch.object(dsd_attempt,"pid_alive",return_value=True), mock.patch.object(dsd_attempt.subprocess,"run",return_value=zombie), mock.patch.object(dsd_attempt.shutil,"which",return_value="/bin/ps"):
            self.assertFalse(dsd_attempt.process_observation(123)["alive"])

    def test_finalized_terminal_session_identity_wins_over_stale_task_binding(self):
        with tempfile.TemporaryDirectory() as td:
            event=Path(td)/"event"; event.mkdir()
            (event/"attempt.json").write_text(json.dumps({"session_id":"live-discovery"}))
            (event/"terminal.json").write_text(json.dumps({"session_id":"final-session"}))
            self.assertEqual(dsd_attempt.attempt_session_id({"event_dir":str(event),"session_id":"stale-task"}),"final-session")

    def test_rearmed_observer_does_not_reset_attempt_deadline(self):
        args=SimpleNamespace(run_root=Path("/run"),phase_id="P",task_id="T",event_dir=Path("/event"),interval=15.0,timeout=None)
        observed={"state":"running","role":"implementer","elapsed_seconds":7300.0,"log_bytes":1,"report_bytes":1}
        with mock.patch.object(dsd_attempt,"resolve_event",return_value=Path("/event")), mock.patch.object(dsd_attempt,"command_inspect",return_value=observed), mock.patch.object(dsd_attempt.time,"sleep") as sleep:
            out=dsd_attempt.command_follow(args)
        self.assertEqual(out["follow_status"],"deadline")
        self.assertEqual(out["elapsed_seconds"],7300.0)
        self.assertLess(out["follow_elapsed_seconds"],1.0)
        sleep.assert_not_called()


class PoisonedSessionTests(unittest.TestCase):
    def _attempt(self,root:Path,index:int,session="ses-poison"):
        event=root/f"a{index}"; event.mkdir(parents=True)
        (event/"terminal.json").write_text(json.dumps({
            "exit_code":1,"session_id":session,"report_state":"launcher-placeholder",
            "scope_diff":{"changed_count":0},
        }))
        return {"event_dir":str(event),"role":"verification","status":"report-resume","session_id":session}

    def test_three_no_work_deaths_mark_exact_session_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            task={"role":"verification","attempts":[self._attempt(root,i) for i in range(3)]}
            out=dsd_task.poisoned_session_candidate(task)
            self.assertEqual(out["session_id"],"ses-poison")
            self.assertEqual(out["failures"],3)
            task["attempts"][-1]["event_dir"] = self._attempt(root,9,"different")["event_dir"]
            self.assertIsNone(dsd_task.poisoned_session_candidate(task))

    def test_poison_scan_routes_to_recovery_and_abandons_session(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; task_root=run/"phases"/"P"/"tasks"/"T"; task_root.mkdir(parents=True)
            attempts=[self._attempt(task_root/"attempts",i) for i in range(3)]
            state={"format":dsd_task.FORMAT,"phase_id":"P","task_id":"T","role":"verification","kind":"verification","status":"active","attempts":attempts}
            dsd_task.write_json(task_root/"task.json",state)
            with mock.patch.object(dsd_task,"task_has_live_attempt",return_value=False):
                out=dsd_task.command_poison_scan(SimpleNamespace(run_root=run,phase_id=None))
            self.assertEqual(out["count"],1)
            updated=dsd_task.load_json(task_root/"task.json")
            self.assertEqual(updated["status"],"recovery-required")
            self.assertEqual(updated["abandoned_sessions"],["ses-poison"])
            self.assertEqual(out["marked"][0]["action"],"launch-recovery")

    def test_abandoned_session_cannot_be_explicitly_resumed(self):
        task={"abandoned_sessions":["ses-poison"],"attempts":[]}
        with self.assertRaisesRegex(ValueError,"mechanically abandoned"):
            dsd_attempt.resolve_resume_session(task,"verification","planned","ses-poison",False)


class ParentTickCpuGuardTests(unittest.TestCase):
    def test_cpu_movement_defers_automatic_stall_retirement(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; run.mkdir()
            live={"phase_id":"P","task_id":"T","role":"implementer","event_dir":str(run/"event")}
            old=(__import__('datetime').datetime.fromtimestamp(time.time()-400,__import__('datetime').timezone.utc).isoformat())
            parent_tick.save_loop(run,{"format":parent_tick.FORMAT,"stall_observations":{live["event_dir"]:{"first_seen_at":old,"cpu_seconds_at_first_seen":10.0}}})
            state={"run_id":"R","run_status":"active","live_attempts":[live],"worker_budget":{"max":2,"live":1,"free":1},"backlog_count":1,"waiting_dependency_count":0}
            observed={"state":"running","report_state":"in-progress","report_age_seconds":5000.0,"log_age_seconds":5000.0,"attention":"silent-long-running","process":{"worker":{"cpu_seconds":15.0}}}
            args=SimpleNamespace(run_root=run,phase_id=None,max_steps=12,owner_heartbeat_seconds=1800.0,changed_update_min_seconds=900.0,report_complete_grace_seconds=30.0,stall_confirm_seconds=300.0)
            with mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"}), mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary"}), mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]}), mock.patch.object(parent_tick,"reconcile",return_value=state), mock.patch.object(parent_tick,"inspect_attempt",return_value=observed), mock.patch.object(parent_tick,"retire_attempt") as retire, mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={}):
                out=parent_tick.command_tick(args)
            retire.assert_not_called()
            self.assertEqual(out["monitoring"][0]["automatic_intervention_deferred"],"worker-cpu-still-changing")


class StatusSnapshotTests(unittest.TestCase):
    def test_status_is_read_only_and_labels_registered_progress(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); run=root/"TBag"/"runs"/"R"; run.mkdir(parents=True)
            (run/"run.json").write_text(json.dumps({"format":dsd_task.RUN_FORMAT,"run_id":"R","status":"active","max_workers":4}))
            with mock.patch.object(tbag_status,"_transport",return_value={"available":False,"parent_sessions":[],"observers":[]}), mock.patch.object(tbag_status.dsd_task,"load_run",return_value={"run_id":"R","status":"active","max_workers":4}):
                snap=tbag_status.build_snapshot(root,run_root=run)
            self.assertEqual(snap["format"],"tbag-status-v1")
            self.assertEqual(snap["progress"]["registered_total"],0)
            self.assertEqual(snap["worker_budget"],{"max":4,"live":0,"free":4})
            self.assertFalse((run/"parent-loop.json").exists(),"status snapshot must not mutate orchestration state")

    def test_tui_source_uses_documented_status_slots_and_panel(self):
        tui=(Path(__file__).resolve().parents[1]/"adapters"/"opencode"/"tbag-ui"/"tui.tsx").read_text()
        self.assertIn('from "@opencode/plugin/tui"',tui)
        self.assertIn('append: "prompt.footer.status"',tui)
        self.assertIn('append: "sidebar.content"',tui)
        self.assertIn('append: "session.panel"',tui)
        self.assertIn('slash: { name: "tbag"',tui)
        self.assertNotIn('toggleFullscreen',tui)
        self.assertNotIn('usePlugin',tui)
        self.assertIn('context.keymap.layer',tui)
        self.assertGreater(tui.index('context.keymap.layer'),tui.index('append: "prompt.footer.status"'))
        self.assertIn('TBag/tools/tbag_status.py',tui)
        self.assertIn('CPU ${w().process?.worker?.cpu_percent',tui)
        bridge=(Path(__file__).resolve().parents[1]/"adapters"/"opencode"/"tbag-ui"/"tui.ts").read_text()
        self.assertIn('./tui.tsx',bridge)


class SemanticEvidenceLaneTests(unittest.TestCase):
    def _empty_terminal(self,event:Path,changed:int=0):
        event.mkdir(parents=True,exist_ok=True)
        (event/"terminal.json").write_text(json.dumps({
            "exit_code":1,"report_state":"launcher-placeholder",
            "scope_diff":{"changed_count":changed},
        }))

    def test_empty_fixer_death_restores_needs_fix_and_does_not_stale_review(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; root=run/"phases"/"P"/"tasks"/"T"; root.mkdir(parents=True)
            review_event=root/"review"; review_event.mkdir(); fixer_event=root/"fixer"; self._empty_terminal(fixer_event)
            reviewer={"event_dir":str(review_event),"role":"reviewer","status":"gated"}
            fixer={"event_dir":str(fixer_event),"role":"fixer","status":"started","prior_task_status":"needs-fix"}
            state={"format":dsd_task.FORMAT,"phase_id":"P","task_id":"T","kind":"implementation","role":"implementer","requires_integration":True,"status":"active","attempts":[reviewer,fixer],"last_review":{"outcome":"fail","attempt":str(review_event)}}
            dsd_task.write_json(root/"task.json",state)
            out=dsd_task.command_update_attempt(SimpleNamespace(run_root=run,phase_id="P",task_id="T",event_dir=fixer_event,status="report-resume",gate=None,session_id=None))
            self.assertEqual(out["task_status"],"needs-fix")
            updated=dsd_task.load_json(root/"task.json")
            dsd_task.require_current_review_attempt(updated,reviewer,reason="review outcome")
            dsd_attempt.validate_launch_role(updated,"fixer",continuing=False)

    def test_plain_base_retry_keeps_existing_active_resume_lane(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; root=run/"phases"/"P"/"tasks"/"T"; root.mkdir(parents=True)
            event=root/"implementer"; self._empty_terminal(event)
            attempt={"event_dir":str(event),"role":"implementer","status":"started","prior_task_status":"planned"}
            state={"format":dsd_task.FORMAT,"phase_id":"P","task_id":"T","kind":"implementation","role":"implementer","requires_integration":True,"status":"active","attempts":[attempt]}
            dsd_task.write_json(root/"task.json",state)
            out=dsd_task.command_update_attempt(SimpleNamespace(run_root=run,phase_id="P",task_id="T",event_dir=event,status="report-resume",gate=None,session_id=None))
            self.assertEqual(out["task_status"],"active")

    def test_substantive_newer_fixer_does_stale_old_review(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); review_event=root/"review"; review_event.mkdir(); fixer_event=root/"fixer"; self._empty_terminal(fixer_event,changed=1)
            reviewer={"event_dir":str(review_event),"role":"reviewer","status":"gated"}
            fixer={"event_dir":str(fixer_event),"role":"fixer","status":"report-resume","prior_task_status":"needs-fix"}
            task={"attempts":[reviewer,fixer]}
            with self.assertRaisesRegex(ValueError,"newer semantic"):
                dsd_task.require_current_review_attempt(task,reviewer,reason="review outcome")

    def test_no_graph_analyst_resume_returns_to_standing_fail_lane(self):
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; root=run/"phases"/"P"/"tasks"/"T"; root.mkdir(parents=True)
            review_event=root/"review"; review_event.mkdir(); fixer_event=root/"fixer"; self._empty_terminal(fixer_event)
            recovery_event=root/"recovery"; recovery_event.mkdir(); report=recovery_event/"report.md"; report.write_text("Resume the existing fix lane.\n")
            reviewer={"event_dir":str(review_event),"role":"reviewer","status":"gated"}
            fixer={"event_dir":str(fixer_event),"role":"fixer","status":"report-resume","prior_task_status":"needs-fix"}
            recovery={"event_dir":str(recovery_event),"role":"recovery","tier":"analyst","status":"gated"}
            state={"format":dsd_task.FORMAT,"phase_id":"P","task_id":"T","kind":"implementation","role":"implementer","requires_integration":True,"status":"active","attempts":[reviewer,fixer,recovery],"last_review":{"outcome":"fail","attempt":str(review_event)}}
            dsd_task.write_json(root/"task.json",state)
            out=dsd_task.command_analysis_result(SimpleNamespace(run_root=run,phase_id="P",task_id="T",report=report,outcome="resume"))
            self.assertEqual(out["status"],"needs-fix")
            self.assertEqual(dsd_task.load_json(root/"task.json")["status"],"needs-fix")


if __name__=="__main__": unittest.main()
