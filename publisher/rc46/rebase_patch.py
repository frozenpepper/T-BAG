from pathlib import Path
p=Path('/tmp/apply_rc46.py')
text=p.read_text(encoding='utf-8')
old='### Replan / amendment graph'
if text.count(old)!=2:
    raise SystemExit(f'expected two stale cookbook headings in patch source, found {text.count(old)}')
p.write_text(text.replace(old,'## Register an Analyst graph'),encoding='utf-8')
