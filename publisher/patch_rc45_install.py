#!/usr/bin/env python3
from pathlib import Path

def replace_once(path,old,new):
    p=Path(path); text=p.read_text(encoding='utf-8'); n=text.count(old)
    if n!=1: raise SystemExit(f'{path}: target count={n}: {old[:100]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')

replace_once('scripts/install_harness_adapter.py',
'''    dsd_task = tools / "dsd_task.py"\n    dsd_attempt = tools / "dsd_attempt.py"\n    write_skill_shim(target, skill_root / "scripts" / "context_checkpoint.py")\n    write_skill_shim(dsd_task, skill_root / "scripts" / "dsd_task.py")\n    write_skill_shim(dsd_attempt, skill_root / "scripts" / "dsd_attempt.py")\n''',
'''    dsd_task = tools / "dsd_task.py"\n    dsd_attempt = tools / "dsd_attempt.py"\n    parent_tick = tools / "parent_tick.py"\n    write_skill_shim(target, skill_root / "scripts" / "context_checkpoint.py")\n    write_skill_shim(dsd_task, skill_root / "scripts" / "dsd_task.py")\n    write_skill_shim(dsd_attempt, skill_root / "scripts" / "dsd_attempt.py")\n    write_skill_shim(parent_tick, skill_root / "scripts" / "parent_tick.py")\n''')
replace_once('scripts/install_harness_adapter.py',
'''    return {"context_checkpoint": target, "dsd_task": dsd_task, "dsd_attempt": dsd_attempt}\n''',
'''    return {"context_checkpoint": target, "dsd_task": dsd_task, "dsd_attempt": dsd_attempt, "parent_tick": parent_tick}\n''')
replace_once('scripts/context_checkpoint.py',
'''        f"First run `python3 <skill>/scripts/dsd_task.py reconcile-run --run-root {run}` and follow returned lifecycle actions/READY work before housekeeping.",\n''',
'''        f"First run `python3 <skill>/scripts/parent_tick.py tick --run-root {run}` and follow its continue/launch/update/intervene/finish boundary; do not reconstruct a separate monitor loop.",\n''')
