import json, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'scripts'

class RuntimeAndEvalTests(unittest.TestCase):
    def test_hot_metadata_has_no_worker_model_or_driver_default(self):
        text=(ROOT/'SKILL.md').read_text()
        self.assertNotIn('default-grunt-model',text)
        self.assertNotIn('default-worker-harness',text)
        self.assertNotIn('deepseek-v4',text.lower())
        self.assertIn('ask the user **once**',text)
        self.assertIn('MISSING_RUNTIME_CONFIG',text)

    def test_cli_init_has_no_model_defaults(self):
        help_text=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run','--help'],text=True,stdout=subprocess.PIPE,check=True).stdout
        self.assertIn('--grunt-driver',help_text); self.assertIn('--grunt-model',help_text); self.assertIn('--analyst-driver',help_text); self.assertIn('--analyst-model',help_text)
        src=(SCRIPTS/'dsd_task.py').read_text()
        self.assertNotIn('default="opencode-go/',src)
        self.assertNotIn('opencode-go/deepseek',src)

    def test_parent_control_help_exposes_role_asymmetries_before_authoring(self):
        direct=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'register-direct','--help'],text=True,stdout=subprocess.PIPE,check=True).stdout
        analysis=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'analysis-result','--help'],text=True,stdout=subprocess.PIPE,check=True).stdout
        self.assertIn('Verification and inferred implementation must come from an approved Analyst graph',' '.join(direct.split()))
        self.assertIn('Review follow-up triage',' '.join(analysis.split()))



    def test_parent_help_keeps_internal_semantic_transitions_behind_advance(self):
        help_text=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'--help'],text=True,stdout=subprocess.PIPE,check=True).stdout
        self.assertIn('advance',help_text); self.assertIn('owner-status',help_text)
        self.assertNotIn('verification-result',help_text); self.assertNotIn('phase-gate',help_text); self.assertNotIn('capability-escalate',help_text); self.assertNotIn('prepare-phase-gate',help_text)

    def test_opencode_harness_detection_never_claims_live_plugin_capability(self):
        sys.path.insert(0,str(SCRIPTS))
        import detect_harness
        caps=detect_harness.capabilities('opencode')
        self.assertEqual(caps['required_live_tool'],'tbag_follow')
        self.assertFalse(caps['live_capability_verified'])
        self.assertEqual(caps['compaction_resume'],'requires-live-project-plugin')
        self.assertEqual(caps['autonomous_supervision'],'requires-live-tbag_follow')

    def test_behavioral_eval_corpus_is_valid_and_covers_core_failures(self):
        cp=subprocess.run([sys.executable,str(SCRIPTS/'check_behavioral_evals.py')],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        out=json.loads(cp.stdout); self.assertGreaterEqual(out['cases'],10)
        cases=[json.loads(x) for x in (ROOT/'evals'/'cases.jsonl').read_text().splitlines() if x.strip()]
        ids={x['id'] for x in cases}
        self.assertTrue({'runtime-partial','major-vague-work','technical-llm-failure','parallel-ready','review-fix-loop','quiet-user-reporting','owner-requested-status-report','semantic-abstention-after-review','plan-owned-assurance','session-continuity','goal-only-bootstrap','midflight-attempt-observability','opencode-launch-follow-yield','deep-reviewer-system-interactions','deep-analyst-causal-system-reasoning','bounded-perfection-worker-quality','early-integration-feedback','semantic-runtime-adapters-are-optimizations','capability-ladder-stays-cold','long-attempt-diagnosis-before-retry','phase-exit-gate-is-product-goal-review','review-followup-obligation-cannot-evaporate','review-followup-invalidates-frozen-phase-frontier','staggered-worker-cli-starts-remain-parallel','opencode2-worker-isolation'}.issubset(ids))

    def test_hot_context_stays_compact(self):
        self.assertLessEqual((ROOT/'SKILL.md').stat().st_size,7500)

    def test_public_brand_is_tbag_and_vendor_neutral(self):
        skill=(ROOT/'SKILL.md').read_text(); readme=(ROOT/'README.md').read_text()
        self.assertIn('name: t-bag',skill)
        self.assertIn('workspace-root: TBag',skill)
        self.assertIn('# T-BAG — The Beauty And the Grunt',skill)
        self.assertIn('# T-BAG — The Beauty And the Grunt',readme)
        self.assertNotIn('Analyst & Grunt',skill)
        self.assertNotIn('Analyst & Grunt',readme)
        self.assertNotIn('DeepSeek and Destroy',skill)
        self.assertNotIn('DeepSeek and Destroy',readme)

    def test_runtime_config_is_cold_and_driver_model_are_separate(self):
        text=(ROOT/'CONFIG.md').read_text()
        self.assertIn('"driver": "opencode"',text)
        self.assertIn('"model":',text)
        self.assertIn('missing_runtime_config',text)
        self.assertIn('There is no hidden model/provider default',text)

    def test_runtime_effort_is_durable_for_defaults_and_cold_profiles(self):
        with tempfile.TemporaryDirectory() as td:
            project=Path(td)/'project'; project.mkdir(); subprocess.run(['git','init','-q',str(project)],check=True)
            run_root=project/'TBag'/'runs'/'r1'
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run','--project-root',str(project),'--run-root',str(run_root),'--run-id','r1'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr)
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime','--run-root',str(run_root),'--tier','analyst','--driver','claude','--model','opus','--effort','medium'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['runtime']['options'],{'effort':'medium'})
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime-profile','--run-root',str(run_root),'--tier','analyst','--name','deep','--driver','codex','--model','astra','--effort','high','--max-uses','1'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['profile']['options'],{'effort':'high'})
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime','--run-root',str(run_root),'--tier','grunt','--driver','opencode','--model','provider/model','--effort','high'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(cp.returncode,0); self.assertIn('no provider-independent effort flag',cp.stdout+cp.stderr)
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime','--run-root',str(run_root),'--tier','grunt','--driver','opencode2','--model','provider/model','--effort','high'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['runtime']['options'],{'effort':'high'})

    def test_codex_claude_and_opencode2_are_wired_drivers_but_unknown_cli_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); project=root/'project'; project.mkdir(); run_root=project/'TBag'/'runs'/'r1'
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run','--project-root',str(project),'--run-root',str(run_root),'--run-id','r1','--analyst-driver','codex','--analyst-model','gpt-test'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['worker_runtimes']['analyst']['driver'],'codex')
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime','--run-root',str(run_root),'--tier','grunt','--driver','claude','--model','claude-opus-5'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['runtime']['driver'],'claude')
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'set-runtime','--run-root',str(run_root),'--tier','grunt','--driver','opencode2','--model','opencode-go/muse'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['runtime']['driver'],'opencode2')

    def test_launch_start_interval_is_cold_run_configuration_with_safe_default(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); project=root/'project'; project.mkdir(); run_root=project/'TBag'/'runs'/'r1'
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run','--project-root',str(project),'--run-root',str(run_root),'--run-id','r1'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); data=json.loads(cp.stdout)
            self.assertEqual(data['launch_start_interval_seconds'],3.0)
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'runtime-status','--run-root',str(run_root)],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertEqual(cp.returncode,0,cp.stderr); self.assertEqual(json.loads(cp.stdout)['launch_start_interval_seconds'],3.0)
            bad=root/'bad'; bad.mkdir(); bad_run=bad/'TBag'/'runs'/'bad'
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run','--project-root',str(bad),'--run-root',str(bad_run),'--run-id','bad','--launch-start-interval-seconds','-1'],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(cp.returncode,0); self.assertIn('finite number >= 0',cp.stdout+cp.stderr)

    def test_init_rejects_unwired_driver_instead_of_persisting_false_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); project=root/'project'; project.mkdir()
            run_root=project/'TBag'/'runs'/'r1'
            cp=subprocess.run([sys.executable,str(SCRIPTS/'dsd_task.py'),'init-run',
                '--project-root',str(project),'--run-root',str(run_root),'--run-id','r1',
                '--analyst-driver','command-code','--analyst-model','some-model'],
                text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            self.assertNotEqual(cp.returncode,0)
            self.assertIn('not wired',cp.stderr)
            self.assertFalse((run_root/'run.json').exists())

if __name__=='__main__': unittest.main()
