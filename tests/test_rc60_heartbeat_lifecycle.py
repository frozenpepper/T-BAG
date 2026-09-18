import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import parent_tick


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

    def test_fast_pulse_wakes_when_started_attempt_process_stops_without_terminal(self):
        result = self.pulse("active", [{
            "phase_id": "P1", "task_id": "T1",
            "attempts": [{"status": "started", "event_dir": "/no/such/event", "_live": False}],
        }])
        self.assertTrue(result["wake_parent"])
        self.assertEqual(result["reason"], "attempt-stopped")
        self.assertFalse(result["stopped_attempts"][0]["terminal_present"])

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

    def test_active_without_started_attempt_uses_only_slow_health_lane(self):
        result = self.pulse("active", [])
        self.assertEqual(result["heartbeat_state"], "idle-recovery")
        self.assertFalse(result["wake_parent"])

    def test_adapters_expose_two_lanes_and_true_unenrollment(self):
        core = (ROOT / "adapters/tbag-opencode-transport-core.js").read_text()
        self.assertIn("COMPLETION_PULSE_MS", core)
        self.assertIn("HEALTH_HEARTBEAT_MS", core)
        self.assertIn("function removeRunHeartbeat", core)
        self.assertIn('status === "human-blocked"', core)
        self.assertIn('status === "paused-by-user"', core)
        self.assertIn('status === "completed" || status === "abandoned"', core)
        self.assertNotIn("const HEARTBEAT_MS =", core)
        for rel in ("adapters/opencode/tbag.js", "adapters/opencode/tbag-v2.js"):
            source = (ROOT / rel).read_text()
            self.assertIn("../tbag-opencode-transport-core.js", source)
            self.assertIn("startHeartbeatTimers", source)

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
