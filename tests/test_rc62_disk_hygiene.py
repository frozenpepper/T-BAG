import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
sys.path.insert(0,str(SCRIPTS))

import dsd_task
import dsd_workspace
import parent_tick
import run_worker


class RC62DiskHygieneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.project=self.root/"project"; self.project.mkdir()
        self.run=self.project/"TBag"/"runs"/"R"; self.run.mkdir(parents=True)
        self.runtime=self.project/"TBag"/"runtime"/"R"
        (self.run/"run.json").write_text(json.dumps({
            "format":dsd_task.RUN_FORMAT,
            "run_id":"R",
            "project_root":str(self.project),
            "runtime_root":str(self.runtime),
            "status":"active",
            "max_workers":2,
        }))
    def tearDown(self):
        self.tmp.cleanup()

    def test_worker_environment_uses_project_shared_caches_and_attempt_tmp(self):
        event=self.run/"phases"/"P"/"tasks"/"T"/"attempts"/"implementer-1"
        env,caches=run_worker.worker_environment({},{"run_root":self.run,"event_dir":event})
        self.assertEqual(caches["root"],self.project/"TBag"/"cache")
        self.assertEqual(Path(env["npm_config_cache"]),self.project/"TBag"/"cache"/"npm-cache")
        self.assertEqual(env["npm_config_prefer_offline"],"true")
        self.assertEqual(Path(env["NODE_COMPILE_CACHE"]),self.project/"TBag"/"cache"/"node-compile-cache")
        self.assertEqual(Path(env["TMPDIR"]),event/"scratch")
        self.assertNotIn(str(event/"scratch"),env["npm_config_cache"])

    def test_codex_sandbox_is_granted_launcher_shared_cache(self):
        event=self.run/"attempt"; event.mkdir(parents=True)
        prompt=event/"prompt.txt"; prompt.write_text("work")
        task=event/"task.md"; task.write_text("# read only\n")
        cache=self.project/"TBag"/"cache"/"npm-cache"; cache.mkdir(parents=True)
        args=SimpleNamespace(driver="codex",task_id="T",role="discovery",attempt=1,model="gpt-test",title=None,force_read_only=True,resume_session=None,auto_flag=None,effort=None)
        p={"prompt":prompt,"task":task,"event_dir":event,"project_root":self.project}
        with patch.object(run_worker.shutil,"which",side_effect=lambda name: "/usr/bin/codex" if name=="codex" else None):
            cmd,_,_,_=run_worker.worker_command(args,p,{"npm_config_cache":str(cache)})
        self.assertIn("--add-dir",cmd)
        self.assertIn(str(cache.parent),cmd)

    def test_terminal_attempt_scratch_is_removed_but_evidence_survives(self):
        task_root=self.run/"phases"/"P"/"tasks"/"T"; task_root.mkdir(parents=True)
        event=task_root/"attempts"/"implementer-1"; scratch=event/"scratch"; scratch.mkdir(parents=True)
        (scratch/"npm-cache.bin").write_bytes(b"x"*1024)
        (event/"terminal.json").write_text('{"status":"process-exited","exit_code":0}\n')
        (event/"worker.log").write_text("worker evidence\n")
        (event/"report.md").write_text("report evidence\n")
        (task_root/"task.json").write_text(json.dumps({
            "task_id":"T","status":"active",
            "attempts":[{"status":"started","event_dir":str(event)}],
        }))
        out=dsd_task.reap_attempt_scratch(self.run)
        self.assertEqual(out["count"],1)
        self.assertGreaterEqual(out["reclaimed_bytes"],1024)
        self.assertFalse(scratch.exists())
        self.assertTrue((event/"worker.log").is_file())
        self.assertTrue((event/"report.md").is_file())
        self.assertTrue((event/"terminal.json").is_file())

    def test_archive_run_drops_launcher_logs_and_scratch_but_keeps_report(self):
        info=json.loads((self.run/"run.json").read_text()); info["status"]="abandoned"
        (self.run/"run.json").write_text(json.dumps(info))
        task_root=self.run/"phases"/"P"/"tasks"/"T"; task_root.mkdir(parents=True)
        event=task_root/"attempts"/"implementer-1"; scratch=event/"scratch"; scratch.mkdir(parents=True)
        (scratch/"tmp.bin").write_bytes(b"x"*2048)
        (event/"terminal.json").write_text('{"status":"process-exited","exit_code":0}\n')
        (event/"worker.log").write_text("large launcher log\n")
        (event/"worker.stderr.log").write_text("stderr\n")
        (event/"report.md").write_text("durable report\n")
        (task_root/"brief.md").write_text("# brief\n")
        (task_root/"task.json").write_text(json.dumps({
            "task_id":"T","status":"active",
            "attempts":[{"status":"started","event_dir":str(event)}],
        }))
        out=dsd_workspace.command_archive_run(SimpleNamespace(run_root=self.run,dry_run=False))
        self.assertEqual(out["format"],"tbag-run-archive-v1")
        self.assertFalse((event/"worker.log").exists())
        self.assertFalse((event/"worker.stderr.log").exists())
        self.assertFalse(scratch.exists())
        self.assertTrue((event/"report.md").is_file())
        self.assertTrue((task_root/"brief.md").is_file())
        self.assertTrue((self.run/"archive.json").is_file())

    def test_parent_disk_sampling_is_throttled_and_reports_delta(self):
        loop={}
        first={"sampled_at":parent_tick.now(),"owned_total_bytes":100,"run_bytes":40,"runtime_bytes":50,"project_shared_cache_bytes":10}
        with patch.object(dsd_workspace,"disk_usage_snapshot",return_value=first) as sample:
            out1=parent_tick.disk_usage_for_tick(self.run,loop,sample_seconds=300)
            out2=parent_tick.disk_usage_for_tick(self.run,loop,sample_seconds=300)
        self.assertFalse(out1["cached"])
        self.assertTrue(out2["cached"])
        self.assertEqual(sample.call_count,1)
        loop["disk_usage_sample"]={**first,"sampled_at":"2000-01-01T00:00:00+00:00","owned_total_bytes":80}
        second={"sampled_at":parent_tick.now(),"owned_total_bytes":120,"run_bytes":50,"runtime_bytes":50,"project_shared_cache_bytes":20}
        with patch.object(dsd_workspace,"disk_usage_snapshot",return_value=second):
            out3=parent_tick.disk_usage_for_tick(self.run,loop,sample_seconds=1)
        self.assertEqual(out3["delta_since_previous_sample_bytes"],40)


if __name__=="__main__":
    unittest.main()
