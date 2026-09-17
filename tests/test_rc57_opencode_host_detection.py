import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import install_harness_adapter as installer
import opencode_tui_compat as compat


class RC57OpenCodeHostDetectionTests(unittest.TestCase):
    def _fake_v2_host(self, calls):
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv[:2] == ["ps", "-p"]:
                return "/usr/local/lib/node_modules/@opencode/cli/bin/opencode2.exe --standalone\n"
            if argv[0].endswith("opencode2.exe"):
                return "opencode2 v0.0.0-beta-19289\n"
            if argv[0] == "opencode":
                return "1.18.31\n"
            raise AssertionError(f"unexpected command: {argv}")
        return fake

    def test_v2_parent_is_found_by_bounded_ancestry_when_pid_env_is_missing(self):
        calls = []
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv == ["ps", "-p", "7001", "-o", "ppid=", "-o", "command="]:
                return "7000 /bin/zsh -lc python3 installer.py\n"
            if argv == ["ps", "-p", "7000", "-o", "ppid=", "-o", "command="]:
                return "6999 /usr/local/lib/node_modules/@opencode/cli/bin/opencode2.exe serve --service\n"
            if argv[0].endswith("opencode2.exe"):
                return "opencode2 v0.0.0-beta-19289\n"
            if argv[0] == "opencode":
                raise AssertionError("active v2 ancestry must win over PATH v1")
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.os, "getppid", return_value=7001), patch.object(
            compat.subprocess, "check_output", side_effect=fake
        ):
            self.assertEqual(compat.detect_opencode_version(), ("0.0.0-beta-19289", 2))
        self.assertEqual(sum(1 for c in calls if c and c[0] == "ps"), 2)

    def test_ancestry_walk_is_bounded_then_preserves_path_fallback(self):
        calls = []
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv[0] == "ps":
                pid = int(argv[2])
                return f"{pid - 1} /bin/helper-{pid}\n"
            if argv[0] == "opencode":
                return "1.18.31\n"
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.os, "getppid", return_value=9000), patch.object(
            compat.subprocess, "check_output", side_effect=fake
        ):
            self.assertEqual(compat.detect_opencode_version(), ("1.18.31", 1))
        self.assertEqual(sum(1 for c in calls if c and c[0] == "ps"), 6)

    def test_v1_parent_is_found_by_ancestry_without_being_upgraded(self):
        def fake(argv, **_kwargs):
            if argv == ["ps", "-p", "8100", "-o", "ppid=", "-o", "command="]:
                return "8099 /usr/local/lib/node_modules/opencode-ai/bin/opencode.exe serve\n"
            if argv[0].endswith("opencode.exe"):
                return "1.18.31\n"
            if argv[0] == "opencode2":
                raise AssertionError("v1 ancestry must not be upgraded merely because opencode2 exists")
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.os, "getppid", return_value=8100), patch.object(
            compat.subprocess, "check_output", side_effect=fake
        ):
            self.assertEqual(compat.detect_opencode_version(), ("1.18.31", 1))

    def test_active_v2_parent_wins_over_path_v1(self):
        calls = []
        with patch.dict(os.environ, {"OPENCODE_PID": "4242"}, clear=False), patch.object(
            compat.subprocess, "check_output", side_effect=self._fake_v2_host(calls)
        ):
            self.assertEqual(compat.detect_opencode_version(), ("0.0.0-beta-19289", 2))
        self.assertTrue(any(c[:2] == ["ps", "-p"] for c in calls))
        self.assertFalse(any(c[0] == "opencode" for c in calls if c))

    def test_opencode2_beta_output_is_generation_two_even_through_path_shim(self):
        def fake(argv, **_kwargs):
            if argv[0] == "opencode":
                return "opencode2 v0.0.0-beta-19289\n"
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.subprocess, "check_output", side_effect=fake):
            self.assertEqual(compat.detect_opencode_version(), ("0.0.0-beta-19289", 2))

    def test_only_v2_binary_visible_falls_back_without_guessing_over_v1(self):
        def fake(argv, **_kwargs):
            if argv[0] == "opencode":
                raise FileNotFoundError("no opencode")
            if argv[0] == "opencode2":
                return "opencode2 v0.0.0-beta-19289\n"
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.subprocess, "check_output", side_effect=fake):
            self.assertEqual(compat.detect_opencode_version(), ("0.0.0-beta-19289", 2))

    def test_v1_parent_remains_v1(self):
        calls = []
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv[:2] == ["ps", "-p"]:
                return "/usr/local/lib/node_modules/opencode-ai/bin/opencode.exe\n"
            if argv[0].endswith("opencode.exe"):
                return "1.18.31\n"
            if argv[0] == "opencode2":
                raise AssertionError("v1 parent must not be upgraded merely because opencode2 exists")
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {"OPENCODE_PID": "5151"}, clear=False), patch.object(compat.subprocess, "check_output", side_effect=fake):
            self.assertEqual(compat.detect_opencode_version(), ("1.18.31", 1))
        self.assertFalse(any(c[0] == "opencode2" for c in calls if c))

    def test_ancestry_v2_detection_drives_full_v2_adapter_upgrade(self):
        calls = []
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv == ["ps", "-p", "7201", "-o", "ppid=", "-o", "command="]:
                return "7200 /bin/zsh -lc python3 installer.py\n"
            if argv == ["ps", "-p", "7200", "-o", "ppid=", "-o", "command="]:
                return "7199 /usr/local/lib/node_modules/@opencode/cli/bin/opencode2.exe serve --service\n"
            if argv[0].endswith("opencode2.exe"):
                return "opencode2 v0.0.0-beta-19289\n"
            if argv[0] == "opencode":
                raise AssertionError("active v2 ancestry must win over PATH v1")
            raise AssertionError(f"unexpected command: {argv}")
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            plugins = project / ".opencode" / "plugins"
            plugins.mkdir(parents=True)
            (plugins / "tbag.js").write_text((ROOT / "adapters" / "opencode" / "tbag.js").read_text())
            (plugins / "tbag-status-tui-v1.tsx").write_text("stale-v1")
            tui = project / ".opencode" / "tui.json"
            tui.write_text('{"owner":true,"plugin":[["./plugins/tbag-status-tui-v1.tsx",{}]]}\n')
            with patch.dict(os.environ, {}, clear=True), patch.object(compat.os, "getppid", return_value=7201), patch.object(
                compat.subprocess, "check_output", side_effect=fake
            ):
                result = installer.install_opencode(project, ROOT)
            self.assertEqual(result["opencode_major"], 2)
            self.assertEqual(result["opencode_version"], "0.0.0-beta-19289")
            self.assertEqual(result["transport_generation"], "v2")
            self.assertEqual(result["tui_generation"], "v2")
            self.assertEqual((plugins / "tbag.js").read_text(), (ROOT / "adapters" / "opencode" / "tbag-v2.js").read_text())
            self.assertFalse((plugins / "tbag-status-tui-v1.tsx").exists())
            self.assertNotIn("tbag-status-tui-v1.tsx", tui.read_text())
            for name in ("index.ts", "tui.ts", "tui.tsx"):
                self.assertTrue((plugins / "tbag-ui" / name).is_file())
            self.assertTrue(Path(result["backup"]).is_file())

    def test_active_v2_detection_drives_full_v2_adapter_upgrade(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / "project"
            plugins = project / ".opencode" / "plugins"
            plugins.mkdir(parents=True)
            (plugins / "tbag.js").write_text((ROOT / "adapters" / "opencode" / "tbag.js").read_text())
            (plugins / "tbag-status-tui-v1.tsx").write_text("stale-v1")
            tui = project / ".opencode" / "tui.json"
            tui.write_text('{"owner":true,"plugin":[["./plugins/tbag-status-tui-v1.tsx",{}]]}\n')
            with patch.dict(os.environ, {"OPENCODE_PID": "6262"}, clear=False), patch.object(
                compat.subprocess, "check_output", side_effect=self._fake_v2_host(calls)
            ):
                result = installer.install_opencode(project, ROOT)
            self.assertEqual(result["opencode_major"], 2)
            self.assertEqual(result["opencode_version"], "0.0.0-beta-19289")
            self.assertEqual(result["transport_generation"], "v2")
            self.assertEqual(result["tui_generation"], "v2")
            self.assertEqual((plugins / "tbag.js").read_text(), (ROOT / "adapters" / "opencode" / "tbag-v2.js").read_text())
            self.assertFalse((plugins / "tbag-status-tui-v1.tsx").exists())
            self.assertNotIn("tbag-status-tui-v1.tsx", tui.read_text())
            for name in ("index.ts", "tui.ts", "tui.tsx"):
                self.assertTrue((plugins / "tbag-ui" / name).is_file())
            self.assertTrue(Path(result["backup"]).is_file())


if __name__ == "__main__":
    unittest.main()
