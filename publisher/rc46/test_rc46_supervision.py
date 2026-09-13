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
        self.assertIn('toggleFullscreen',tui)
        self.assertIn('TBag", "tools", "tbag_status.py"',tui)


if __name__=="__main__": unittest.main()
