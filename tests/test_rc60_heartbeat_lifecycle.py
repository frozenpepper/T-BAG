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
        return SimpleNamespace(run_root=Path("/project/TBag/runtime/R"), phase_id=None)

    def pulse(self, status, state=None):
        state = state or {}
        with patch.object(parent_tick.dsd_task, "load_run", return_value={"run_id": "R", "status": status}), \
             patch.object(parent_tick, "reconcile", return_value={
                 "run_id": "R",
                 "run_status": status,
                 "first_useful_actions": [],
                 "live_attempts": [],
                 "human_blocks": [],
                 "unresolved_state": [],
                 "backlog_count": 0,
                 "waiting_dependency_count": 0,
                 **state,
             }):
            return parent_tick.command_pulse(self.args())

    def test_fast_pulse_is_silent_while_workers_are_still_running(self):
        result = self.pulse("active", {"live_attempts": [{"task_id": "T1", "phase_id": "P1"}]})
        self.assertEqual(result["heartbeat_state"], "running")
        self.assertFalse(result["wake_parent"])

    def test_fast_pulse_wakes_only_for_finished_attempt(self):
        result = self.pulse("active", {
            "first_useful_actions": [{
                "action": "gate-finished-attempt",
                "task_id": "T1",
                "phase_id": "P1",
                "event_dir": "/project/TBag/runtime/R/P1/T1/attempt",
            }]
        })
        self.assertTrue(result["wake_parent"])
        self.assertEqual(result["reason"], "attempt-finished")
        self.assertEqual(result["completed_attempts"][0]["task_id"], "T1")

    def test_wait_pause_and_terminal_states_are_quiescent(self):
        expected = {
            "human-blocked": "waiting",
            "paused-by-user": "paused",
            "completed": "ended",
            "abandoned": "ended",
        }
        for status, heartbeat in expected.items():
            with self.subTest(status=status), patch.object(parent_tick, "reconcile") as reconcile:
                result = self.pulse(status)
                self.assertEqual(result["heartbeat_state"], heartbeat)
                self.assertFalse(result["wake_parent"])
                reconcile.assert_not_called()

    def test_active_without_live_worker_uses_only_slow_health_lane(self):
        result = self.pulse("active", {"unresolved_state": [{"task_id": "T1"}]})
        self.assertEqual(result["heartbeat_state"], "idle-recovery")
        self.assertFalse(result["wake_parent"])

    def test_adapters_expose_two_lanes_and_quiescent_states(self):
        for rel in ("adapters/opencode/tbag.js", "adapters/opencode/tbag-v2.js"):
            source = (ROOT / rel).read_text()
            self.assertIn("COMPLETION_PULSE_MS", source)
            self.assertIn("HEALTH_HEARTBEAT_MS", source)
            self.assertIn('status === "human-blocked"', source)
            self.assertIn('status === "paused-by-user"', source)
            self.assertIn('status === "completed" || status === "abandoned"', source)
            self.assertIn('"health"', source)
            self.assertNotIn("const HEARTBEAT_MS =", source)

    def test_owner_update_reasons_distinguish_wait_pause_and_terminal(self):
        loop = {}
        waiting = parent_tick.update_due(
            loop,
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
