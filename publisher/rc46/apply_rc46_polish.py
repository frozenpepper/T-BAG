from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise SystemExit(f'{path}: expected one polish anchor, found {count}: {old[:160]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')

# Keep the hot operator cookbook under its existing size budget.
replace_once('PROMPTS.md',
'''A Human `resolve-escalation --route analysis` opens the Analyst lane; it is not approval of a technical graph. The Analyst still records `analysis-result --outcome replan` before that graph can be registered.\n''',
'''Human `--route analysis` opens the Analyst lane; the Analyst still records `replan` before graph registration.\n''')

# Progress means current registered obligations, not historical superseded work or the
# phase-auditor gate itself.
replace_once('scripts/tbag_status.py',
'''CONTROL_ROLES = {"plan-reviewer", "context-reviewer"}\n''',
'''CONTROL_ROLES = {"plan-reviewer", "context-reviewer", "phase-auditor"}\n''')
replace_once('scripts/tbag_status.py',
'''                control = role in CONTROL_ROLES\n                done = _task_done(run, phase, task)\n                if not control:\n                    registered_total += 1\n                    if done:\n                        registered_done += 1\n''',
'''                control = role in CONTROL_ROLES\n                obsolete = str(task.get("status") or "") == "superseded"\n                countable = not control and not obsolete\n                done = _task_done(run, phase, task)\n                if countable:\n                    registered_total += 1\n                    if done:\n                        registered_done += 1\n''')
replace_once('scripts/tbag_status.py',
'''                    "control_conduit": control,\n                    "updated_at": task.get("updated_at"),\n''',
'''                    "control_conduit": control,\n                    "counted_in_progress": countable,\n                    "updated_at": task.get("updated_at"),\n''')
replace_once('scripts/tbag_status.py',
'''        counted = [x for x in tasks if not x.get("control_conduit")]\n''',
'''        counted = [x for x in tasks if x.get("counted_in_progress")]\n''')

# Give the session panel the evidence the field report actually needed: CPU use and
# last log/report activity, without dumping raw logs.
replace_once('adapters/opencode/tbag-ui/tui.tsx',
'''      <text>{`  ${String(w().model ?? "unknown model")} · ${shortSession(w().session?.id)} · ${workerHealth(w())}`}</text>\n''',
'''      <text>{`  ${String(w().model ?? "unknown model")} · ${shortSession(w().session?.id)} · ${workerHealth(w())}`}</text>\n      <text>{`  CPU ${w().process?.worker?.cpu_percent ?? "?"}% / ${duration(w().process?.worker?.cpu_seconds)} · log ${duration(w().log_age_seconds)} ago · report ${duration(w().report_age_seconds)} ago`}</text>\n''')

# OpenCode's local CLI-plugin discovery documents tui.ts; keep JSX in tui.tsx and use
# the tiny discovery bridge so the implementation stays readable.
replace_once('scripts/install_harness_adapter.py',
'''    for name in ("index.ts","tui.tsx"):\n''',
'''    for name in ("index.ts","tui.ts","tui.tsx"):\n''')

# Tight source-level guard for the documented bridge and progress semantics.
replace_once('tests/test_rc46_supervision.py',
'''        self.assertIn('TBag", "tools", "tbag_status.py"',tui)\n''',
'''        self.assertIn('TBag", "tools", "tbag_status.py"',tui)\n        self.assertIn('CPU ${w().process?.worker?.cpu_percent',tui)\n        bridge=(Path(__file__).resolve().parents[1]/"adapters"/"opencode"/"tbag-ui"/"tui.ts").read_text()\n        self.assertIn('./tui.tsx',bridge)\n''')
