import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import opencode_tui_compat as compat


class RC59FieldFixTests(unittest.TestCase):
    def test_wrapper_payload_cannot_impersonate_opencode1(self):
        self.assertIsNone(compat._generation_hint("/bin/zsh -lc 'python3 installer.py --harness opencode --project-root /project'"))

    def test_wrapper_payload_cannot_impersonate_opencode2(self):
        self.assertIsNone(compat._generation_hint("/bin/zsh -lc 'echo opencode2 && python3 probe.py'"))

    def test_real_opencode2_ancestor_wins_after_wrapper_with_harness_argument(self):
        calls = []
        def fake(argv, **_kwargs):
            calls.append(list(argv))
            if argv == ["ps", "-p", "7301", "-o", "ppid=", "-o", "command="]:
                return "7300 /bin/zsh -lc python3 installer.py --harness opencode --project-root /project\n"
            if argv == ["ps", "-p", "7300", "-o", "ppid=", "-o", "command="]:
                return "7299 /usr/local/lib/node_modules/@opencode/cli/bin/opencode2.exe serve --service\n"
            if argv[0].endswith("opencode2.exe"):
                return "opencode2 v0.0.0-beta-19289\n"
            if argv[0] == "opencode":
                raise AssertionError("PATH v1 must not win over the real v2 ancestor")
            raise AssertionError(f"unexpected command: {argv}")
        with patch.dict(os.environ, {}, clear=True), patch.object(compat.os, "getppid", return_value=7301), patch.object(
            compat.subprocess, "check_output", side_effect=fake
        ):
            self.assertEqual(compat.detect_opencode_version(), ("0.0.0-beta-19289", 2))
        self.assertEqual(sum(1 for call in calls if call and call[0] == "ps"), 2)

    def test_v2_ui_uses_field_proven_loading_and_keymap_shape(self):
        index = (ROOT / "adapters/opencode/tbag-ui/index.ts").read_text()
        tui = (ROOT / "adapters/opencode/tbag-ui/tui.tsx").read_text()
        self.assertIn('import type { Plugin } from "@opencode/plugin"', index)
        self.assertNotIn('import { Plugin } from "@opencode/plugin"', index)
        self.assertNotIn('Plugin.define(', index)
        self.assertNotIn('import path from "node:path"', tui)
        self.assertNotIn('usePlugin', tui)
        self.assertIn('append: "prompt.footer.status"', tui)
        self.assertGreater(tui.index('context.keymap.layer'), tui.index('append: "prompt.footer.status"'))
        self.assertIn('style={{ fg:', tui)
        self.assertIn('clearInterval(clock)', tui)

    def test_project_local_scratch_rule_is_always_loaded_and_opencode_repeats_only_the_reference(self):
        skill = (ROOT / "SKILL.md").read_text()
        opencode = (ROOT / "OPENCODE.md").read_text()
        self.assertIn("Project-local scratch", skill)
        self.assertIn("/private/var", skill)
        self.assertIn("SKILL.md` project-local scratch boundary", opencode)
        self.assertIn("--harness opencode", opencode)


if __name__ == "__main__":
    unittest.main()
