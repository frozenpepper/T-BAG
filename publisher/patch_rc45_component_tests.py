#!/usr/bin/env python3
from pathlib import Path

def replace_once(path,old,new):
    p=Path(path); text=p.read_text(encoding='utf-8'); n=text.count(old)
    if n!=1: raise SystemExit(f'{path}: target count={n}: {old[:100]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')

# Compaction now enters the canonical parent tick, whose first operation is reconcile.
replace_once('tests/test_components.py',"        self.assertIn('reconcile-run',cp.stdout)\n        self.assertNotIn('ready --run-root',cp.stdout)\n","        self.assertIn('parent_tick.py tick',cp.stdout)\n        self.assertNotIn('ready --run-root',cp.stdout)\n")
replace_once('tests/test_components.py',"        self.assertEqual(cp.returncode,0,cp.stderr); self.assertIn(str(other),cp.stdout); self.assertIn('reconcile-run',cp.stdout)\n","        self.assertEqual(cp.returncode,0,cp.stderr); self.assertIn(str(other),cp.stdout); self.assertIn('parent_tick.py tick',cp.stdout)\n")

replace_once('tests/test_components.py',
'''                helper=project/'TBag'/'tools'/'context_checkpoint.py'; task_helper=project/'TBag'/'tools'/'dsd_task.py'; attempt_helper=project/'TBag'/'tools'/'dsd_attempt.py'\n                self.assertTrue(helper.is_file()); self.assertTrue(task_helper.is_file()); self.assertTrue(attempt_helper.is_file())\n''',
'''                helper=project/'TBag'/'tools'/'context_checkpoint.py'; task_helper=project/'TBag'/'tools'/'dsd_task.py'; attempt_helper=project/'TBag'/'tools'/'dsd_attempt.py'; tick_helper=project/'TBag'/'tools'/'parent_tick.py'\n                self.assertTrue(helper.is_file()); self.assertTrue(task_helper.is_file()); self.assertTrue(attempt_helper.is_file()); self.assertTrue(tick_helper.is_file())\n''')
replace_once('tests/test_components.py',
'''                self.assertIn(str((SCRIPTS/'dsd_task.py').resolve()),task_helper.read_text()); self.assertIn(str((SCRIPTS/'dsd_attempt.py').resolve()),attempt_helper.read_text())\n''',
'''                self.assertIn(str((SCRIPTS/'dsd_task.py').resolve()),task_helper.read_text()); self.assertIn(str((SCRIPTS/'dsd_attempt.py').resolve()),attempt_helper.read_text()); self.assertIn(str((SCRIPTS/'parent_tick.py').resolve()),tick_helper.read_text())\n''')

# Two installer expectations use the same old autonomous-supervision value.
p=Path('tests/test_components.py'); text=p.read_text(encoding='utf-8')
old="self.assertEqual(data['autonomous_supervision'],'per-attempt-tbag-follow-wake')"
if text.count(old)!=2: raise SystemExit(f'autonomous supervision expectation count={text.count(old)}')
text=text.replace(old,"self.assertEqual(data['autonomous_supervision'],'per-attempt-wake-plus-parent-heartbeat')")
p.write_text(text,encoding='utf-8')

replace_once('tests/test_components.py',
'''        self.assertNotIn('OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS',text); self.assertNotIn('promptAsync',text)\n        self.assertNotIn('setInterval(',text); self.assertNotIn('setTimeout(',text)\n''',
'''        self.assertNotIn('OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS',text); self.assertNotIn('promptAsync',text)\n        self.assertIn('runHeartbeats',text); self.assertIn('HEARTBEAT_MS',text); self.assertIn('setInterval(',text); self.assertIn('heartbeatTimer.unref',text)\n        self.assertNotIn('setTimeout(',text)\n''')
