#!/usr/bin/env python3
from pathlib import Path
p=Path('tests/opencode_plugin_runtime.mjs'); text=p.read_text(encoding='utf-8')
old='''assert.match(prompts[0].body.parts[0].text, /reconcile-run/)\nassert.match(prompts[0].body.parts[0].text, /tbag_follow/)\n'''
new='''assert.match(prompts[0].body.parts[0].text, /parent_tick\\.py tick/)\nassert.match(prompts[0].body.parts[0].text, /tbag_follow/)\n'''
if text.count(old)!=1: raise SystemExit(f'opencode wake assertion target count={text.count(old)}')
text=text.replace(old,new)
old='''assert.equal(explicit.armed, true)\nassert.equal(explicit.already_armed, true)\n'''
new='''assert.equal(explicit.armed, true)\nassert.equal(explicit.already_armed, true)\nassert.equal(explicit.observer_healthy, true)\nassert.equal(explicit.heartbeat_registered, true)\n'''
if text.count(old)!=1: raise SystemExit(f'opencode observer assertion target count={text.count(old)}')
p.write_text(text.replace(old,new),encoding='utf-8')
