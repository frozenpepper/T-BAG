import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import dsd_task, dsd_attempt, dsd_workspace, run_worker

class RC55SimplificationTests(unittest.TestCase):
    def test_default_runtime_is_project_local(self):
        project=Path(tempfile.mkdtemp())/"project"
        project.mkdir()
        self.assertEqual(dsd_task._default_runtime_root(project,"RUN"), project/"TBag"/"runtime"/"RUN")

    def test_resumable_context_does_not_forbid_intentional_cold_launch(self):
        task={"kind":"implementation","role":"implementer","status":"active","attempts":[{"status":"report-resume","session_id":"old-session"}]}
        dsd_attempt.validate_launch_role(task,"implementer",continuing=False)

    def test_read_only_role_can_use_analysis_view_for_mutating_task(self):
        task={"requires_integration":True}
        self.assertTrue(dsd_workspace.task_can_use_analysis_view(task,"discovery","plain read-only diagnosis"))

    def test_worker_launch_gate_is_run_local(self):
        project=Path(tempfile.mkdtemp())/"project"; run=project/"TBag"/"runs"/"R"; run.mkdir(parents=True)
        (run/"run.json").write_text(__import__("json").dumps({"project_root":str(project)}))
        self.assertEqual(run_worker.launch_gate_root(run),project/"TBag"/"runtime"/"launch-start-gate")

    def test_opencode_adapter_has_no_whole_stdout_json_parse_contract(self):
        source=(ROOT/"adapters/opencode/tbag.js").read_text()
        self.assertIn("function structuredObjects",source)
        self.assertIn("backgroundLaunchCommand",source)
        self.assertIn("repairObserversFromTick",source)
        self.assertNotIn("function launchResultFromToolOutput",source)

if __name__ == '__main__': unittest.main()
