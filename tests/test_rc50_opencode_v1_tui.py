import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_harness_adapter
import opencode_tui_compat


class OpenCodeTuiCompatTests(unittest.TestCase):
    def test_version_parser_handles_v1_and_v2_output(self):
        with mock.patch.object(opencode_tui_compat.subprocess, "check_output", return_value="opencode 1.18.30\n"):
            self.assertEqual(opencode_tui_compat.detect_opencode_version(), ("1.18.30", 1))
        with mock.patch.object(opencode_tui_compat.subprocess, "check_output", return_value="v2.0.4\n"):
            self.assertEqual(opencode_tui_compat.detect_opencode_version(), ("2.0.4", 2))

    def test_jsonc_registration_is_targeted_idempotent_and_comment_preserving(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            config = project / ".opencode" / "tui.jsonc"
            config.parent.mkdir(parents=True)
            config.write_text(
                '{\n'
                '  // owner theme stays\n'
                '  "theme": "opencode",\n'
                '  "plugin": [\n'
                '    ["./plugins/owner.tsx", {"x": 1}], // owner plugin\n'
                '  ],\n'
                '}\n'
            )
            changed, path = opencode_tui_compat.ensure_tui_plugin(project)
            self.assertTrue(changed)
            self.assertEqual(path, config)
            text = config.read_text()
            self.assertIn("// owner theme stays", text)
            self.assertIn("// owner plugin", text)
            self.assertIn(opencode_tui_compat.V1_SPEC, text)
            changed_again, _ = opencode_tui_compat.ensure_tui_plugin(project)
            self.assertFalse(changed_again)
            self.assertEqual(config.read_text().count(opencode_tui_compat.V1_SPEC), 1)

    def test_jsonc_registration_adds_missing_plugin_key_without_overwriting_owner_text(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            config = project / ".opencode" / "tui.jsonc"
            config.parent.mkdir(parents=True)
            config.write_text('{\n  "theme": "opencode" // keep me\n}\n')
            changed, _ = opencode_tui_compat.ensure_tui_plugin(project)
            self.assertTrue(changed)
            text = config.read_text()
            self.assertIn("// keep me", text)
            self.assertIn(opencode_tui_compat.V1_SPEC, text)

    def test_removal_targets_only_tbag_v1_entry(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            config = project / ".opencode" / "tui.jsonc"
            config.parent.mkdir(parents=True)
            config.write_text(
                '{\n'
                '  // preserve\n'
                '  "plugin": [\n'
                '    ["./plugins/owner.tsx", {}],\n'
                f'    ["{opencode_tui_compat.V1_SPEC}", {{}}], // tbag row\n'
                '  ],\n'
                '  "theme": "opencode"\n'
                '}\n'
            )
            changed, _ = opencode_tui_compat.remove_tui_plugin(project)
            self.assertTrue(changed)
            text = config.read_text()
            self.assertIn("// preserve", text)
            self.assertIn("./plugins/owner.tsx", text)
            self.assertNotIn(opencode_tui_compat.V1_SPEC, text)
            self.assertIn('"theme": "opencode"', text)


class OpenCodeInstallerVersionTests(unittest.TestCase):
    def test_v1_installs_explicit_registered_companion_without_package_edits(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            install_harness_adapter, "detect_opencode_version", return_value=("1.18.30", 1)
        ):
            project = Path(td)
            result = install_harness_adapter.install_opencode(project, ROOT)
            companion = project / ".opencode" / "plugins" / "tbag-status-tui-v1.tsx"
            self.assertTrue(companion.is_file())
            self.assertFalse((project / ".opencode" / "plugins" / "tbag-ui").exists())
            config = json.loads((project / ".opencode" / "tui.json").read_text())
            self.assertIn([opencode_tui_compat.V1_SPEC, {}], config["plugin"])
            self.assertEqual(result["opencode_major"], 1)
            self.assertEqual(result["tui_generation"], "v1")
            self.assertEqual(result["status_surface"], "tui-v1-sidebar-route")
            self.assertFalse(result["live_capability_verified"])
            self.assertFalse((project / ".opencode" / "package.json").exists())

    def test_v2_installs_existing_companion_and_removes_stale_v1_registration(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            opencode_tui_compat.ensure_tui_plugin(project)
            stale = project / ".opencode" / "plugins" / "tbag-status-tui-v1.tsx"
            stale.parent.mkdir(parents=True, exist_ok=True)
            stale.write_text("stale")
            with mock.patch.object(install_harness_adapter, "detect_opencode_version", return_value=("2.0.1", 2)):
                result = install_harness_adapter.install_opencode(project, ROOT)
            self.assertTrue((project / ".opencode" / "plugins" / "tbag-ui" / "tui.tsx").is_file())
            self.assertFalse(stale.exists())
            self.assertNotIn(opencode_tui_compat.V1_SPEC, (project / ".opencode" / "tui.json").read_text())
            self.assertEqual(result["tui_generation"], "v2")
            self.assertTrue(result["stale_v1_companion_removed"])

    def test_unknown_host_keeps_transport_but_does_not_guess_tui_generation(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(
            install_harness_adapter, "detect_opencode_version", return_value=(None, None)
        ):
            project = Path(td)
            result = install_harness_adapter.install_opencode(project, ROOT)
            self.assertTrue((project / ".opencode" / "plugins" / "tbag.js").is_file())
            self.assertEqual(result["tui_generation"], "unknown")
            self.assertEqual(result["status_surface"], "transport-only-host-version-unknown")
            self.assertEqual(result["tui_plugin"], [])

    def test_v1_companion_uses_documented_v1_surface(self):
        text = (ROOT / "adapters" / "opencode" / "tbag-status-tui-v1.tsx").read_text()
        self.assertIn('/** @jsxImportSource @opentui/solid */', text)
        self.assertIn('@opencode-ai/plugin/tui', text)
        self.assertNotIn('@opencode/plugin/tui', text)
        self.assertIn('name: "sidebar_content"', text)
        self.assertIn('slashName: "tbag"', text)
        self.assertIn('api.route.register', text)
        self.assertIn('api.lifecycle.onDispose', text)
        self.assertIn('id: "tbag.status.v1"', text)


if __name__ == "__main__":
    unittest.main()
