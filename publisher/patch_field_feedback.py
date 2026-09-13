from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count != 1:
        raise SystemExit(f'{path}: expected exactly one target, found {count}: {old[:140]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')


# --- Routing-token normalization: tolerate Markdown syntax, never infer prose. ---
marker='''def declared_report_outcome(report: Path, role: str, *, required: bool = False) -> str | None:\n'''
helpers='''def _routing_line_outcome(raw: str, allowed: dict[str, str]) -> str | None:\n    """Parse one explicit routing line after harmless Markdown decoration."""\n    text=raw.strip()\n    text=re.sub(r"^#{1,6}\\s+", "", text)\n    text=re.sub(r"^[*+-]\\s+", "", text)\n    for token in sorted(allowed,key=len,reverse=True):\n        escaped=re.escape(token)\n        forms=(escaped,rf"\\*\\*{escaped}\\*\\*",rf"__{escaped}__",rf"\\*{escaped}\\*",rf"`{escaped}`")\n        if re.fullmatch(rf"(?:{'|'.join(forms)})(?:\\s*(?:—|–|-|:)\\s+.+)?",text):\n            return allowed[token]\n    return None\n\n\ndef _decorative_routing_heading(raw: str, allowed: dict[str, str]) -> bool:\n    """A pure Markdown title may precede the routing line; a verdict-bearing title may not."""\n    text=raw.strip()\n    if not re.match(r"^#{1,6}\\s+\\S",text):\n        return False\n    upper=text.upper()\n    for token in sorted(allowed,key=len,reverse=True):\n        if re.search(rf"(?<![A-Z0-9_]){re.escape(token)}(?![A-Z0-9_])",upper):\n            return False\n    return True\n\n\n'''
replace_once('scripts/dsd_task.py',marker,helpers+marker)

old='''    nonempty=[raw.strip() for raw in report.read_text(encoding="utf-8",errors="replace").splitlines() if raw.strip()]\n    first=nonempty[0] if nonempty else ""\n    outcome=allowed.get(first)\n    if outcome is None and first:\n        # Still deterministic: accept only an allowed token anchored at the start of\n        # the first line, optionally Markdown-bolded and followed by an explicit\n        # punctuation separator. Never infer PASS/FAIL from ordinary prose.\n        for token in sorted(allowed,key=len,reverse=True):\n            pattern=rf"^(?:\\*\\*)?{re.escape(token)}(?:\\*\\*)?(?:\\s*(?:—|–|-|:)\\s+.+)?$"\n            if re.fullmatch(pattern,first):\n                outcome=allowed[token]; break\n    if outcome is not None:\n        return outcome\n'''
new='''    nonempty=[raw.strip() for raw in report.read_text(encoding="utf-8",errors="replace").splitlines() if raw.strip()]\n    first=nonempty[0] if nonempty else ""\n    outcome=_routing_line_outcome(first,allowed) if first else None\n    if outcome is None and first and _decorative_routing_heading(first,allowed):\n        # A model may lead with one or two pure Markdown title headings. They are\n        # presentation, not semantic content. Stop immediately on any non-heading\n        # line, or any heading that itself mentions a routing token.\n        index=1; skipped=1\n        while index < len(nonempty) and skipped < 2 and _decorative_routing_heading(nonempty[index],allowed):\n            index+=1; skipped+=1\n        if index < len(nonempty):\n            outcome=_routing_line_outcome(nonempty[index],allowed)\n    if outcome is not None:\n        return outcome\n'''
replace_once('scripts/dsd_task.py',old,new)

# --- Advance: quarantine one bad deterministic action for this pass, continue others. ---
replace_once('scripts/dsd_task.py',
'''    run=args.run_root.resolve(); max_steps=int(args.max_steps or 12); applied=[]\n    for index in range(max_steps):\n''',
'''    run=args.run_root.resolve(); max_steps=int(args.max_steps or 12); applied=[]; blocked_actions=[]; blocked_keys=set()\n    def action_key(item: dict[str, Any]) -> str:\n        return json.dumps(item,sort_keys=True,separators=(",",":"),default=str)\n    for index in range(max_steps):\n''')

replace_once('scripts/dsd_task.py',
'''        state=command_reconcile_run(r); actions=list(state.get("first_useful_actions") or [])\n        if not actions:\n            return {"applied":applied,"stopped":"quiescent","state":state}\n        action=actions[0]; name=str(action.get("action") or ""); phase=str(action.get("phase_id") or ""); tid=str(action.get("task_id") or "")\n''',
'''        state=command_reconcile_run(r); actions=list(state.get("first_useful_actions") or [])\n        if not actions:\n            result={"applied":applied,"stopped":"quiescent","state":state}\n            if blocked_actions: result["blocked_actions"]=blocked_actions\n            return result\n        action=next((item for item in actions if action_key(item) not in blocked_keys),None)\n        if action is None:\n            return {"applied":applied,"stopped":"control-error","blocked_actions":blocked_actions,"state":state}\n        name=str(action.get("action") or ""); phase=str(action.get("phase_id") or ""); tid=str(action.get("task_id") or "")\n''')

# Preserve blocked-action context on semantic boundaries.
replace_once('scripts/dsd_task.py',
'''                    return {"applied":applied,"stopped":"semantic-boundary","next_action":action,"reason":"legacy report needs explicit outcome command","state":state}\n''',
'''                    result={"applied":applied,"stopped":"semantic-boundary","next_action":action,"reason":"legacy report needs explicit outcome command","state":state}\n                    if blocked_actions: result["blocked_actions"]=blocked_actions\n                    return result\n''')
replace_once('scripts/dsd_task.py',
'''                    return {"applied":applied,"stopped":"semantic-boundary","next_action":action,"state":state}\n''',
'''                    result={"applied":applied,"stopped":"semantic-boundary","next_action":action,"state":state}\n                    if blocked_actions: result["blocked_actions"]=blocked_actions\n                    return result\n''')
replace_once('scripts/dsd_task.py',
'''                return {"applied":applied,"stopped":"semantic-or-launch-boundary","next_action":action,"state":state}\n        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:\n            return {"applied":applied,"stopped":"control-error","next_action":action,"error":str(exc),"state":state}\n''',
'''                result={"applied":applied,"stopped":"semantic-or-launch-boundary","next_action":action,"state":state}\n                if blocked_actions: result["blocked_actions"]=blocked_actions\n                return result\n        except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:\n            key=action_key(action); blocked_keys.add(key)\n            blocked_actions.append({"key":key,"action":name,"phase_id":phase or None,"task_id":tid or None,"error":str(exc)})\n            continue\n''')
replace_once('scripts/dsd_task.py',
'''    return {"applied":applied,"stopped":"step-limit","state":state}\n''',
'''    result={"applied":applied,"stopped":"step-limit","state":state}\n    if blocked_actions: result["blocked_actions"]=blocked_actions\n    return result\n''')

# --- Parent tick: never hand quarantined actions back as executable work. ---
replace_once('scripts/parent_tick.py',
'''def args_for(**values: Any) -> SimpleNamespace:\n    return SimpleNamespace(**values)\n\n\ndef reconcile''',
'''def args_for(**values: Any) -> SimpleNamespace:\n    return SimpleNamespace(**values)\n\n\ndef action_key(item: dict[str, Any]) -> str:\n    return json.dumps(item,sort_keys=True,separators=(",",":"),default=str)\n\n\ndef reconcile''')
replace_once('scripts/parent_tick.py',
'''    if any(x.get("attention") == "silent-long-running" for x in monitors): urgent.append("worker-stall")\n''',
'''    if any(x.get("attention") == "silent-long-running" for x in monitors): urgent.append("worker-stall")\n    if classification == "recovery-required": urgent.append("control-recovery-required")\n''')
replace_once('scripts/parent_tick.py',
'''    run_status = str(state.get("run_status") or "active")\n    pending = list(state.get("first_useful_actions") or [])\n    live_now = list(state.get("live_attempts") or [])\n''',
'''    run_status = str(state.get("run_status") or "active")\n    blocked_actions=list(advance_result.get("blocked_actions") or []) if isinstance(advance_result,dict) else []\n    blocked_keys={str(item.get("key") or "") for item in blocked_actions if isinstance(item,dict)}\n    pending_all=list(state.get("first_useful_actions") or [])\n    pending=[item for item in pending_all if action_key(item) not in blocked_keys]\n    live_now = list(state.get("live_attempts") or [])\n''')
replace_once('scripts/parent_tick.py',
'''    elif any(x.get("retirement_error") for x in monitors) or state.get("unresolved_state"):\n        classification = "recovery-required"\n        turn = "intervene"\n    elif pending:\n''',
'''    elif any(x.get("retirement_error") for x in monitors) or state.get("unresolved_state") or (blocked_actions and not pending):\n        classification = "recovery-required"\n        turn = "intervene"\n    elif pending:\n''')
replace_once('scripts/parent_tick.py',
'''    if advance_result: out["advance"] = advance_result\n    if pending: out["actions"] = pending\n''',
'''    if advance_result: out["advance"] = advance_result\n    if blocked_actions: out["blocked_actions"] = blocked_actions\n    if pending: out["actions"] = pending\n''')

# --- Field-derived OpenCode credential-rotation recovery note. ---
replace_once('OPENCODE.md',
'''Direct bash/python `dsd_attempt.py follow` remains forbidden because it can monopolize the conversational turn. The project-local `tbag_follow` tool backgrounds the same core observer and returns immediately.\n''',
'''Direct bash/python `dsd_attempt.py follow` remains forbidden because it can monopolize the conversational turn. The project-local `tbag_follow` tool backgrounds the same core observer and returns immediately.\n\nCredential/config rotation is not assumed to hot-reload inside an already-running worker. If a worker stops making progress after rotation, use lifecycle retirement plus retained-session resume/retry; never make the parent inventory sibling processes or issue raw `ps`/`kill`.\n''')

# --- Tests: measured SQR8V2 markdown shapes + poison-action continuation. ---
replace_once('tests/test_rc45_parent_tick.py',
'''            for text in ("PASS — all checks green\\n", "**PASS**\\n", "ESCALATE CAPABILITY: provider exhausted\\n"):\n''',
'''            for text in ("PASS — all checks green\\n", "**PASS**\\n", "**PASS** — reviewer summary\\n", "# PASS\\n", "* PASS\\n", "`PASS`\\n", "# T-BAG Phase Auditor report\\nPASS\\n", "## Phase gate\\n**PASS** — all predicates green\\n", "ESCALATE CAPABILITY: provider exhausted\\n"):\n''')
replace_once('tests/test_rc45_parent_tick.py',
'''            report.write_text("The evidence looks like PASS to me.\\n")\n            with self.assertRaisesRegex(ValueError,"must begin"):\n                dsd_task.declared_report_outcome(report,"verification",required=True)\n''',
'''            for invalid in ("The evidence looks like PASS to me.\\n", "# Verdict: PASS\\n", "# Phase gate\\nNarrative first.\\nPASS\\n"):\n                report.write_text(invalid)\n                with self.assertRaisesRegex(ValueError,"must begin"):\n                    dsd_task.declared_report_outcome(report,"verification",required=True)\n''')

insert='''\n    def test_advance_quarantines_bad_action_and_continues_unrelated_work(self):\n        args=SimpleNamespace(run_root=Path('/run'),phase_id=None,max_steps=6)\n        bad={"action":"record-verification-result","phase_id":"P","task_id":"BAD","report":"/tmp/bad.md"}\n        good={"action":"record-phase-gate","phase_id":"P","task_id":"GOOD","report":"/tmp/good.md"}\n        states=[{"first_useful_actions":[bad,good]},{"first_useful_actions":[bad,good]},{"first_useful_actions":[bad]}]\n        with mock.patch.object(dsd_task,"command_reconcile_run",side_effect=states), \\\n             mock.patch.object(dsd_task,"command_verification_result",side_effect=ValueError("bad report")), \\\n             mock.patch.object(dsd_task,"command_phase_gate",return_value={"recorded":True}) as phase_gate:\n            out=dsd_task.command_advance(args)\n        phase_gate.assert_called_once()\n        self.assertEqual(out["stopped"],"control-error")\n        self.assertEqual(len(out["blocked_actions"]),1)\n        self.assertEqual(out["blocked_actions"][0]["task_id"],"BAD")\n        self.assertEqual(out["applied"][0]["task_id"],"GOOD")\n\n'''
replace_once('tests/test_rc45_parent_tick.py','''\n\nclass Rc45ParentTickTests(unittest.TestCase):\n''',insert+'''\nclass Rc45ParentTickTests(unittest.TestCase):\n''')

insert2='''\n    @mock.patch.object(parent_tick.dsd_task,"command_owner_status",return_value={"status":"ok"})\n    @mock.patch.object(parent_tick.dsd_task,"load_run",return_value={"status":"active"})\n    def test_tick_filters_quarantined_action_but_exposes_other_work(self,_load,_owner):\n        bad={"action":"record-verification-result","phase_id":"P","task_id":"BAD","report":"/tmp/bad.md"}\n        good={"action":"launch-worker","phase_id":"P","task_id":"GOOD"}\n        blocked={"key":parent_tick.action_key(bad),"action":bad["action"],"phase_id":"P","task_id":"BAD","error":"bad report"}\n        with mock.patch.object(parent_tick.dsd_task,"command_advance",return_value={"stopped":"semantic-or-launch-boundary","blocked_actions":[blocked]}), \\\n             mock.patch.object(parent_tick,"reconcile",return_value=self.base_state(first_useful_actions=[bad,good],backlog_count=2)):\n            out=parent_tick.command_tick(self.args)\n        self.assertEqual(out["classification"],"actions-ready")\n        self.assertEqual(out["actions"],[good])\n        self.assertEqual(out["blocked_actions"][0]["task_id"],"BAD")\n\n'''
replace_once('tests/test_rc45_parent_tick.py','''    @mock.patch.object(parent_tick.dsd_task,"command_set_run_status",return_value={"status":"completed"})\n''',insert2+'''    @mock.patch.object(parent_tick.dsd_task,"command_set_run_status",return_value={"status":"completed"})\n''')

# Changelog addendum inside RC45 entry.
replace_once('CHANGELOG.md',
'''- Relaxed only the mechanical report envelope (anchored suffixed/bold verdict tokens, footer-safe/empty follow-up obligations), fixed superseded mutable-task phase-gate readiness, and documented replan-before-register ordering.\n''',
'''- Relaxed only the mechanical report envelope: token-first Markdown decoration, pure leading title headings, anchored suffix prose, and footer-safe/empty follow-up obligations are accepted without semantic inference. `# Verdict: PASS` remains invalid.\n- `advance` now quarantines an isolated deterministic control error for the current pass and continues unrelated authorized actions instead of letting one poisoned action jam the parent loop. Superseded mutable-task phase-gate readiness and replan-before-register ordering remain fixed.\n''')
