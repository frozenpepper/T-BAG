import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import dsd_task
import parent_tick
import scope_snapshot


class CanonicalScopeEvidenceTests(unittest.TestCase):
    def test_inline_and_path_scope_evidence_share_one_reader(self):
        inline = {"changed_count": 0, "changed_since_attempt_baseline": []}
        self.assertEqual(scope_snapshot.comparison_changed_count(inline), 0)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "scope-diff.json"
            path.write_text(json.dumps(inline))
            self.assertEqual(scope_snapshot.comparison_changed_count(str(path)), 0)
            self.assertEqual(scope_snapshot.comparison_changed_count("scope-diff.json", relative_to=root), 0)

    def test_poison_candidate_accepts_terminal_scope_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            attempts=[]
            for index in range(3):
                event=root/f"implementer-{index+1}"; event.mkdir()
                scope=event/"scope-diff.json"; scope.write_text(json.dumps({"changed_count":0,"changed_since_attempt_baseline":[]}))
                (event/"terminal.json").write_text(json.dumps({
                    "exit_code":1,"report_state":"launcher-placeholder","session_id":"ses-poison","scope_diff":str(scope)
                }))
                attempts.append({"role":"implementer","status":"report-resume","event_dir":str(event),"session_id":"ses-poison"})
            candidate=dsd_task.poisoned_session_candidate({"role":"implementer","attempts":attempts})
            self.assertIsNotNone(candidate)
            self.assertEqual(candidate["session_id"],"ses-poison")


class ActionabilityInvariantTests(unittest.TestCase):
    def test_durable_status_dominates_stale_attempt_residue(self):
        residue={"role":"implementer","status":"report-resume","event_dir":"/nonexistent/attempt","session_id":"ses-old"}
        self.assertIsNone(dsd_task._reconcile_action(Path("/tmp/run"),"p",{
            "task_id":"old","status":"superseded","attempts":[residue],"requires_integration":True,
        }))
        accepted=dsd_task._reconcile_action(Path("/tmp/run"),"p",{
            "task_id":"land","status":"accepted","attempts":[residue],"requires_integration":True,
        })
        self.assertEqual(accepted["action"],"integrate-accepted-task")
        integrated_with_obligation=dsd_task._reconcile_action(Path("/tmp/run"),"p",{
            "task_id":"integrated-followup","status":"integrated","attempts":[residue],"requires_integration":True,
            "review_history":[{"findings":[{"finding_id":"F1","status":"open","text":"carry me"}]}],
        })
        self.assertEqual(integrated_with_obligation["action"],"prepare-followup-triage")
        recovery=dsd_task._reconcile_action(Path("/tmp/run"),"p",{
            "task_id":"recover","status":"recovery-required","attempts":[residue],"requires_integration":True,
        })
        self.assertEqual(recovery["action"],"launch-recovery")

    def test_housekeeping_default_receipt_is_counts_only(self):
        self.assertEqual(
            dsd_task._runtime_reaped_counts({"cleaned":[{"task_id":str(i)} for i in range(90)],"orphan_databases_removed":["x"]}),
            {"cleaned_count":90,"orphan_databases_removed_count":1},
        )


class ParentEdgePolicyTests(unittest.TestCase):
    def test_acknowledged_stall_is_not_immediately_renotified(self):
        state={"run_status":"active","backlog_count":1,"waiting_dependency_count":0,"live_attempts":[],"human_blocks":[],"first_useful_actions":[]}
        monitors=[{"phase_id":"p","task_id":"t","attention":"silent-long-running"}]
        first=parent_tick.update_due({},state,monitors,"workers-running",heartbeat_seconds=1800,changed_min_seconds=900)
        self.assertTrue(first["due"])
        loop={
            "last_owner_update_at":parent_tick.now(),
            "last_owner_update_signature":first["signature"],
            "last_owner_update_reasons":first["reasons"],
        }
        second=parent_tick.update_due(loop,state,monitors,"workers-running",heartbeat_seconds=1800,changed_min_seconds=900)
        self.assertFalse(second["due"])

    def test_compact_advance_drops_duplicate_quiescent_state(self):
        self.assertIsNone(parent_tick.compact_advance({"applied":[],"stopped":"quiescent","state":{"runtime_reaped":{"cleaned_count":90}}}))

    def test_deadline_is_hard_boundary_for_silent_worker_and_observer(self):
        event="/tmp/tbag-rc52-attempt"
        state={
            "run_id":"R","run_status":"active","worker_budget":{"max":1,"live":1,"free":0},
            "backlog_count":1,"waiting_dependency_count":0,"first_useful_actions":[],"human_blocks":[],"unresolved_state":[],
            "live_attempts":[{"phase_id":"p","task_id":"t","role":"implementer","event_dir":event}],
        }
        loop={"format":parent_tick.FORMAT,"stall_observations":{
            event:{"first_seen_at":"2000-01-01T00:00:00+00:00","cpu_seconds_at_first_seen":1.0}
        }}
        observed={
            "state":"running","attention":"silent-long-running","report_state":"launcher-placeholder",
            "report_age_seconds":7200,"log_age_seconds":7200,
            "deadline":{"exceeded":True,"limit_seconds":7200,"overrun_seconds":3600},
            "process":{"worker":{"cpu_seconds":500.0}},
        }
        args=SimpleNamespace(
            run_root=Path("/tmp/run"),phase_id=None,max_steps=12,report_complete_grace_seconds=30,
            stall_confirm_seconds=300,owner_heartbeat_seconds=1800,changed_update_min_seconds=900,
        )
        with mock.patch.object(parent_tick,"load_loop",return_value=loop), \
             mock.patch.object(parent_tick,"save_loop"), \
             mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"}), \
             mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"applied":[],"stopped":"quiescent","state":state}), \
             mock.patch.object(parent_tick.dsd_task,"command_poison_scan",return_value={"count":0,"marked":[]}), \
             mock.patch.object(parent_tick,"reconcile",return_value=state), \
             mock.patch.object(parent_tick,"inspect_attempt",return_value=observed), \
             mock.patch.object(parent_tick,"transport_registry",return_value={"adapter_pid":1,"observers":[]}), \
             mock.patch.object(parent_tick,"observer_for",return_value=None), \
             mock.patch.object(parent_tick,"retire_attempt",return_value={"retired":True}) as retire, \
             mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={}):
            out=parent_tick.command_tick(args)
        retire.assert_called_once()
        self.assertNotIn("observer_rearm_required",out)
        self.assertNotIn("monitoring",out)
        self.assertEqual(out["attention"][0]["observer_attention"],"observer-not-rearmed-after-attempt-deadline")


if __name__ == "__main__":
    unittest.main()
