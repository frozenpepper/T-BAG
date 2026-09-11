#!/usr/bin/env python3
from pathlib import Path
p=Path('PROMPTS.md'); text=p.read_text(encoding='utf-8')
repls={
'''FAIL resumes Planner then uses a **new** Plan Reviewer; PASS permits acceptance/rules creation.\n''':'''FAIL resumes Planner; review again fresh. PASS permits acceptance/rules creation.\n''',
'''`register-plan` returns `ready_registered`; use `ready` only for an explicit inventory.\n''':'''`register-plan` returns `ready_registered`.\n''',
'''Normal cleanup is automatic: integration retires task runtime; `reconcile-run` reaps safe leftovers; a cleanup-safe `completed` run purges its owned runtime. Manual commands are diagnostics/recovery only:\n''':'''Cleanup is lifecycle-owned; these are diagnostics/recovery only:\n''',
'''`cleanup --force --reason "..."` is explicit abandonment, never a way around an undisposed mutable delta. `~/.cache/t-bag` is shared; never raw-delete it or sibling runtimes.\n''':'''`cleanup --force --reason "..."` is explicit abandonment; never raw-delete shared cache/runtime paths.\n''',
'''Use `dsd_task.py owner-status --run-root ... [--phase-id ...]` for concise purpose-first owner context; use `reconcile-run --details` only for internal inventory. Never `cat`/tail raw artifacts. For legacy/non-gate reports only:\n''':'''Use `dsd_task.py owner-status --run-root ... [--phase-id ...]`; `reconcile-run --details` is internal inventory. For legacy/non-gate reports only:\n''',
'''If the bounded surface is insufficient, resume/clarify the worker; do not shadow-review the body.\n''':'''If insufficient, resume/clarify the worker; do not shadow-review.\n''',
}
for old,new in repls.items():
    if text.count(old)!=1: raise SystemExit(f'PROMPTS compact target count={text.count(old)}: {old[:80]!r}')
    text=text.replace(old,new)
p.write_text(text,encoding='utf-8')
