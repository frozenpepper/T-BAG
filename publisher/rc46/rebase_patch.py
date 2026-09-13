from pathlib import Path
p=Path('/tmp/apply_rc46.py')
text=p.read_text(encoding='utf-8')
old='### Replan / amendment graph'
if text.count(old)!=2:
    raise SystemExit(f'expected two stale cookbook headings in patch source, found {text.count(old)}')
text=text.replace(old,'## Register an Analyst graph')
old_session='for value in (attempt.get("session_id"),(terminal or {}).get("session_id"),attempt.get("resume_session")):'
new_session='for value in ((terminal or {}).get("session_id"),attempt.get("session_id"),attempt.get("resume_session")):'
if text.count(old_session)!=1:
    raise SystemExit(f'expected one session-precedence anchor in patch source, found {text.count(old_session)}')
text=text.replace(old_session,new_session)
p.write_text(text,encoding='utf-8')
