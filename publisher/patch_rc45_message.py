#!/usr/bin/env python3
from pathlib import Path
p=Path('scripts/dsd_task.py'); text=p.read_text(encoding='utf-8')
old='raise ValueError(f"{FOLLOWUP_HEADING} must contain only \'- ...\' bullets; indent wrapped continuation lines")'
new='raise ValueError(f"{FOLLOWUP_HEADING} must contain only single-line \'- ...\' bullets; indent wrapped continuation lines")'
if text.count(old)!=1: raise SystemExit(f'followup parser error target count={text.count(old)}')
p.write_text(text.replace(old,new),encoding='utf-8')
