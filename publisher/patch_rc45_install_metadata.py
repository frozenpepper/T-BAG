#!/usr/bin/env python3
from pathlib import Path
p=Path('scripts/install_harness_adapter.py'); text=p.read_text(encoding='utf-8')
old='''        "autonomous_supervision": "per-attempt-tbag-follow-wake",\n'''
new='''        "autonomous_supervision": "per-attempt-wake-plus-parent-heartbeat",\n'''
if text.count(old)!=1: raise SystemExit(f'autonomous supervision target count={text.count(old)}')
text=text.replace(old,new)
old='''        "manual_step": "The installer proves only the project adapter file on disk; it cannot inspect the current OpenCode tool registry. If the adapter changed, restart/reload OpenCode to activate the refreshed hooks. The stable parent protocol is detached core dsd_attempt.py launch, then immediate tbag_follow for the exact returned run_root/phase_id/task_id/event_dir, then yield. If tbag_follow is already visible, that protocol remains safe even with an older follow-only adapter. Never run core dsd_attempt.py follow or a Bash/Python wait/poll in the OpenCode parent turn.",\n'''
new='''        "manual_step": "The installer proves only the project adapter file on disk; it cannot inspect the current OpenCode tool registry. If the adapter changed, restart/reload OpenCode to activate the refreshed hooks. Every owner turn/resume/wake/heartbeat begins with TBag/tools/parent_tick.py tick. New attempts still use detached core dsd_attempt.py launch followed immediately by tbag_follow; tbag_follow also registers the active run for the low-frequency heartbeat. Never run core dsd_attempt.py follow or a Bash/Python wait/poll in the OpenCode parent turn.",\n'''
if text.count(old)!=1: raise SystemExit(f'manual step target count={text.count(old)}')
p.write_text(text.replace(old,new),encoding='utf-8')
