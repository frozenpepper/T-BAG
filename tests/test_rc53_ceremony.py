import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'
sys.path.insert(0,str(SCRIPTS))
import dsd_task


class FollowupNullMarkerTests(unittest.TestCase):
    def parse(self, body):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'report.md'
            p.write_text('PASS\n\n## Follow-up obligations\n'+body+'\n')
            return dsd_task.review_followup_items(p)

    def test_none_with_explanatory_prose_is_not_an_obligation(self):
        self.assertEqual(self.parse('- None. Next step belongs to T23, not this review.'),[])
        self.assertEqual(self.parse('- None — T23 owns the next verification.'),[])

    def test_real_none_prefixed_sentence_remains_an_obligation(self):
        self.assertEqual(self.parse('- None of the migration docs cover the fallback.'),['None of the migration docs cover the fallback.'])


class AttemptRoleAuthorityTests(unittest.TestCase):
    def make_run(self, root, attempt_role):
        run=root/'run'
        taskroot=run/'phases'/'p'/'tasks'/'GATE'
        event=taskroot/'attempts'/f'{attempt_role}-1'
        event.mkdir(parents=True)
        report=event/'report.md'
        report.write_text('Findings only; no lifecycle transition is requested.\n')
        task={
            'format':dsd_task.FORMAT,'phase_id':'p','task_id':'GATE','kind':'analysis',
            'role':'phase-auditor','tier':'analyst','brief':str(taskroot/'brief.md'),
            'dependencies':[],'requires_integration':False,'status':'active',
            'attempts':[{'role':attempt_role,'tier':'analyst','status':'gated','event_dir':str(event)}],
            'review_rounds':0,'review_history':[],'created_at':dsd_task.now(),
        }
        (taskroot/'brief.md').write_text('# gate\n')
        dsd_task.write_json(taskroot/'task.json',task)
        return run,report,taskroot/'task.json'

    def test_discovery_under_phase_gate_closes_as_findings(self):
        with tempfile.TemporaryDirectory() as td:
            run,report,state=self.make_run(Path(td),'discovery')
            task=dsd_task.load_json(state)
            self.assertEqual(dsd_task._reconcile_action(run,'p',task)['action'],'accept-specialist-result')
            out=dsd_task.command_accept(SimpleNamespace(run_root=run,phase_id='p',task_id='GATE',report=report))
            self.assertEqual(out['status'],'accepted')
            self.assertEqual(dsd_task.load_json(state)['accepted_report'],str(report.resolve()))

    def test_actual_phase_auditor_attempt_still_requires_phase_gate(self):
        with tempfile.TemporaryDirectory() as td:
            run,report,_=self.make_run(Path(td),'phase-auditor')
            with self.assertRaisesRegex(ValueError,'Phase-Auditor results use phase-gate'):
                dsd_task.command_accept(SimpleNamespace(run_root=run,phase_id='p',task_id='GATE',report=report))


class AdvanceReducerTests(unittest.TestCase):
    def test_mechanical_action_runs_past_earlier_launch_boundary(self):
        run=Path('/tmp/rc53-run')
        launch={'action':'launch-ready-task','phase_id':'p','task_id':'A'}
        mechanical={'action':'prepare-followup-triage','phase_id':'p','task_id':'B'}
        states=[{'first_useful_actions':[launch,mechanical]},{'first_useful_actions':[launch]}]
        with mock.patch.object(dsd_task,'command_reconcile_run',side_effect=states), mock.patch.object(dsd_task,'command_prepare_followup_triage',return_value={'ok':True}) as triage:
            out=dsd_task.command_advance(SimpleNamespace(run_root=run,phase_id=None,max_steps=12))
        triage.assert_called_once()
        self.assertEqual(out['stopped'],'semantic-or-launch-boundary')
        self.assertEqual(out['next_action']['task_id'],'A')
        self.assertEqual(out['applied'][0]['task_id'],'B')

    def test_accept_specialist_result_is_mechanical(self):
        run=Path('/tmp/rc53-run')
        action={'action':'accept-specialist-result','phase_id':'p','task_id':'G','report':'/tmp/report.md'}
        states=[{'first_useful_actions':[action]},{'first_useful_actions':[]}]
        with mock.patch.object(dsd_task,'command_reconcile_run',side_effect=states), mock.patch.object(dsd_task,'command_accept',return_value={'status':'accepted'}) as accept:
            out=dsd_task.command_advance(SimpleNamespace(run_root=run,phase_id=None,max_steps=12))
        accept.assert_called_once()
        self.assertEqual(out['stopped'],'quiescent')
        self.assertEqual(out['applied'][0]['action'],'accept-specialist-result')


class TransportFallbackDocsTests(unittest.TestCase):
    def test_missing_follow_is_documented_as_degraded_transport(self):
        text=(ROOT/'OPENCODE.md').read_text()
        self.assertIn('wake transport is degraded, not lifecycle correctness',text)
        self.assertIn('next owner turn/manual tick',text)


if __name__=='__main__': unittest.main()
