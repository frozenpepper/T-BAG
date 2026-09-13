import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_harness_adapter
import tbag_render


def sample_snapshot():
    analyst = {
        "phase_id": "D",
        "task_id": "D20",
        "objective": "Diagnose provider retry seam without changing production code",
        "authority": "Analyst",
        "tier": "analyst",
        "role": "recovery",
        "model": "deepseek-v4.1-flash",
        "elapsed_seconds": 434,
        "session": {"id": "ses-analyst-123456", "known": True, "abandoned": False},
        "observer": {"known": True, "healthy": True},
        "process": {"worker": {"alive": True, "cpu_percent": 2.4, "cpu_seconds": 81}},
        "log_age_seconds": 4,
        "report_age_seconds": 12,
    }
    grunt = {
        "phase_id": "D",
        "task_id": "D18",
        "objective": "Implement reducer lifecycle repair",
        "authority": "Grunt",
        "tier": "grunt",
        "role": "implementer",
        "model": "muse-spark-1.3-contributor",
        "elapsed_seconds": 703,
        "session": {"id": "ses-grunt-987654", "known": True, "abandoned": False},
        "observer": {"known": False, "healthy": False},
        "process": {"worker": {"alive": True, "cpu_percent": 1.1, "cpu_seconds": 54}},
        "log_age_seconds": 9,
        "report_age_seconds": 9,
    }
    return {
        "format": "tbag-status-v1",
        "run": {"id": "SQR8V2", "status": "active", "parent_loop": "workers-live"},
        "progress": {"registered_done": 36, "registered_total": 50, "registered_percent": 72.0, "phases_done": 3, "phases_total": 5},
        "current_phase": {"phase_id": "D", "percent": 88.0, "gate": None, "complete": False},
        "phases": [
            {"phase_id": "A", "percent": 100.0, "complete": True, "gate": {"result": "PASS"}},
            {"phase_id": "D", "percent": 88.0, "complete": False, "gate": None},
        ],
        "workers": [analyst, grunt],
        "analysts_active": [analyst],
        "grunts_active": [grunt],
        "worker_budget": {"max": 4, "live": 2, "free": 2},
        "attention": [{"phase_id": "D", "task_id": "D21", "status": "observer-missing", "objective": "Run native store proof"}],
        "recent": [],
    }


class RendererTests(unittest.TestCase):
    def test_claude_surface_prioritizes_analyst_purpose_and_session(self):
        lines = tbag_render.claude_status_lines(
            sample_snapshot(), host={"model": "Opus 5", "context_percent": 41}, width=220, color=False
        )
        text = "\n".join(lines)
        self.assertIn("T-BAG", text)
        self.assertIn("phase D", text)
        self.assertIn("72%", text)
        self.assertIn("A1 G1", text)
        self.assertIn("Analysts:", text)
        self.assertIn("D20 recovery", text)
        self.assertIn("Diagnose provider retry seam", text)
        self.assertIn("deepseek-v4.1", text)
        self.assertIn("ses-analys", text)
        self.assertIn("Grunts:", text)
        self.assertIn("D18 implementer", text)
        self.assertIn("Opus 5 ctx 41%", text)

    def test_terminal_detail_exposes_process_observer_and_attention(self):
        text = "\n".join(tbag_render.detail_lines(sample_snapshot(), width=220, color=False))
        self.assertIn("ACTIVE ANALYSTS (1)", text)
        self.assertIn("CPU 2.4%", text)
        self.assertIn("observer healthy", text)
        self.assertIn("ACTIVE GRUNTS (1)", text)
        self.assertIn("observer missing", text)
        self.assertIn("ATTENTION (1)", text)
        self.assertIn("PHASES", text)

    def test_claude_payload_uses_native_session_context_without_mutating_state(self):
        payload = {
            "session_id": "claude-parent-1",
            "workspace": {"project_dir": "/tmp/project"},
            "model": {"display_name": "Opus 5"},
            "context_window": {"used_percentage": 37},
        }
        with mock.patch.object(tbag_render.tbag_status, "build_snapshot", return_value=sample_snapshot()) as build:
            lines = tbag_render.render_claude_payload(payload, width=180, color=False)
        build.assert_called_once_with(Path("/tmp/project"), parent_session_id="claude-parent-1")
        self.assertIn("Opus 5 ctx 37%", lines[0])

    def test_claude_payload_degrades_cleanly_without_a_run(self):
        with mock.patch.object(tbag_render.tbag_status, "build_snapshot", side_effect=ValueError("no run")):
            lines = tbag_render.render_claude_payload({"cwd": "/tmp", "model": {"display_name": "Sonnet"}}, width=100, color=False)
        self.assertEqual(lines, ["T-BAG ○ no active run · Sonnet"])


class InstallerTests(unittest.TestCase):
    def test_claude_installs_native_refreshing_status_line_when_free(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            result = install_harness_adapter.install_claude(project, ROOT)
            settings = json.loads((project / ".claude" / "settings.json").read_text())
            status = settings["statusLine"]
            self.assertEqual(status["type"], "command")
            self.assertEqual(status["refreshInterval"], 5)
            self.assertIn("TBag/tools/tbag_render.py", status["command"])
            self.assertTrue(result["status_line_installed"])
            self.assertFalse(result["status_line_conflict"])

    def test_claude_preserves_an_existing_non_tbag_status_line(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            settings = project / ".claude" / "settings.json"
            settings.parent.mkdir(parents=True)
            custom = {"type": "command", "command": "~/my-status.sh", "refreshInterval": 1}
            settings.write_text(json.dumps({"statusLine": custom}) + "\n")
            result = install_harness_adapter.install_claude(project, ROOT)
            after = json.loads(settings.read_text())
            self.assertEqual(after["statusLine"], custom)
            self.assertTrue(result["status_line_conflict"])
            self.assertEqual(result["status_surface"], "custom-status-line-preserved")

    def test_codex_installer_exposes_read_only_status_and_watch_commands(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            result = install_harness_adapter.install_codex(project, ROOT)
            self.assertEqual(result["status_surface"], "companion-terminal")
            self.assertIn("tbag_render.py", result["status_command"])
            self.assertIn(" status ", result["status_command"])
            self.assertIn(" watch ", result["watch_command"])
            self.assertTrue((project / ".codex" / "hooks.json").is_file())

    def test_helper_install_exposes_shared_renderer_shim(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            helpers = install_harness_adapter.install_helper(ROOT, project)
            renderer = helpers["tbag_render"]
            self.assertTrue(renderer.is_file())
            self.assertIn("tbag_render.py", renderer.read_text())


if __name__ == "__main__":
    unittest.main()
