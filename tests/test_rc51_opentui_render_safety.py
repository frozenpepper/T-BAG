import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import opencode_tui_compat


_COMPONENT_ROOT = re.compile(
    r"function\s+([A-Z]\w*)\s*\([^)]*\)\s*\{(?:(?!\nfunction\s).)*?return\s*(?:\(\s*)?<([A-Za-z][\w.]*)",
    re.DOTALL,
)
_TEXT_BLOCK = re.compile(r"<text\b[^>]*>(.*?)</text>", re.DOTALL)
_CHILD_TAG = re.compile(r"<(?!/)([A-Za-z][\w.]*)\b")


def text_render_violations(source: str) -> list[str]:
    """Conservatively reject JSX children that OpenTUI text cannot accept.

    TextNodeRenderable accepts strings and branded text nodes such as spans. A
    reusable component inside <text> is therefore allowed only when its root is
    statically known to be <span>. Unknown components are rejected on purpose:
    presentation code must fail closed rather than crash the parent TUI.
    """
    component_roots = {name: root for name, root in _COMPONENT_ROOT.findall(source)}
    violations: list[str] = []
    for block in _TEXT_BLOCK.findall(source):
        for child in _CHILD_TAG.findall(block):
            if child == "span":
                continue
            if component_roots.get(child) == "span":
                continue
            resolved = component_roots.get(child, child)
            violations.append(f"<text> contains <{child}> resolving to <{resolved}>")
    return violations


class OpenTuiTextSafetyTests(unittest.TestCase):
    def test_all_shipped_opencode_tui_sources_obey_text_child_contract(self):
        sources = [
            ROOT / "adapters" / "opencode" / "tbag-status-tui-v1.tsx",
            ROOT / "adapters" / "opencode" / "tbag-ui" / "tui.tsx",
        ]
        for path in sources:
            with self.subTest(path=path):
                self.assertEqual(text_render_violations(path.read_text()), [])

    def test_guard_catches_component_that_renders_text_inside_text(self):
        bad = """
function Bar() {
  return <text>████</text>
}
function Row() {
  return <text>progress <Bar /></text>
}
"""
        self.assertEqual(
            text_render_violations(bad),
            ["<text> contains <Bar> resolving to <text>"],
        )

    def test_v1_progress_bar_is_plain_text_not_a_nested_text_component(self):
        source = (ROOT / "adapters" / "opencode" / "tbag-status-tui-v1.tsx").read_text()
        self.assertIn("function progressBar(", source)
        self.assertNotIn("function SegmentedBar(", source)


class OpenCodeLegacyTuiRegistrationTests(unittest.TestCase):
    def test_ensure_migrates_legacy_v1_registration_without_touching_owner_plugin(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            config = project / ".opencode" / "tui.json"
            config.parent.mkdir(parents=True)
            legacy = opencode_tui_compat.LEGACY_V1_SPECS[0]
            config.write_text(
                "{\n"
                '  "plugin": [\n'
                '    ["./plugins/owner.tsx", {"keep": true}],\n'
                f'    ["{legacy}", {{}}]\n'
                "  ]\n"
                "}\n"
            )

            changed, path = opencode_tui_compat.ensure_tui_plugin(project)

            self.assertTrue(changed)
            self.assertEqual(path, config)
            text = config.read_text()
            self.assertIn("./plugins/owner.tsx", text)
            self.assertNotIn(legacy, text)
            self.assertEqual(text.count(opencode_tui_compat.V1_SPEC), 1)

    def test_remove_canonical_v1_registration_also_retires_legacy_alias(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            config = project / ".opencode" / "tui.json"
            config.parent.mkdir(parents=True)
            legacy = opencode_tui_compat.LEGACY_V1_SPECS[0]
            config.write_text(
                "{\n"
                '  "plugin": [\n'
                f'    ["{opencode_tui_compat.V1_SPEC}", {{}}],\n'
                f'    ["{legacy}", {{}}],\n'
                '    ["./plugins/owner.tsx", {}]\n'
                "  ]\n"
                "}\n"
            )

            changed, _ = opencode_tui_compat.remove_tui_plugin(project)

            self.assertTrue(changed)
            text = config.read_text()
            self.assertNotIn(opencode_tui_compat.V1_SPEC, text)
            self.assertNotIn(legacy, text)
            self.assertIn("./plugins/owner.tsx", text)


if __name__ == "__main__":
    unittest.main()
