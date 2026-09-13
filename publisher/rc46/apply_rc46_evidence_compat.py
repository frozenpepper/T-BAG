from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise SystemExit(f'{path}: expected one semantic-lane compatibility anchor, found {count}: {old[:180]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')


replace_once('scripts/dsd_task.py',
'''            task["status"]=_stale_retry_status(task,found)\n''',
'''            prior=str(found.get("prior_task_status") or "")\n            if prior in {"needs-fix","needs-analysis","recovery-required","awaiting-review","review-passed"}:\n                task["status"]=_stale_retry_status(task,found)\n''')

replace_once('CHANGELOG.md',
'''- Separated chronological attempt order from semantic Review authority. Empty zero-delta placeholder retries restore the lane they entered instead of consuming it; they do not stale a standing Reviewer verdict, and Analyst `resume` returns to that still-authoritative Review lane when appropriate.\n''',
'''- Separated chronological attempt order from semantic Review authority. Empty zero-delta placeholder retries preserve any standing semantic lane they entered instead of consuming it, while ordinary base-role retries keep the existing active same-session path; empty retries do not stale a standing Reviewer verdict, and Analyst `resume` returns to that still-authoritative Review lane when appropriate.\n''')

replace_once('tests/test_rc46_supervision.py',
'''    def test_substantive_newer_fixer_does_stale_old_review(self):\n''',
'''    def test_plain_base_retry_keeps_existing_active_resume_lane(self):\n        with tempfile.TemporaryDirectory() as td:\n            run=Path(td)/"run"; root=run/"phases"/"P"/"tasks"/"T"; root.mkdir(parents=True)\n            event=root/"implementer"; self._empty_terminal(event)\n            attempt={"event_dir":str(event),"role":"implementer","status":"started","prior_task_status":"planned"}\n            state={"format":dsd_task.FORMAT,"phase_id":"P","task_id":"T","kind":"implementation","role":"implementer","requires_integration":True,"status":"active","attempts":[attempt]}\n            dsd_task.write_json(root/"task.json",state)\n            out=dsd_task.command_update_attempt(SimpleNamespace(run_root=run,phase_id="P",task_id="T",event_dir=event,status="report-resume",gate=None,session_id=None))\n            self.assertEqual(out["task_status"],"active")\n\n    def test_substantive_newer_fixer_does_stale_old_review(self):\n''')
