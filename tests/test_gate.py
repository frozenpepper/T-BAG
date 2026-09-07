import json, sys, tempfile, unittest
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/"scripts";sys.path.insert(0,str(SCRIPTS))
import evidence_gate
from run_worker import PLACEHOLDER, placeholder_text

class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.event=self.root/"event";self.event.mkdir();self.task=self.root/"task.md";self.task.write_text("# T\n")
        self.baseline=self.root/"baseline.json";self.baseline.write_text("{}")
        self.report=self.event/"report.md";self.scope=self.event/"scope.json"
    def tearDown(self):self.tmp.cleanup()
    def make(self,role="reviewer",writes=False,changed=None,report="ok\n",exit_code=0):
        changed=changed or []
        reservation={"task_id":"T","role":role,"tier":"grunt","model":"m","attempt":1,"writes_project":writes,"task_contract":str(self.task),"scope_baseline":str(self.baseline),"report":str(self.report)}
        (self.event/"launch-reservation.json").write_text(json.dumps(reservation));self.report.write_text(report)
        self.scope.write_text(json.dumps({"changed_since_attempt_baseline":changed,"changed_count":len(changed)}))
        terminal={"task_id":"T","role":role,"tier":reservation["tier"],"model":"m","attempt":1,"exit_code":exit_code,"scope_diff":str(self.scope),"session_id":"s"}
        (self.event/"terminal.json").write_text(json.dumps(terminal))
        return evidence_gate.gate(self.event)
    def test_report_semantics_are_not_parsed(self):
        g=self.make(report="VERDICT: FAIL\nThis is semantically bad but mechanically present.\n")
        self.assertTrue(g["ready_for_interpretation"])
    def test_completed_report_may_mention_placeholder_token_in_prose(self):
        g=self.make(report="PASS\nThe launcher marker DSD_WORKER_REPORT_PLACEHOLDER_V2_1 was removed before final handoff.\n")
        self.assertEqual(g["report_state"],"present")
        self.assertTrue(g["ready_for_interpretation"])

    def test_readonly_mutation_fails(self):
        g=self.make(changed=["a.txt"]);self.assertFalse(g["integrity_ok"])
    def test_control_tree_mutation_fails_even_for_writer(self):
        g=self.make(role="implementer",writes=True,changed=["TBag/foo"]);self.assertFalse(g["integrity_ok"])
    def test_reportless_no_change_is_same_role_retry_not_analyst_or_log_reading(self):
        g=self.make(report=PLACEHOLDER); self.assertEqual(g["disposition"],"report-resume"); self.assertTrue(g["integrity_ok"]); self.assertFalse(g["ready_for_interpretation"])
    def test_reportless_admissible_mutation_is_same_role_continuation_not_analyst_tax(self):
        g=self.make(role="implementer",writes=True,changed=["a.txt"],report=PLACEHOLDER)
        self.assertEqual(g["disposition"],"mutating-report-resume"); self.assertTrue(g["integrity_ok"]); self.assertFalse(g["ready_for_interpretation"])
    def test_in_progress_report_after_mutation_prefers_same_session_resume(self):
        report=placeholder_text(self.event)+"\n- About to update a.txt through the established owner.\n"
        g=self.make(role="implementer",writes=True,changed=["a.txt"],report=report)
        self.assertEqual(g["report_state"],"in-progress")
        self.assertEqual(g["disposition"],"mutating-report-resume")
        self.assertTrue(g["integrity_ok"]); self.assertFalse(g["ready_for_interpretation"])
    def test_in_progress_report_never_overrides_scope_violation(self):
        self.task.write_text("# T\n## Allowed source changes\n- `src/allowed`\n")
        report=placeholder_text(self.event)+"\n- Working on the requested change.\n"
        g=self.make(role="implementer",writes=True,changed=["src/outside.py"],report=report)
        self.assertEqual(g["report_state"],"in-progress")
        self.assertEqual(g["disposition"],"integrity-failed")
        self.assertFalse(g["integrity_ok"]); self.assertFalse(g["ready_for_interpretation"])

    def test_placeholder_never_masks_readonly_mutation(self):
        g=self.make(role="reviewer",writes=False,changed=["a.txt"],report=PLACEHOLDER)
        self.assertEqual(g["disposition"],"integrity-failed")
        self.assertFalse(g["integrity_ok"])

    def test_exit_zero_is_only_exposed_as_fact(self):
        g=self.make(exit_code=0);self.assertEqual(g["exit_code"],0);self.assertNotIn("semantic",json.dumps(g).lower())
    def test_explicit_write_boundary_is_enforced(self):
        self.task.write_text("# T\n## Allowed source changes\n- `src/allowed`\n")
        g=self.make(role="implementer",writes=True,changed=["src/other/file.py"]);self.assertFalse(g["integrity_ok"])

    def test_directory_tree_spelling_is_canonical_prefix_not_literal_glob(self):
        self.task.write_text("# T\n## Allowed source changes\n- `src/allowed/**`\n")
        inside=self.make(role="implementer",writes=True,changed=["src/allowed/deep/file.py"])
        self.assertTrue(inside["integrity_ok"],inside["errors"])
        outside=self.make(role="implementer",writes=True,changed=["src/other/file.py"])
        self.assertFalse(outside["integrity_ok"])

    def test_decorated_allowlist_bullets_fail_instead_of_becoming_literal_prefixes(self):
        from _contract import allowed_source_changes
        bad = [
            "# T\n## Allowed source changes\n- DELETE `src/a.py`\n",
            "# T\n## Allowed source changes\n- REGENERATE via the generator chain:\n",
            "# T\n## Allowed source changes\n- Nothing else may change.\n",
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError,"exactly one path"):
                    allowed_source_changes(text)

    def test_whole_backtick_wrapped_path_may_contain_spaces(self):
        from _contract import allowed_source_changes
        self.assertEqual(allowed_source_changes("# T\n## Allowed source changes\n- `docs/My File.md`\n"), ["docs/My File.md"])

if __name__=="__main__":unittest.main()
