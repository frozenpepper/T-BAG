import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import parent_tick
import dsd_task


class RC60HeartbeatLifecycleTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(run_root=Path("/project/TBag/runs/R"), phase_id=None)

    def pulse(self, status, tasks):
        with patch.object(parent_tick.dsd_task, "load_run", return_value={"run_id": "R", "status": status}), \
             patch.object(parent_tick.dsd_task, "iter_run_tasks", return_value=iter(tasks)), \
             patch.object(parent_tick.dsd_task, "attempt_is_live") as live:
            live.side_effect = lambda attempt: bool(attempt.get("_live"))
            return parent_tick.command_pulse(self.args())

    def test_fast_pulse_is_silent_while_started_attempt_is_running(self):
        result = self.pulse("active", [{
            "phase_id": "P1", "task_id": "T1",
            "attempts": [{"status": "started", "event_dir": "/no/such/event", "_live": True}],
        }])
        self.assertEqual(result["heartbeat_state"], "running")
        self.assertFalse(result["wake_parent"])
        self.assertEqual(len(result["live_attempts"]), 1)
        self.assertEqual(result["live_attempts"][0]["task_id"], "T1")

    def test_fast_pulse_wakes_when_started_attempt_process_stops_without_terminal(self):
        result = self.pulse("active", [{
            "phase_id": "P1", "task_id": "T1",
            "attempts": [{"status": "started", "event_dir": "/no/such/event", "_live": False}],
        }])
        self.assertTrue(result["wake_parent"])
        self.assertEqual(result["reason"], "attempt-stopped")
        self.assertFalse(result["stopped_attempts"][0]["terminal_present"])
        self.assertEqual(result["live_attempts"], [])

    def test_fast_pulse_ignores_scheduler_and_human_block_semantics(self):
        result = self.pulse("active", [{
            "phase_id": "P1", "task_id": "BLOCKED", "status": "blocked", "attempts": [],
        }])
        self.assertEqual(result["heartbeat_state"], "idle-recovery")
        self.assertFalse(result["wake_parent"])

    def test_wait_pause_and_terminal_states_are_quiescent_without_task_scan(self):
        expected = {
            "human-blocked": "waiting",
            "paused-by-user": "paused",
            "completed": "ended",
            "abandoned": "ended",
        }
        for status, heartbeat in expected.items():
            with self.subTest(status=status), \
                 patch.object(parent_tick.dsd_task, "load_run", return_value={"run_id": "R", "status": status}), \
                 patch.object(parent_tick.dsd_task, "iter_run_tasks") as tasks:
                result = parent_tick.command_pulse(self.args())
                self.assertEqual(result["heartbeat_state"], heartbeat)
                self.assertFalse(result["wake_parent"])
                tasks.assert_not_called()

    def test_open_owner_question_suspends_pulse_even_while_run_active(self):
        with patch.object(parent_tick.dsd_task,"load_run",return_value={"run_id":"R","status":"active"}), \
             patch.object(parent_tick,"load_loop",return_value={"format":parent_tick.FORMAT,"owner_wait":{"open":True,"question_id":"human-decision:P:T:1"}}), \
             patch.object(parent_tick.dsd_task,"iter_run_tasks") as tasks:
            result=parent_tick.command_pulse(self.args())
        self.assertEqual(result["heartbeat_state"],"waiting")
        self.assertEqual(result["reason"],"owner-question-open")
        self.assertEqual(result["owner_question_id"],"human-decision:P:T:1")
        self.assertFalse(result["wake_parent"])
        tasks.assert_not_called()

    def test_wait_and_resume_owner_are_durable_transport_state(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as td:
            run=Path(td)/"run"; run.mkdir()
            (run/"run.json").write_text(json.dumps({"format":dsd_task.RUN_FORMAT,"run_id":"R","project_root":td,"runtime_root":str(Path(td)/"runtime"),"status":"active"}))
            opened=parent_tick.command_wait_owner(SimpleNamespace(run_root=run,question_id="runtime-config:grunt"))
            self.assertTrue(opened["heartbeat_suspended"])
            self.assertEqual(parent_tick.load_loop(run)["owner_wait"]["question_id"],"runtime-config:grunt")
            closed=parent_tick.command_resume_owner(SimpleNamespace(run_root=run,question_id="runtime-config:grunt"))
            self.assertTrue(closed["heartbeat_resumed"])
            self.assertNotIn("owner_wait",parent_tick.load_loop(run))

    def test_active_without_started_attempt_enters_idle_recovery_without_wake(self):
        result = self.pulse("active", [])
        self.assertEqual(result["heartbeat_state"], "idle-recovery")
        self.assertFalse(result["wake_parent"])
        self.assertEqual(result["live_preparations"], [])

    def test_fast_pulse_surfaces_durable_launch_preparation(self):
        import json, os, tempfile
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            task_root = Path(td) / "task"
            task_root.mkdir()
            marker = task_root / "launch-preparation.json"
            marker.write_text(json.dumps({"pid": os.getpid(), "role": "implementer"}))
            task = {"phase_id": "P1", "task_id": "T1", "attempts": []}
            with patch.object(parent_tick.dsd_task, "load_run", return_value={"run_id": "R", "status": "active"}), \
                 patch.object(parent_tick.dsd_task, "iter_run_tasks", return_value=iter([task])), \
                 patch.object(parent_tick.dsd_task, "task_root", return_value=task_root):
                result = parent_tick.command_pulse(SimpleNamespace(run_root=run, phase_id=None))
            self.assertEqual(result["heartbeat_state"], "running")
            self.assertFalse(result["wake_parent"])
            self.assertEqual(result["reason"], "launch-preparation-running")
            self.assertEqual(result["live_preparations"][0]["preparation_pid"], os.getpid())

    def test_fast_pulse_wakes_for_dead_durable_launch_preparation(self):
        import json, tempfile
        with tempfile.TemporaryDirectory() as td:
            run = Path(td) / "run"
            task_root = Path(td) / "task"
            task_root.mkdir()
            marker = task_root / "launch-preparation.json"
            marker.write_text(json.dumps({"pid": 12345, "role": "implementer"}))
            task = {"phase_id": "P1", "task_id": "T1", "attempts": []}
            with patch.object(parent_tick.dsd_task, "load_run", return_value={"run_id": "R", "status": "active"}), \
                 patch.object(parent_tick.dsd_task, "iter_run_tasks", return_value=iter([task])), \
                 patch.object(parent_tick.dsd_task, "task_root", return_value=task_root), \
                 patch.object(parent_tick.dsd_attempt, "pid_alive", return_value=False):
                result = parent_tick.command_pulse(SimpleNamespace(run_root=run, phase_id=None))
            self.assertTrue(result["wake_parent"])
            self.assertEqual(result["reason"], "preparation-stopped")
            self.assertEqual(result["stopped_preparations"][0]["task_id"], "T1")

    def test_adapters_expose_two_lanes_and_true_unenrollment(self):
        core = (ROOT / "adapters/tbag-opencode-transport-core.js").read_text()
        self.assertIn("COMPLETION_PULSE_MS", core)
        self.assertIn("HEALTH_HEARTBEAT_MS", core)
        self.assertIn("function removeRunHeartbeat", core)
        self.assertIn('status === "human-blocked"', core)
        self.assertIn("owner_wait", core)
        self.assertIn('packet.classification === "owner-question-open"', core)
        self.assertIn('status === "paused-by-user"', core)
        self.assertIn('status === "completed" || status === "abandoned"', core)
        self.assertNotIn("const HEARTBEAT_MS =", core)
        self.assertIn('["running", "idle-recovery"].includes(item.heartbeatState)', core)
        self.assertIn('args?.activity_hint === "launch"', core)
        self.assertIn('typeof onPulse === "function"', core)
        for rel in ("adapters/opencode/tbag.js", "adapters/opencode/tbag-v2.js"):
            source = (ROOT / rel).read_text()
            self.assertIn("../tbag-opencode-transport-core.js", source)
            self.assertIn("startHeartbeatTimers", source)
            self.assertIn("repairTransportFromPacket", source)
            self.assertIn("live_preparations", source)
            self.assertIn("watchPreparation", source)
            self.assertIn("onPulse:", source)
            self.assertIn('"health"', source)

    def test_owner_update_reasons_distinguish_wait_pause_and_terminal(self):
        waiting = parent_tick.update_due(
            {},
            {"run_status": "human-blocked", "human_blocks": [{"task_id": "T"}]},
            [],
            "run-human-blocked",
            heartbeat_seconds=900.0,
            changed_min_seconds=900.0,
        )
        self.assertIn("owner-decision-required", waiting["reasons"])
        self.assertNotIn("run-terminal-state", waiting["reasons"])

        paused = parent_tick.update_due(
            {},
            {"run_status": "paused-by-user", "human_blocks": []},
            [],
            "run-paused-by-user",
            heartbeat_seconds=900.0,
            changed_min_seconds=900.0,
        )
        self.assertIn("run-paused", paused["reasons"])
        self.assertNotIn("run-terminal-state", paused["reasons"])

        ended = parent_tick.update_due(
            {},
            {"run_status": "completed", "human_blocks": []},
            [],
            "run-completed",
            heartbeat_seconds=900.0,
            changed_min_seconds=900.0,
        )
        self.assertIn("run-terminal-state", ended["reasons"])

if __name__ == "__main__":
    unittest.main()
