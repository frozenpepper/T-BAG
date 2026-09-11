#!/usr/bin/env python3
from pathlib import Path

def replace_once(path,old,new):
    p=Path(path); text=p.read_text(encoding='utf-8'); n=text.count(old)
    if n!=1: raise SystemExit(f'{path}: target count={n}: {old[:120]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')

replace_once('PROMPTS.md',
'''## Resume / tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Use this on every owner turn, resume, adapter wake and heartbeat. It owns reconcile + deterministic advance + live-attempt monitoring + update/project-end classification. If `owner_update.due=true`, send its bounded status then:

```bash
python3 <skill>/scripts/parent_tick.py ack-update --run-root ... --token <token>
```

A `completion-candidate` is not silent idle. Either register/replan remaining accepted-plan work or, after confirming plan exhaustion:

```bash
python3 <skill>/scripts/parent_tick.py finish --run-root ... --reason "accepted plan obligations exhausted"
```
''',
'''## Parent tick / turn boundary

```bash
python3 <skill>/scripts/parent_tick.py tick --run-root ... [--phase-id ...]
```

Run on owner turn/resume/wake/heartbeat. The packet owns reconcile, advance, monitoring, updates and end-state routing. After sending `owner_update`, acknowledge its token with `parent_tick.py ack-update`; on `completion-candidate`, replan or `parent_tick.py finish --reason "..."` after confirming plan exhaustion.
''')

replace_once('OPENCODE.md',
'''The wake bit is disposable. Durable T-BAG state remains authoritative: after plugin/server restart or a lost wake submission, the next owner turn begins with `reconcile-run`, which rediscovers terminal-but-ungated attempts and reports already-live attempts that need re-arming. Session deletion suppresses obsolete wake delivery; a successor parent simply reconciles and re-arms under its own session.

The adapter never polls idleness, chooses models/tasks, launches additional work, gates evidence, accepts tasks, integrates, or persists notification state.
''',
'''Wake state is disposable. Per-attempt wakes are only fast hints; the run heartbeat requests another parent tick when one is lost. The tick re-derives live/terminal/action state from durable T-BAG files. Session deletion suppresses obsolete delivery; a successor session registers its own heartbeat on `tbag_follow`.

The adapter never polls idleness, chooses models/tasks, launches additional work, gates evidence, accepts tasks, integrates, or persists semantic notification state.
''')
replace_once('OPENCODE.md',
'''The project plugin injects reconcile-first orientation plus the launch → follow → yield invariant into compaction context. It creates no parallel checkpoint stream.
''',
'''The project plugin injects tick-first orientation plus launch → follow → yield. It creates no parallel checkpoint stream.
''')
