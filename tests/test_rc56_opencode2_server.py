import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_harness_adapter as installer


class RC56OpenCode2ServerTests(unittest.TestCase):
    def test_major2_installs_native_setup_server_adapter(self):
        old = installer.detect_opencode_version
        try:
            installer.detect_opencode_version = lambda: ("2.0.0", 2)
            with tempfile.TemporaryDirectory() as td:
                project = Path(td) / "project"
                project.mkdir()
                result = installer.install_opencode(project, ROOT)
                installed = project / ".opencode" / "plugins" / "tbag.js"
                source = ROOT / "adapters" / "opencode" / "tbag-v2.js"
                self.assertEqual(installed.read_text(), source.read_text())
                text = installed.read_text()
                self.assertIn('id: "tbag.transport"', text)
                self.assertIn('async setup(ctx)', text)
                self.assertIn('ctx.tool.hook("execute.before"', text)
                self.assertIn('ctx.tool.hook("execute.after"', text)
                self.assertIn('ctx.event.subscribe', text)
                self.assertNotIn('@opencode-ai/plugin', text)
                self.assertEqual(result["transport_generation"], "v2")
                self.assertEqual(result["opencode_major"], 2)
                self.assertIsNone(result["live_probe_tool"])
                self.assertTrue(result["disk_matches_source"])
        finally:
            installer.detect_opencode_version = old

    def test_major1_keeps_legacy_server_adapter(self):
        old = installer.detect_opencode_version
        try:
            installer.detect_opencode_version = lambda: ("1.18.31", 1)
            with tempfile.TemporaryDirectory() as td:
                project = Path(td) / "project"
                project.mkdir()
                result = installer.install_opencode(project, ROOT)
                installed = project / ".opencode" / "plugins" / "tbag.js"
                source = ROOT / "adapters" / "opencode" / "tbag.js"
                self.assertEqual(installed.read_text(), source.read_text())
                self.assertEqual(result["transport_generation"], "v1")
                self.assertEqual(result["live_probe_tool"], "tbag_follow")
        finally:
            installer.detect_opencode_version = old


if __name__ == '__main__':
    unittest.main()
