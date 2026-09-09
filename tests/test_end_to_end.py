import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def run(cmd, *, cwd=None, env=None, ok=(0,)):
    cp = subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if cp.returncode not in ok:
        raise AssertionError(f"command failed {cp.returncode}: {' '.join(map(str, cmd))}\nSTDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}")
    return cp


def git(cwd, *args):
    return run(["git", *args], cwd=cwd).stdout.strip()


class EndToEndTests(unittest.TestCase):
    def test_detached_implement_review_accept_integrate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            project = root / "project"
            project.mkdir()
            git(project, "init", "-q")
            git(project, "config", "user.email", "t@example.com")
            git(project, "config", "user.name", "T")
            (project / "a.txt").write_text("before\n")
            (project / "PLAN.md").write_text("# Plan\n")
            git(project, "add", ".")
            git(project, "commit", "-qm", "init")

            run_root = project / "TBag" / "runs" / "r1"
            runtime = root / "runtime"
            run([
                sys.executable, str(SCRIPTS / "dsd_task.py"), "init-run",
                "--project-root", str(project.resolve()), "--run-root", str(run_root.resolve()),
                "--run-id", "r1", "--runtime-root", str(runtime.resolve()),
                "--grunt-driver", "opencode", "--grunt-model", "fake-grunt",
                "--analyst-driver", "opencode", "--analyst-model", "fake-analyst",
            ])
            run([
                sys.executable, str(SCRIPTS / "prepare_worker_rules.py"),
                "--project-root", str(project.resolve()), "--run-root", str(run_root.resolve()),
                "--plan", str((project / "PLAN.md").resolve()), "--revision", "1",
            ])
            planner_brief = root / "planner.md"
            planner_brief.write_text("# Plan T1\n")
            run([
                sys.executable, str(SCRIPTS / "dsd_task.py"), "register-direct",
                "--run-root", str(run_root.resolve()), "--phase-id", "P", "--task-id", "PLAN-T1",
                "--brief", str(planner_brief.resolve()), "--kind", "analysis", "--role", "planner", "--tier", "analyst", "--no-integration",
            ])
            plan_event = run_root / "phases" / "P" / "tasks" / "PLAN-T1" / "attempts" / "planner-1"
            plan_tasks = plan_event / "plan" / "tasks"; plan_tasks.mkdir(parents=True)
            plan_report = plan_event / "report.md"; plan_report.write_text("Analyst produced T1.\n")
            task_brief = plan_tasks / "T1.md"; task_brief.write_text("# Task T1\n\nChange a.txt from before to after through the assigned task worktree.\n")
            graph = plan_event / "plan" / "task-graph.json"
            graph.write_text(json.dumps({"format":"dsd-task-plan-v2.1","tasks":[{"task_id":"T1","kind":"implementation","role":"implementer","tier":"grunt","brief":"tasks/T1.md","dependencies":[],"requires_integration":True}]}))
            planner_state_path = run_root / "phases" / "P" / "tasks" / "PLAN-T1" / "task.json"
            planner_state = json.loads(planner_state_path.read_text()); planner_state["attempts"].append({"task_id":"PLAN-T1","role":"planner","tier":"analyst","status":"gated","event_dir":str(plan_event)}); planner_state["status"]="active"; planner_state_path.write_text(json.dumps(planner_state,indent=2,sort_keys=True)+"\n")
            run([sys.executable,str(SCRIPTS/"dsd_task.py"),"accept","--run-root",str(run_root.resolve()),"--phase-id","P","--task-id","PLAN-T1","--report",str(plan_report.resolve())])
            run([sys.executable,str(SCRIPTS/"dsd_task.py"),"register-plan","--run-root",str(run_root.resolve()),"--phase-id","P","--plan",str(graph.resolve())])

            fakebin = root / "bin"
            fakebin.mkdir()
            fake = fakebin / "opencode"
            fake.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys
args=sys.argv[1:]
if args[:2] == ["session", "list"]:
    print("[]")
    raise SystemExit(0)
if not args or args[0] != "run":
    raise SystemExit(2)
prompt=args[-1]
report=None
for line in prompt.splitlines():
    if line.startswith("Report: "):
        report=pathlib.Path(line[len("Report: "):].strip())
        break
if report is None:
    raise SystemExit(3)
report.parent.mkdir(parents=True, exist_ok=True)
if prompt.startswith("T-BAG IMPLEMENTER"):
    pathlib.Path("a.txt").write_text("after\n")
    report.write_text("Implemented the bounded task in a.txt and verified the resulting file content.\n")
elif prompt.startswith("T-BAG REVIEWER"):
    if pathlib.Path("a.txt").read_text() != "after\n":
        report.write_text("Review found the implementation missing.\n")
        raise SystemExit(4)
    report.write_text("Adversarial review: task behavior is present through the assigned worktree; no task-relevant defect found.\n")
else:
    report.write_text("Completed assigned role.\n")
raise SystemExit(0)
''')
            fake.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(fakebin) + os.pathsep + env.get("PATH", "")

            def launch(role, tier):
                cp = run([
                    sys.executable, str(SCRIPTS / "dsd_attempt.py"), "launch",
                    "--run-root", str(run_root.resolve()), "--phase-id", "P", "--task-id", "T1",
                    "--role", role, "--tier", tier,
                ], env=env)
                data = json.loads(cp.stdout)
                self.assertEqual(data["run_root"], str(run_root.resolve()))
                self.assertEqual(data["phase_id"], "P"); self.assertEqual(data["task_id"], "T1")
                event = Path(data["event_dir"])
                deadline = time.time() + 15
                while time.time() < deadline and not (event / "terminal.json").is_file():
                    time.sleep(0.05)
                self.assertTrue((event / "terminal.json").is_file(), f"terminal did not appear for {role}")
                gate = run([
                    sys.executable, str(SCRIPTS / "dsd_attempt.py"), "gate",
                    "--run-root", str(run_root.resolve()), "--phase-id", "P", "--task-id", "T1",
                    "--event-dir", str(event),
                ], env=env)
                g = json.loads(gate.stdout)
                self.assertTrue(g["ready_for_interpretation"], g)
                self.assertTrue(g.get("report_surface"), g)
                return event, g

            implement_event, _implement_gate = launch("implementer", "grunt")
            task = json.loads((run_root / "phases" / "P" / "tasks" / "T1" / "task.json").read_text())
            self.assertEqual(task["status"], "awaiting-review")
            workspace_before = json.loads((run_root / "phases" / "P" / "tasks" / "T1" / "workspace.json").read_text())
            worktree = Path(workspace_before["worktree"]); db = Path(workspace_before["db"])
            self.assertEqual((worktree / "a.txt").read_text(), "after\n")
            self.assertEqual((project / "a.txt").read_text(), "before\n")

            review_event, review_gate = launch("reviewer", "grunt")
            review_report = review_event / "report.md"
            self.assertTrue(review_gate.get("report_surface"))
            run([
                sys.executable, str(SCRIPTS / "dsd_workspace.py"), "integrate",
                "--run-root", str(run_root.resolve()), "--phase-id", "P", "--task-id", "T1",
                "--review-pass-report", str(review_report.resolve()),
            ])
            self.assertEqual((project / "a.txt").read_text(), "after\n")
            final_task = json.loads((run_root / "phases" / "P" / "tasks" / "T1" / "task.json").read_text())
            self.assertEqual(final_task["status"], "integrated")
            self.assertTrue((implement_event / "report.md").is_file())
            self.assertFalse((run_root / "phases" / "P" / "tasks" / "T1" / "workspace.json").exists())
            self.assertEqual(final_task.get("workspace_cleanup_reason"),"reviewed-delta-integrated")
            self.assertFalse(worktree.exists())
            self.assertFalse(db.exists())
            self.assertFalse(Path(str(db) + "-wal").exists())
            self.assertFalse(Path(str(db) + "-shm").exists())


if __name__ == "__main__":
    unittest.main()
