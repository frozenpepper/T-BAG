from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p=Path(path); text=p.read_text(encoding='utf-8')
    count=text.count(old)
    if count!=1:
        raise SystemExit(f'{path}: expected one tail anchor, found {count}: {old[:160]!r}')
    p.write_text(text.replace(old,new),encoding='utf-8')

# Keep old installer wording contracts while describing the new companion UI.
replace_once('scripts/install_harness_adapter.py',
'''The installer proves only project plugin files on disk; it cannot inspect the current OpenCode registry.''',
'''The installer proves only the project adapter file on disk plus companion presentation files; it cannot inspect the current OpenCode tool registry.''')

# Parent supervision must reject a stale observer whose owning adapter is gone and
# prefer a healthy observer when old/new parent sessions overlap briefly.
old='''def observer_for(registry:dict[str,Any], event_dir:str)->dict[str,Any]|None:
    target=str(Path(event_dir).resolve()) if event_dir else ""
    for item in registry.get("observers",[]) if isinstance(registry.get("observers"),list) else []:
        if not isinstance(item,dict): continue
        try: current=str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError: current=str(item.get("event_dir") or "")
        if current==target:
            pid=item.get("observer_pid")
            alive=False
            if isinstance(pid,int) and pid>0:
                try: os.kill(pid,0); alive=True
                except OSError: pass
            return {**item,"process_alive":alive,"healthy":bool(alive and not item.get("done"))}
    return None
'''
new='''def observer_for(registry:dict[str,Any], event_dir:str)->dict[str,Any]|None:
    target=str(Path(event_dir).resolve()) if event_dir else ""
    adapter_pid=registry.get("adapter_pid"); adapter_alive=False
    if isinstance(adapter_pid,int) and adapter_pid>0:
        try: os.kill(adapter_pid,0); adapter_alive=True
        except OSError: pass
    matches=[]
    for item in registry.get("observers",[]) if isinstance(registry.get("observers"),list) else []:
        if not isinstance(item,dict): continue
        try: current=str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError: current=str(item.get("event_dir") or "")
        if current!=target: continue
        pid=item.get("observer_pid"); alive=False
        if isinstance(pid,int) and pid>0:
            try: os.kill(pid,0); alive=True
            except OSError: pass
        matches.append({**item,"process_alive":alive,"adapter_alive":adapter_alive,"healthy":bool(alive and adapter_alive and not item.get("done") and not item.get("orphaned"))})
    if not matches: return None
    return next((x for x in reversed(matches) if x.get("healthy")),matches[-1])
'''
replace_once('scripts/parent_tick.py',old,new)

# Status UI uses the same health semantics and prefers the newest healthy binding.
replace_once('scripts/tbag_status.py',
'''            "transport_adapter_alive": adapter_alive,
        })''',
'''            "transport_adapter_alive": adapter_alive,
            "healthy": bool(adapter_alive and _pid_alive(observer_pid) and not item.get("done") and not item.get("orphaned")),
        })''')
old='''def _observer_for(transport: dict[str, Any], event_dir: str) -> dict[str, Any] | None:
    target = str(Path(event_dir).resolve()) if event_dir else ""
    for item in transport.get("observers", []):
        try:
            current = str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError:
            current = str(item.get("event_dir") or "")
        if target and current == target:
            healthy = bool(item.get("transport_adapter_alive") and item.get("observer_process_alive") and not item.get("done"))
            return {**item, "healthy": healthy}
    return None
'''
new='''def _observer_for(transport: dict[str, Any], event_dir: str) -> dict[str, Any] | None:
    target = str(Path(event_dir).resolve()) if event_dir else ""
    matches=[]
    for item in transport.get("observers", []):
        try:
            current = str(Path(str(item.get("event_dir") or "")).resolve())
        except OSError:
            current = str(item.get("event_dir") or "")
        if target and current == target:
            matches.append(item)
    if not matches: return None
    return next((x for x in reversed(matches) if x.get("healthy")),matches[-1])
'''
replace_once('scripts/tbag_status.py',old,new)

# Persist heartbeat freshness and mark observers owned by deleted parent sessions as
# orphaned instead of accidentally reporting them healthy to a successor parent.
replace_once('adapters/opencode/tbag.js',
'''      item.lastQueuedAt = Date.now()
      queueWake(ctx.client, item.sessionID)
''',
'''      item.lastQueuedAt = Date.now()
      persistTransport(item.run_root)
      queueWake(ctx.client, item.sessionID)
''')
replace_once('adapters/opencode/tbag.js',
'''    const affected = new Set()
    for (const [key, item] of runHeartbeats) if (item.sessionID === sessionID) { affected.add(item.run_root); runHeartbeats.delete(key) }
    for (const runRoot of affected) persistTransport(runRoot)
    return
''',
'''    const affected = new Set()
    for (const [key, item] of runHeartbeats) if (item.sessionID === sessionID) { affected.add(item.run_root); runHeartbeats.delete(key) }
    for (const item of follows.values()) if (item.sessionID === sessionID) { item.orphaned = true; affected.add(item.args?.run_root) }
    for (const runRoot of affected) if (runRoot) persistTransport(runRoot)
    return
''')
replace_once('adapters/opencode/tbag.js',
'''        observer_pid: item.proc?.pid, generation: item.generation, armed_at_ms: item.armedAt, done: item.done === true,
''',
'''        observer_pid: item.proc?.pid, generation: item.generation, armed_at_ms: item.armedAt, done: item.done === true, orphaned: item.orphaned === true,
''')
