#!/usr/bin/env python3
"""Resolve project views for T-BAG tasks and integrate mutable worktrees.

Mutating work gets an isolated task worktree. Independent read-only/result work normally
shares a frozen run-level analysis view and keeps only task-local report/session state. Git
provides isolation/history; T-BAG does not add checksum-chain orchestration.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dsd_task
from _contract import required_worktree_fixtures
from _roles import ALWAYS_READ_ONLY_ROLES

FORMAT = "dsd-task-workspace-v2.1"
ANALYSIS_VIEW_FORMAT = "tbag-analysis-view-v1"


def now() -> str: return datetime.now(timezone.utc).isoformat()


def run_cmd(cmd: list[str], cwd: Path, *, input_bytes: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(cmd, cwd=cwd, input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and cp.returncode != 0:
        raise ValueError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stderr.decode(errors='replace')[:1200]}")
    return cp


def git_text(cwd: Path, *args: str, check: bool = True) -> str:
    return run_cmd(["git", *args], cwd, check=check).stdout.decode("utf-8", errors="surrogateescape").strip()


def internal_git(run: Path, *args: str) -> list[str]:
    """Git command prefix for T-BAG-internal snapshot operations.

    Project hooks belong to the owner's normal Git workflow. T-BAG's temporary
    worktree/snapshot commits must not trigger arbitrary project pre/post hooks.
    Use a run-local empty hook directory rather than platform-specific /dev/null.
    """
    hooks=(run/"internal-git-hooks").resolve(); hooks.mkdir(parents=True,exist_ok=True)
    return ["git","-c",f"core.hooksPath={hooks}",*args]


def safe_component(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return out or "x"


def workspace_path(run: Path, phase: str, task: str) -> Path:
    return dsd_task.task_root(run, phase, task) / "workspace.json"


def load_workspace(run: Path, phase: str, task: str) -> dict[str, Any]:
    path = workspace_path(run, phase, task)
    if not path.is_file(): raise ValueError(f"workspace not created: {phase}/{task}")
    data = dsd_task.load_json(path)
    if data.get("format") != FORMAT: raise ValueError(f"unsupported workspace format: {data.get('format')!r}")
    return data




def analysis_views_root(run: Path) -> Path:
    info=dsd_task.load_run(run)
    return Path(info["runtime_root"]).resolve()/"analysis-views"


def analysis_view_index_path(run: Path) -> Path:
    return analysis_views_root(run)/"index.json"


def _load_analysis_view_index(run: Path) -> dict[str, Any]:
    path=analysis_view_index_path(run)
    if not path.is_file():
        return {"format":ANALYSIS_VIEW_FORMAT,"next_generation":1,"views":[],"current":None}
    data=dsd_task.load_json(path)
    if data.get("format")!=ANALYSIS_VIEW_FORMAT:
        raise ValueError(f"unsupported analysis-view index format: {data.get('format')!r}")
    data.setdefault("views",[]); data.setdefault("next_generation",1); data.setdefault("current",None)
    return data


def _write_analysis_view_index(run: Path, data: dict[str, Any]) -> None:
    dsd_task.write_json(analysis_view_index_path(run),data)


def _analysis_generation(path: Path) -> int | None:
    m=re.fullmatch(r"v(\d{4,})",path.name)
    return int(m.group(1)) if m else None


def _heal_analysis_view_index_unlocked(run: Path, primary: Path, index: dict[str, Any]) -> dict[str, Any]:
    """Reconcile disposable analysis-view metadata with the runtime filesystem.

    Analysis views are derived checkouts, never unique project authority. External cache
    deletion or an index reset must therefore repair itself instead of making the parent
    chmod/rm/prune Git internals by hand. Referenced orphan views are retained as stale
    generations so existing readers keep their frozen seat; unreferenced orphans are
    reclaimed and later readers get a fresh generation.
    """
    root=analysis_views_root(run); root.mkdir(parents=True,exist_ok=True)
    refs=_analysis_view_references(run); changed=False; kept=[]; listed=set(); max_generation=0
    current=str(index.get("current") or "")
    for raw in index.get("views",[]):
        if not isinstance(raw,dict):
            changed=True; continue
        item=dict(raw); path=Path(str(item.get("path") or "")).resolve(); generation=int(item.get("generation") or (_analysis_generation(path) or 0))
        max_generation=max(max_generation,generation); path_s=str(path)
        if path.is_dir():
            item["generation"]=generation or item.get("generation"); kept.append(item); listed.add(path_s); continue
        if path_s in refs:
            item["stale"]=True; item["stale_reason"]="referenced-analysis-view-path-missing"; item["stale_at"]=now(); kept.append(item); listed.add(path_s)
        else:
            changed=True
        if current==path_s:
            current=""; changed=True
    for path in sorted(root.glob("v*")):
        if not path.is_dir(): continue
        generation=_analysis_generation(path)
        if generation is None: continue
        max_generation=max(max_generation,generation); path_s=str(path.resolve())
        if path_s in listed: continue
        changed=True
        if path_s in refs:
            # The view is still owned by an existing read-only task. Preserve it but
            # never reuse it for a new reader because its missing index provenance
            # cannot prove freshness against current primary state.
            baseline=git_text(path,"rev-parse","HEAD",check=False)
            kept.append({"format":ANALYSIS_VIEW_FORMAT,"generation":generation,"path":path_s,"baseline_ref":baseline or None,"created_at":now(),"stale":True,"stale_reason":"recovered-orphan-analysis-view-index"})
        else:
            _make_tree_owner_writable(path)
            run_cmd(["git","worktree","remove","--force",path_s],primary,check=False)
            if path.exists(): shutil.rmtree(path,ignore_errors=True)
    # External deletion commonly leaves stale .git/worktrees registrations. Pruning is
    # safe here because view creation/GC holds the exclusive T-BAG workspace lock.
    run_cmd(["git","worktree","prune"],primary,check=False)
    next_generation=max(int(index.get("next_generation") or 1),max_generation+1)
    if next_generation!=int(index.get("next_generation") or 1): changed=True
    index={**index,"format":ANALYSIS_VIEW_FORMAT,"views":kept,"current":current or None,"next_generation":next_generation}
    if changed: _write_analysis_view_index(run,index)
    return index


def _make_tree_read_only(root: Path) -> None:
    # Cooperative guard: read-only roles should never author project state. Keep
    # execute bits where they already exist so scripts remain inspectable/runnable.
    for path in sorted(root.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        try:
            if path.is_symlink(): continue
            mode=path.stat().st_mode
            if path.is_dir(): path.chmod(mode & ~0o222)
            else: path.chmod(mode & ~0o222)
        except FileNotFoundError:
            pass
    mode=root.stat().st_mode; root.chmod(mode & ~0o222)


def _make_tree_owner_writable(root: Path) -> None:
    if not root.exists(): return
    for path in [root,*root.rglob("*")]:
        try:
            if path.is_symlink(): continue
            mode=path.stat().st_mode
            if path.is_dir(): path.chmod(mode | 0o700)
            else: path.chmod(mode | 0o600)
        except FileNotFoundError:
            pass


def _analysis_view_references(run: Path) -> set[str]:
    refs=set(); phases=run/"phases"
    for ws_path in phases.glob("*/tasks/*/workspace.json") if phases.is_dir() else []:
        try: ws=dsd_task.load_json(ws_path)
        except Exception: continue
        if ws.get("mode")!="analysis-view" or ws.get("released"): continue
        raw=ws.get("worktree")
        if isinstance(raw,str) and raw: refs.add(str(Path(raw).resolve()))
    return refs


def gc_analysis_views(run: Path, *, drop_current_if_unused: bool = False) -> list[str]:
    """Remove unreferenced shared analysis views.

    Normal opportunistic GC removes only stale generations so sequential Analysts can
    reuse one warm snapshot. Explicit phase housekeeping may also drop an unreferenced
    current generation to reclaim its checkout space.
    """
    with dsd_task.file_lock(run/".workspace.lock"):
        primary=Path(dsd_task.load_run(run)["project_root"]).resolve()
        index=_heal_analysis_view_index_unlocked(run,primary,_load_analysis_view_index(run)); refs=_analysis_view_references(run); removed=[]; kept=[]
        current=str(index.get("current") or "")
        for item in index.get("views",[]):
            if not isinstance(item,dict): continue
            path=Path(str(item.get("path") or "")).resolve()
            stale=bool(item.get("stale"))
            unused_current = drop_current_if_unused and str(path)==current and str(path) not in refs
            unused_fixture_variant = bool(item.get("fixture_bindings")) and str(path)!=current and str(path) not in refs
            if (stale and str(path) not in refs) or unused_current or unused_fixture_variant:
                _make_tree_owner_writable(path)
                run_cmd(["git","worktree","remove","--force",str(path)],primary,check=False)
                if path.exists(): shutil.rmtree(path,ignore_errors=True)
                removed.append(str(path)); continue
            kept.append(item)
        index["views"]=kept
        if current and current in removed: index["current"]=None
        _write_analysis_view_index(run,index)
        return removed


def _invalidate_analysis_view_unlocked(run: Path) -> None:
    index=_load_analysis_view_index(run)
    # More than one read-only view may coexist when their immutable fixture bindings
    # differ. Integration changes the project snapshot authority for every variant.
    for item in index.get("views",[]):
        if isinstance(item,dict) and not item.get("stale"):
            item["stale"]=True; item["stale_at"]=now()
    index["current"]=None; _write_analysis_view_index(run,index)


def invalidate_analysis_view(run: Path) -> None:
    """Mark the reusable read-only project view stale after primary integration."""
    with dsd_task.file_lock(run/".workspace.lock"):
        _invalidate_analysis_view_unlocked(run)


def _primary_view_marker(primary: Path) -> tuple[str, str]:
    """Cheaply describe primary Git state without content hashes.

    T-BAG integrations invalidate views directly. This marker additionally catches
    out-of-band commits and tracked dirty-state changes. Ambient untracked files are
    deliberately not part of a project view, so their creation/removal does not rotate
    the shared read-only generation. An external edit that changes only the contents
    of a tracked path that was already dirty still requires explicit
    ``invalidate-analysis-view``.
    """
    head=git_text(primary,"rev-parse","HEAD")
    status=git_text(primary,"status","--porcelain=v1","--untracked-files=no","--",".",":(exclude)TBag/**",":(exclude)AnalystAndGrunt/**")
    return head,status


def _view_matches_primary(item: dict[str, Any], run: Path, primary: Path) -> bool:
    current=integrated_primary_untracked_inputs(run,primary)
    current_paths={str(x.get("path") or "") for x in current if str(x.get("path") or "")}
    recorded=item.get("integrated_primary_inputs") if isinstance(item.get("integrated_primary_inputs"),list) else []
    recorded_paths={str(x.get("path") or "") for x in recorded if isinstance(x,dict) and str(x.get("path") or "")}
    if current_paths!=recorded_paths: return False
    view=Path(str(item.get("path") or ""))
    if not all(_same_primary_file(primary,view,rel) for rel in current_paths): return False
    baseline=str(item.get("baseline_ref") or "")
    if baseline and run_cmd(["git","rev-parse","--verify",baseline],primary,check=False).returncode==0:
        return _primary_matches_snapshot(primary,baseline,excluded_paths=sorted(current_paths))
    head,status=_primary_view_marker(primary)
    return item.get("primary_head")==head and item.get("primary_status")==status


def _fixture_binding_key(bindings: list[dict[str, Any]] | None) -> str:
    canonical=[]
    for item in bindings or []:
        canonical.append({
            "path":str(item.get("path") or ""),
            "fingerprint":str(item.get("fingerprint") or ""),
            "source_kind":str(item.get("source_kind") or ""),
        })
    return json.dumps(sorted(canonical,key=lambda x:(x["path"],x["fingerprint"])),sort_keys=True,separators=(",",":"))


def _analysis_view_bindings_match(item: dict[str, Any], bindings: list[dict[str, Any]]) -> bool:
    return str(item.get("fixture_binding_key") or _fixture_binding_key([]))==_fixture_binding_key(bindings)


def _bind_read_only_fixtures(view: Path, bindings: list[dict[str, Any]]) -> None:
    """Expose immutable fixture-store payloads inside one frozen analysis view."""
    for binding in bindings:
        rel=str(binding.get("path") or ""); source=Path(str(binding.get("store_payload") or "")).resolve(); dst=view/rel
        if not rel or not source.exists(): raise ValueError(f"read-only fixture binding is unavailable: {rel}")
        if dst.exists() or dst.is_symlink():
            if dst.is_symlink() and dst.resolve()==source: continue
            raise ValueError(f"analysis view fixture path collides with project state: {rel}")
        dst.parent.mkdir(parents=True,exist_ok=True); dst.symlink_to(source,target_is_directory=source.is_dir())


def acquire_analysis_view(run: Path, fixture_bindings: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return a reusable frozen project view for one immutable fixture-binding set."""
    requested=list(fixture_bindings or []); requested_key=_fixture_binding_key(requested)
    info=dsd_task.load_run(run); primary=Path(info["project_root"]).resolve()
    with dsd_task.file_lock(run/".workspace.lock", shared=True):
        index=_load_analysis_view_index(run); current=str(index.get("current") or "")
        for item in reversed(index.get("views",[])):
            path=Path(str(item.get("path") or "")) if isinstance(item,dict) else Path()
            if not isinstance(item,dict) or str(path.resolve())!=current or item.get("stale") or not _analysis_view_bindings_match(item,requested): continue
            if path.is_dir() and _view_matches_primary(item,run,primary): return dict(item)
    # Creation/reselection mutates shared view metadata, so serialize it against
    # integration and GC. Recheck after taking the exclusive lock.
    with dsd_task.file_lock(run/".workspace.lock"):
        index=_heal_analysis_view_index_unlocked(run,primary,_load_analysis_view_index(run))
        for item in reversed(index.get("views",[])):
            if not isinstance(item,dict) or item.get("stale") or not _analysis_view_bindings_match(item,requested): continue
            path=Path(str(item.get("path") or ""))
            if path.is_dir() and _view_matches_primary(item,run,primary):
                index["current"]=str(path.resolve()); _write_analysis_view_index(run,index); return dict(item)
            if not item.get("stale"):
                item["stale"]=True; item["stale_at"]=now(); item["stale_reason"]="primary-state-changed-outside-view"
        root=analysis_views_root(run); root.mkdir(parents=True,exist_ok=True)
        generation=int(index.get("next_generation") or 1); path=root/f"v{generation:04d}"
        if path.exists(): raise ValueError(f"analysis-view path already exists: {path}")
        try:
            run_cmd(internal_git(run,"worktree","add","--detach",str(path),"HEAD"),primary)
            if not path.is_dir(): raise ValueError(f"git worktree add reported success but did not materialize analysis view: {path}")
            patch=run_cmd(["git","diff","--binary","HEAD","--",".",":(exclude)TBag/**",":(exclude)AnalystAndGrunt/**"],primary).stdout
            if patch: run_cmd(["git","apply","--whitespace=nowarn","-"],path,input_bytes=patch)
            integrated_inputs=copy_integrated_primary_inputs(primary,path,integrated_primary_untracked_inputs(run,primary))
            run_cmd(["git","add","-A"],path)
            integrated_paths=[str(x.get("path") or "") for x in integrated_inputs if str(x.get("path") or "")]
            if integrated_paths: run_cmd(["git","add","-f","--",*integrated_paths],path)
            run_cmd(internal_git(run,"-c","user.name=TBag","-c","user.email=analyst-grunt@local","commit","--allow-empty","-m",f"T-BAG shared analysis view {generation}"),path)
            baseline=git_text(path,"rev-parse","HEAD")
            _bind_read_only_fixtures(path,requested)
            _make_tree_read_only(path)
            primary_head,primary_status=_primary_view_marker(primary)
            item={"format":ANALYSIS_VIEW_FORMAT,"generation":generation,"path":str(path.resolve()),"baseline_ref":baseline,"primary_head":primary_head,"primary_status":primary_status,"integrated_primary_inputs":integrated_inputs,"fixture_binding_key":requested_key,"fixture_bindings":requested,"created_at":now(),"stale":False}
            index["views"].append(item); index["current"]=str(path.resolve()); index["next_generation"]=generation+1; _write_analysis_view_index(run,index)
            return dict(item)
        except Exception:
            _make_tree_owner_writable(path)
            run_cmd(["git","worktree","remove","--force",str(path)],primary,check=False)
            if path.exists(): shutil.rmtree(path,ignore_errors=True)
            raise


def task_can_use_analysis_view(task: dict[str, Any], role: str, task_text: str, primary: Path | None = None) -> bool:
    if task.get("requires_integration"): return False
    if role not in ALWAYS_READ_ONLY_ROLES: return False
    fixtures=required_worktree_fixtures(task_text)
    if not fixtures: return True
    if primary is None: return False
    # Only dependency fixtures with a deterministic lockfile identity are safe to
    # share. Unknown/private fixtures retain the older isolated-copy path.
    return all(dependency_fixture_identity(primary,rel) is not None for rel in fixtures)

def prepare_launch_workspace(run: Path, phase: str, task_id: str, role: str) -> dict[str, Any]:
    """Resolve a stable project view for launch without over-allocating worktrees.

    Existing task worktrees always win: Reviewer/Analyst diagnosis of a mutating task
    must inspect that exact unintegrated state. New result-only/read-only tasks share a
    frozen analysis view; tasks that can mutate still receive their own worktree.
    """
    tid=dsd_task.slug(task_id); existing=workspace_path(run,phase,tid)
    if existing.is_file():
        bound=load_workspace(run,phase,tid)
        if bound.get("mode")!="analysis-view" or not bound.get("released"):
            return bound
        # Reusable read-only conduits (Plan/Context Reviewer) intentionally keep
        # their task record but release runtime state between fresh attempts.
        existing.unlink()
    task=dsd_task.load_task(run,phase,tid); brief=Path(str(task.get("brief") or "")).read_text(encoding="utf-8",errors="replace")
    info=dsd_task.load_run(run); primary=Path(info["project_root"]).resolve()
    if not task_can_use_analysis_view(task,role,brief,primary):
        class A: pass
        a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid
        return command_create(a)
    fixture_bindings=[]
    for rel in required_worktree_fixtures(brief):
        binding=ensure_dependency_fixture_store(run,primary,rel)
        if binding is None: raise ValueError(f"read-only fixture cannot be safely shared: {rel}")
        fixture_bindings.append(binding)
    view=acquire_analysis_view(run,fixture_bindings); runtime=Path(info["runtime_root"]).resolve(); db=runtime/"opencode-db"/safe_component(phase)/f"{safe_component(tid)}.sqlite"; db.parent.mkdir(parents=True,exist_ok=True)
    data={"format":FORMAT,"mode":"analysis-view","phase_id":phase,"task_id":tid,"primary_root":str(primary),"worktree":view["path"],"baseline_ref":view["baseline_ref"],"analysis_view_generation":view["generation"],"db":str(db),"fixture_mirrors":required_worktree_fixtures(brief),"fixture_bindings":fixture_bindings,"created_at":now(),"released":False}
    dsd_task.write_json(existing,data)
    task_path=dsd_task.task_file(run,phase,tid)
    with dsd_task.file_lock(task_path.with_suffix(".lock")):
        current=dsd_task.load_json(task_path); current["workspace"]=str(existing); current["updated_at"]=now(); dsd_task.write_json(task_path,current)
    return data

def integrated_primary_untracked_inputs(run: Path, primary: Path) -> list[dict[str, str]]:
    """Return current non-tracked project files established by any integrated T-BAG task.

    The primary working tree is T-BAG's integration line even when the owner has not
    committed it. Tracked primary changes are replayed from ``git diff HEAD``; this
    function supplies the complementary reviewed additions that Git still considers
    untracked/ignored. Dependency edges govern readiness, not whether already-integrated
    project state is physically visible in a later task view.
    """
    producers: dict[str, list[tuple[str, str, str]]] = {}
    phases=run/"phases"
    for state in sorted(phases.glob("*/tasks/*/task.json")) if phases.is_dir() else []:
        try: task=dsd_task.load_json(state)
        except Exception: continue
        if task.get("status")!="integrated": continue
        phase_id=str(task.get("phase_id") or state.parents[2].name)
        task_id=str(task.get("task_id") or state.parent.name)
        integrated_at=str(task.get("integrated_at") or "")
        for raw in task.get("integration_untracked_paths",[]) if isinstance(task.get("integration_untracked_paths"),list) else []:
            rel=str(raw).replace("\\","/").strip("/")
            if not rel: continue
            producers.setdefault(rel,[]).append((integrated_at,phase_id,task_id))
    out=[]
    for rel, history in sorted(producers.items()):
        source=primary/rel
        try: source.resolve().relative_to(primary.resolve())
        except ValueError: continue
        if not source.exists() and not source.is_symlink(): continue
        if _path_is_tracked(primary,rel): continue
        _,phase_id,task_id=sorted(history)[-1]
        out.append({"path":rel,"producer_phase":phase_id,"producer_task":task_id})
    return out


def _path_is_tracked(root: Path, rel: str) -> bool:
    return run_cmd(["git","ls-files","--error-unmatch","--",rel],root,check=False).returncode==0


def copy_integrated_primary_inputs(primary: Path, worktree: Path, inputs: list[dict[str, str]]) -> list[dict[str, str]]:
    copied=[]
    for item in inputs:
        rel=str(item.get("path") or ""); src=primary/rel; dst=worktree/rel
        if not rel or (not src.exists() and not src.is_symlink()): continue
        if dst.exists() or dst.is_symlink():
            # A committed/tracked baseline already has this path; normal Git snapshot
            # authority wins and no non-tracked overlay is needed.
            continue
        dst.parent.mkdir(parents=True,exist_ok=True)
        if src.is_symlink(): dst.symlink_to(src.readlink())
        elif src.is_dir(): shutil.copytree(src,dst,symlinks=True)
        else: shutil.copy2(src,dst)
        copied.append(dict(item))
    return copied


def _review_delta_paths(worktree: Path, base: str, reviewed_ref: str, *, fixture_prefixes: list[str] | None = None) -> tuple[list[str], list[str]]:
    raw=run_cmd(["git","diff","--name-status","-z",f"{base}..{reviewed_ref}","--",*_project_pathspec(fixture_prefixes=fixture_prefixes or [])],worktree).stdout
    changed=[]; added=[]; parts=raw.split(b"\0"); i=0
    while i < len(parts):
        status=parts[i].decode("utf-8",errors="surrogateescape") if parts[i] else ""; i+=1
        if not status: continue
        code=status[0]
        if code in {"R","C"}:
            if i+1>=len(parts): break
            old=parts[i].decode("utf-8",errors="surrogateescape"); new=parts[i+1].decode("utf-8",errors="surrogateescape"); i+=2
            changed.extend([old,new])
        else:
            if i>=len(parts): break
            rel=parts[i].decode("utf-8",errors="surrogateescape"); i+=1
            changed.append(rel)
            if code=="A": added.append(rel)
    return list(dict.fromkeys(changed)),list(dict.fromkeys(added))


def _known_untracked_producers(run: Path, phase: str, paths: list[str]) -> dict[str, list[str]]:
    wanted=set(paths); out={path:[] for path in paths}; phases=run/"phases"
    for state in sorted(phases.glob("*/tasks/*/task.json")) if phases.is_dir() else []:
        try: task=dsd_task.load_json(state)
        except Exception: continue
        if task.get("status")!="integrated": continue
        produced=set(str(x) for x in task.get("integration_untracked_paths",[]) if str(x))
        label=f"{task.get('phase_id') or state.parents[2].name}/{task.get('task_id') or state.parent.name}"
        for path in wanted & produced: out[path].append(label)
    return {path:ids for path,ids in out.items() if ids}



DEPENDENCY_LOCKFILES=("package-lock.json","npm-shrinkwrap.json","pnpm-lock.yaml","yarn.lock","bun.lock","bun.lockb")


def _validate_fixture_source(primary: Path, rel: str) -> Path:
    src=primary/rel
    if not src.exists() and not src.is_symlink():
        raise ValueError(f"required worktree fixture missing from primary checkout: {rel}")
    resolved=src.resolve()
    try: resolved.relative_to(primary.resolve())
    except ValueError as exc: raise ValueError(f"required worktree fixture symlink escapes primary checkout: {rel}") from exc
    if src.is_dir():
        for link in src.rglob("*"):
            if not link.is_symlink(): continue
            try: link.resolve().relative_to(primary.resolve())
            except ValueError as exc: raise ValueError(f"required worktree fixture contains symlink escaping primary checkout: {link.relative_to(primary)}") from exc
    return src


def _fixture_tree_is_self_contained(src: Path) -> bool:
    """Whether preserving symlinks keeps every dependency edge inside this fixture."""
    root=src.resolve()
    if src.is_symlink(): return False
    if not src.is_dir(): return True
    for link in src.rglob("*"):
        if not link.is_symlink(): continue
        try: link.resolve().relative_to(root)
        except ValueError: return False
    return True


def dependency_fixture_identity(primary: Path, rel: str) -> dict[str, Any] | None:
    """Return a deterministic identity for a shareable installed dependency tree.

    Today the optimized class is ``node_modules`` because package-manager lockfiles
    provide a cheap semantic identity without hashing gigabytes of dependencies. Other
    fixtures keep the conservative task-local copy behavior.
    """
    rel=rel.replace("\\","/").strip("/")
    if Path(rel).name!="node_modules": return None
    src=_validate_fixture_source(primary,rel)
    if not src.is_dir() or not _fixture_tree_is_self_contained(src): return None
    project_root=primary.resolve(); cursor=(primary/rel).parent.resolve(); lock_dir=None; lockfiles=[]
    while cursor==project_root or project_root in cursor.parents:
        found=[cursor/name for name in DEPENDENCY_LOCKFILES if (cursor/name).is_file()]
        if found:
            lock_dir=cursor; lockfiles=found; break
        if cursor==project_root: break
        cursor=cursor.parent
    if lock_dir is None: return None
    inputs=[]; descriptor=["tbag-dependency-fixture-v1",rel]
    for path in sorted(lockfiles,key=lambda x:x.name):
        rel_input=path.relative_to(project_root).as_posix(); oid=git_text(project_root,"hash-object","--no-filters",str(path))
        descriptor.extend([rel_input,oid]); inputs.append(rel_input)
    manifest=lock_dir/"package.json"
    if manifest.is_file():
        rel_input=manifest.relative_to(project_root).as_posix(); oid=git_text(project_root,"hash-object","--no-filters",str(manifest))
        descriptor.extend([rel_input,oid]); inputs.append(rel_input)
    # npm's hidden installation lock gives a stronger identity for the actual installed
    # tree when available, while other package managers still use their authoritative lock.
    installed=src/".package-lock.json"
    if installed.is_file():
        rel_input=f"{rel}/.package-lock.json"; oid=git_text(project_root,"hash-object","--no-filters",str(installed))
        descriptor.extend([rel_input,oid]); inputs.append(rel_input)
    payload="\0".join(descriptor).encode("utf-8")
    fingerprint=run_cmd(["git","hash-object","--stdin"],project_root,input_bytes=payload).stdout.decode("ascii",errors="replace").strip()
    if not fingerprint: raise ValueError(f"cannot derive Git identity for dependency fixture: {rel}")
    return {"path":rel,"fingerprint":fingerprint,"identity_inputs":inputs,"source_kind":"dependency-store"}


def fixture_store_root(run: Path) -> Path:
    runtime=Path(dsd_task.load_run(run)["runtime_root"]).resolve()
    return runtime/"fixture-store"


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file(): path.unlink(missing_ok=True)
    elif path.is_dir():
        _make_tree_owner_writable(path)
        shutil.rmtree(path)


def _clone_path(src: Path, dst: Path, *, writable: bool) -> str:
    """Clone with copy-on-write when supported; otherwise make one ordinary copy."""
    _remove_path(dst); dst.parent.mkdir(parents=True,exist_ok=True)
    mode="copy"
    cp=shutil.which("cp")
    commands=[]
    if cp and sys.platform=="darwin": commands=[[cp,"-cR",str(src),str(dst)]]
    elif cp and sys.platform.startswith("linux"): commands=[[cp,"-a","--reflink=always",str(src),str(dst)]]
    for cmd in commands:
        probe=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
        if probe.returncode==0:
            mode="cow"; break
        _remove_path(dst)
    if not dst.exists() and not dst.is_symlink():
        if src.is_dir(): shutil.copytree(src,dst,symlinks=True)
        else: shutil.copy2(src,dst,follow_symlinks=False)
    if writable: _make_tree_owner_writable(dst)
    else: _make_tree_read_only(dst) if dst.is_dir() else dst.chmod(dst.stat().st_mode & ~0o222)
    return mode


def ensure_dependency_fixture_store(run: Path, primary: Path, rel: str) -> dict[str, Any] | None:
    identity=dependency_fixture_identity(primary,rel)
    if identity is None: return None
    root=fixture_store_root(run); entry=root/identity["fingerprint"]; payload=entry/"payload"; manifest=entry/"manifest.json"
    with dsd_task.file_lock(run/".fixture.lock"):
        if payload.exists() and manifest.is_file():
            data=dsd_task.load_json(manifest)
            if data.get("fingerprint")==identity["fingerprint"] and data.get("path")==identity["path"]:
                return {**identity,"store_payload":str(payload.resolve()),"materialization":data.get("materialization")}
            raise ValueError(f"fixture-store identity collision: {entry}")
        root.mkdir(parents=True,exist_ok=True)
        tmp=Path(tempfile.mkdtemp(prefix=".fixture-build-",dir=root))
        try:
            built=tmp/"payload"; mode=_clone_path(_validate_fixture_source(primary,rel),built,writable=False)
            dsd_task.write_json(tmp/"manifest.json",{**identity,"materialization":mode,"created_at":now(),"source_primary":str(primary.resolve())})
            tmp.replace(entry)
        except Exception:
            if tmp.exists(): shutil.rmtree(tmp,ignore_errors=True)
            raise
    return {**identity,"store_payload":str(payload.resolve()),"materialization":mode}


def _copy_one_required_fixture(primary: Path, worktree: Path, rel: str) -> None:
    src=_validate_fixture_source(primary,rel); dst=worktree/rel
    _remove_path(dst); dst.parent.mkdir(parents=True,exist_ok=True)
    if src.is_symlink():
        resolved=src.resolve()
        if resolved.is_dir(): shutil.copytree(resolved,dst,symlinks=False)
        else: shutil.copy2(resolved,dst)
    elif src.is_dir(): shutil.copytree(src,dst,symlinks=False)
    else: shutil.copy2(src,dst)


def _materialize_mutable_fixture(binding: dict[str, Any], worktree: Path) -> str:
    rel=str(binding["path"]); source=Path(str(binding["store_payload"])).resolve(); dst=worktree/rel
    return _clone_path(source,dst,writable=True)


def gc_fixture_store(run: Path) -> list[str]:
    """Delete immutable fixture generations that no live room/view can still reach."""
    root=fixture_store_root(run)
    if not root.is_dir(): return []
    referenced=set(); phases=run/"phases"
    for ws_path in phases.glob("*/tasks/*/workspace.json") if phases.is_dir() else []:
        try: ws=dsd_task.load_json(ws_path)
        except Exception: continue
        if ws.get("released"): continue
        for item in ws.get("fixture_bindings",[]) if isinstance(ws.get("fixture_bindings"),list) else []:
            if isinstance(item,dict) and item.get("fingerprint"): referenced.add(str(item["fingerprint"]))
    try: index=_load_analysis_view_index(run)
    except Exception: index={"views":[]}
    for item in index.get("views",[]):
        if not isinstance(item,dict): continue
        path=Path(str(item.get("path") or ""))
        if not path.exists(): continue
        for binding in item.get("fixture_bindings",[]) if isinstance(item.get("fixture_bindings"),list) else []:
            if isinstance(binding,dict) and binding.get("fingerprint"): referenced.add(str(binding["fingerprint"]))
    removed=[]
    with dsd_task.file_lock(run/".fixture.lock"):
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".fixture-build-") or entry.name in referenced: continue
            _make_tree_owner_writable(entry)
            shutil.rmtree(entry); removed.append(str(entry))
    return removed


def copy_required_fixtures(primary: Path, worktree: Path, task_text: str) -> list[str]:
    """Conservatively copy explicitly declared fixtures from one trusted source."""
    copied=[]
    for rel in required_worktree_fixtures(task_text):
        _copy_one_required_fixture(primary,worktree,rel); copied.append(rel)
    return copied



def refresh_task_fixtures(run: Path, phase: str, task: str) -> list[str]:
    """Restore launcher-owned fixtures without destroying a task's new dependency state.

    Dependency-store bindings are reset only while the task lockfile identity still
    matches the frozen binding. If the worker changed its lockfile, its private
    dependency tree is left alone for the next worker/reviewer to inspect.
    """
    with dsd_task.file_lock(run/".workspace.lock", shared=True):
        ws=load_workspace(run,phase,task)
        if ws.get("mode","isolated-worktree")!="isolated-worktree": return []
        state=dsd_task.load_task(run,phase,task); brief=Path(str(state.get("brief") or "")).read_text(encoding="utf-8",errors="replace")
        wt=Path(ws["worktree"]).resolve(); refreshed=[]
        bindings={str(x.get("path") or ""):x for x in ws.get("fixture_bindings",[]) if isinstance(x,dict)} if isinstance(ws.get("fixture_bindings"),list) else {}
        snapshot=Path(str(ws.get("fixture_snapshot_root") or "")).resolve() if ws.get("fixture_snapshot_root") else None
        for rel in required_worktree_fixtures(brief):
            binding=bindings.get(rel)
            if binding and binding.get("source_kind")=="dependency-store":
                current=dependency_fixture_identity(wt,rel)
                if current is None or current.get("fingerprint")!=binding.get("fingerprint"):
                    continue
                _materialize_mutable_fixture(binding,wt); refreshed.append(rel); continue
            if snapshot is None: raise ValueError(f"fixture snapshot missing for non-shareable fixture: {rel}")
            _copy_one_required_fixture(snapshot,wt,rel); refreshed.append(rel)
        return refreshed

def _command_create_unlocked(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    info=dsd_task.load_run(run); task=dsd_task.load_task(run,phase,tid)
    existing=workspace_path(run,phase,tid); primary=Path(info["project_root"]).resolve(); runtime=Path(info["runtime_root"]).resolve()
    if existing.exists():
        bound=load_workspace(run,phase,tid)
        if bound.get("mode","isolated-worktree")=="isolated-worktree" and not Path(str(bound.get("worktree") or "")).is_dir():
            # RC34 and older could leave workspace.json behind after forced cleanup.
            # Rebuild only when the binding's branches are already gone; if any remain,
            # they may still protect task work and require explicit diagnosis.
            if dsd_task.task_has_live_attempt(task) or dsd_task.task_has_unresolved_attempt(task):
                raise ValueError("workspace record points to a missing worktree while an attempt is live/unresolved; reconcile before recreating it")
            branches=[str(bound.get("task_branch") or ""),str(bound.get("baseline_branch") or "")]
            surviving=[b for b in branches if b and run_cmd(["git","show-ref","--verify","--quiet",f"refs/heads/{b}"],primary,check=False).returncode==0]
            if surviving:
                raise ValueError(f"workspace record points to a missing worktree but task branch state still exists: {surviving}; do not rebuild over potentially recoverable work")
            existing.unlink(missing_ok=True)
            task_path=dsd_task.task_file(run,phase,tid)
            with dsd_task.file_lock(task_path.with_suffix(".lock")):
                current=dsd_task.load_json(task_path); current.pop("workspace",None); current["updated_at"]=now(); dsd_task.write_json(task_path,current)
        else:
            return bound
    if git_text(primary,"rev-parse","--is-inside-work-tree")!="true": raise ValueError("project must be a Git worktree")
    ns="/".join(["dsd",safe_component(info["run_id"]),safe_component(phase),safe_component(tid)])
    base_branch=ns+"-base"; task_branch=ns
    worktree=runtime/"worktrees"/safe_component(phase)/safe_component(tid); db=runtime/"opencode-db"/safe_component(phase)/f"{safe_component(tid)}.sqlite"
    if worktree.exists(): raise ValueError(f"runtime worktree path already exists: {worktree}")
    for branch in (base_branch,task_branch):
        if run_cmd(["git","show-ref","--verify","--quiet",f"refs/heads/{branch}"],primary,check=False).returncode==0:
            raise ValueError(f"T-BAG branch already exists: {branch}")
    worktree.parent.mkdir(parents=True,exist_ok=True); db.parent.mkdir(parents=True,exist_ok=True)
    try:
        run_cmd(["git","worktree","prune"],primary,check=False)
        run_cmd(internal_git(run,"worktree","add","-b",base_branch,str(worktree),"HEAD"),primary)
        if not worktree.is_dir(): raise ValueError(f"git worktree add reported success but did not materialize task worktree: {worktree}")
        patch=run_cmd(["git","diff","--binary","HEAD","--",".",":(exclude)TBag/**"],primary).stdout
        if patch:
            run_cmd(["git","apply","--whitespace=nowarn","-"],worktree,input_bytes=patch)
        task_text=Path(str(task.get("brief") or "")).read_text(encoding="utf-8",errors="replace")
        integrated_primary=copy_integrated_primary_inputs(primary,worktree,integrated_primary_untracked_inputs(run,primary))
        fixture_snapshot=dsd_task.task_root(run,phase,tid)/"fixture-snapshot"
        fixture_mirrors=required_worktree_fixtures(task_text); fixture_bindings=[]; snapshot_used=False
        for rel in fixture_mirrors:
            binding=ensure_dependency_fixture_store(run,primary,rel)
            if binding is not None:
                _materialize_mutable_fixture(binding,worktree); fixture_bindings.append(binding)
            else:
                _copy_one_required_fixture(primary,fixture_snapshot,rel); _copy_one_required_fixture(fixture_snapshot,worktree,rel); snapshot_used=True
        _stage_durable_project_state(worktree,fixture_prefixes=fixture_mirrors)
        # T-BAG-integrated non-tracked additions are reviewed project state, not ambient
        # ignored input. Force them into the task-local baseline so .gitignore cannot
        # make integrated primary state disappear from later checkpoints/reviews.
        integrated_paths=[str(x.get("path") or "") for x in integrated_primary if str(x.get("path") or "")]
        if integrated_paths: run_cmd(["git","add","-f","--",*integrated_paths],worktree)
        run_cmd(internal_git(run,"-c","user.name=TBag","-c","user.email=analyst-grunt@local","commit","--allow-empty","-m",f"Analyst-Grunt baseline {phase}/{tid}"),worktree)
        run_cmd(["git","branch",task_branch],worktree)
        run_cmd(internal_git(run,"switch",task_branch),worktree)
        carry_patch=Path(str(task.get("carry_forward_patch") or ""))
        carry_from=task.get("carry_from")
        if carry_from:
            if str(carry_patch) in {".",""} or not carry_patch.is_file():
                raise ValueError(f"replacement task {tid} declares carry_from {carry_from} but its frozen carry-forward patch is missing")
            check=run_cmd(["git","apply","--check",str(carry_patch)],worktree,check=False)
            if check.returncode!=0:
                evidence_path=dsd_task.task_root(run,phase,tid)/"workspace-carry-conflict.json"
                evidence={
                    "format":"dsd-workspace-carry-conflict-v1","task_id":tid,"phase_id":phase,"recorded_at":now(),
                    "carry_from":carry_from,"carry_forward_patch":str(carry_patch.resolve()),
                    "primary_head":git_text(primary,"rev-parse","HEAD"),
                    "git_apply_error":check.stderr.decode(errors="replace")[:4000],
                }
                dsd_task.write_json(evidence_path,evidence)
                task_path=dsd_task.task_file(run,phase,tid)
                with dsd_task.file_lock(task_path.with_suffix(".lock")):
                    current=dsd_task.load_json(task_path)
                    current["status"]="needs-analysis"
                    current["last_workspace_conflict"]={**evidence,"evidence":str(evidence_path.resolve())}
                    current["updated_at"]=now(); dsd_task.write_json(task_path,current)
                raise ValueError(
                    f"frozen carry_from delta from {carry_from} no longer applies cleanly to the replacement's current primary baseline; "
                    f"task routed to needs-analysis with evidence {evidence_path.resolve()}"
                )
            run_cmd(["git","apply",str(carry_patch)],worktree)
        primary_head,primary_status=_primary_view_marker(primary)
        data={
            "format":FORMAT,"mode":"isolated-worktree","phase_id":phase,"task_id":tid,"primary_root":str(primary),"worktree":str(worktree),
            "baseline_branch":base_branch,"task_branch":task_branch,"db":str(db),"fixture_mirrors":fixture_mirrors,"fixture_bindings":fixture_bindings,
            "integrated_primary_inputs":integrated_primary,
            "fixture_snapshot_root":str(fixture_snapshot.resolve()) if snapshot_used else None,"primary_head":primary_head,"primary_status":primary_status,"created_at":now(),
        }
        if carry_from:
            data["carry_from"]=carry_from; data["carry_forward_patch"]=str(carry_patch.resolve())
        dsd_task.write_json(existing,data)
        task_path=dsd_task.task_file(run,phase,tid)
        with dsd_task.file_lock(task_path.with_suffix(".lock")):
            current=dsd_task.load_json(task_path); current["workspace"]=str(existing); current["updated_at"]=now(); dsd_task.write_json(task_path,current)
        return data
    except Exception:
        run_cmd(["git","worktree","remove","--force",str(worktree)],primary,check=False)
        run_cmd(["git","worktree","prune"],primary,check=False)
        run_cmd(["git","branch","-D",task_branch],primary,check=False); run_cmd(["git","branch","-D",base_branch],primary,check=False)
        raise



def _workspace_fixture_prefixes(ws: dict[str, Any]) -> list[str]:
    raw=ws.get("fixture_mirrors") if isinstance(ws.get("fixture_mirrors"),list) else []
    return list(dict.fromkeys(str(x).replace("\\","/").strip("/") for x in raw if str(x).strip("/")))


def _project_pathspec(*, fixture_prefixes: list[str] | None = None, extra_excludes: list[str] | None = None) -> list[str]:
    """Git pathspec for durable project state, excluding launcher-owned inputs."""
    prefixes=["TBag","AnalystAndGrunt",*(fixture_prefixes or []),*(extra_excludes or [])]
    out=["."]
    for rel in list(dict.fromkeys(x.replace("\\","/").strip("/") for x in prefixes if x)):
        out.extend([f":(exclude){rel}",f":(exclude){rel}/**"] )
    return out


def _stage_durable_project_state(root: Path, *, fixture_prefixes: list[str] | None = None) -> None:
    """Stage project state while keeping launcher-owned fixture inputs out of Git."""
    run_cmd(["git","add","-A","--","."],root)
    for rel in ["TBag","AnalystAndGrunt",*(fixture_prefixes or [])]:
        run_cmd(["git","reset","-q","HEAD","--",rel],root,check=False)


def _primary_matches_snapshot(primary: Path, snapshot_ref: str, *, excluded_paths: list[str] | None = None) -> bool:
    """Compare frozen tracked project bytes with the current primary working tree."""
    if not snapshot_ref:
        return False
    cp=run_cmd(["git","diff","--quiet",snapshot_ref,"--",*_project_pathspec(extra_excludes=excluded_paths or [])],primary,check=False)
    return cp.returncode==0


def _workspace_tree_matches_baseline(ws: dict[str, Any]) -> bool:
    """Whether an isolated workspace contains no task-authored project delta."""
    wt=Path(str(ws.get("worktree") or ""))
    baseline=str(ws.get("baseline_branch") or ""); task_branch=str(ws.get("task_branch") or "")
    if not wt.is_dir() or not baseline or not task_branch: return False
    pathspec=_project_pathspec(fixture_prefixes=_workspace_fixture_prefixes(ws))
    status=git_text(wt,"status","--porcelain=v1","--untracked-files=all","--",*pathspec)
    if status: return False
    return run_cmd(["git","diff","--quiet",f"{baseline}..{task_branch}","--",*pathspec],wt,check=False).returncode==0


def _same_primary_file(primary: Path, worktree: Path, rel: str) -> bool:
    src=primary/rel; dst=worktree/rel
    if src.is_symlink() or dst.is_symlink():
        return src.is_symlink() and dst.is_symlink() and src.readlink()==dst.readlink()
    if not src.is_file() or not dst.is_file(): return False
    try: return src.read_bytes()==dst.read_bytes()
    except OSError: return False


def _workspace_primary_changed(run: Path, phase: str, task: dict[str, Any], ws: dict[str, Any]) -> tuple[bool,str]:
    primary=Path(str(ws.get("primary_root") or "")).resolve(); wt=Path(str(ws.get("worktree") or "")).resolve()
    if not primary.is_dir() or not wt.is_dir(): return False,"workspace-missing"
    desired=integrated_primary_untracked_inputs(run,primary)
    desired_paths={str(x.get("path") or "") for x in desired if str(x.get("path") or "")}
    copied=ws.get("integrated_primary_inputs") if isinstance(ws.get("integrated_primary_inputs"),list) else ws.get("dependency_untracked_inputs") if isinstance(ws.get("dependency_untracked_inputs"),list) else []
    copied_paths={str(x.get("path") or "") for x in copied if isinstance(x,dict) and str(x.get("path") or "")}
    if desired_paths!=copied_paths: return True,"integrated-primary-untracked-set-changed"
    for rel in sorted(desired_paths):
        if not _same_primary_file(primary,wt,rel): return True,"integrated-primary-untracked-content-changed"

    # Compare the baseline snapshot commit with the *current working tree bytes*.
    # HEAD/status markers cannot notice a second edit to a path that was already dirty.
    baseline=str(ws.get("baseline_branch") or "")
    if baseline and run_cmd(["git","rev-parse","--verify",baseline],primary,check=False).returncode==0:
        if not _primary_matches_snapshot(primary,baseline,excluded_paths=sorted(desired_paths)):
            return True,"primary-tracked-state-changed"
        return False,"current"

    # Legacy fallback for bindings whose baseline ref has already disappeared.
    head,status=_primary_view_marker(primary)
    old_head=str(ws.get("primary_head") or ""); old_status=ws.get("primary_status")
    if old_head and (head!=old_head or (isinstance(old_status,str) and status!=old_status)):
        return True,"primary-tracked-state-changed"
    return False,"current"


def refresh_clean_task_workspace(run: Path, phase: str, task_id: str) -> dict[str, Any]:
    """Recreate a stale isolated workspace only when it contains no task delta.

    A clean cold retry has no task state worth rebasing. Reusing the normal workspace
    constructor keeps primary snapshotting, dependency overlays and fixtures single-
    owned. Dirty/continued workspaces are retained and require an explicit decision.
    """
    tid=dsd_task.slug(task_id); path=workspace_path(run,phase,tid)
    if not path.is_file(): return {"refreshed":False,"reason":"no-workspace"}
    with dsd_task.file_lock(run/".workspace.lock"):
        ws=load_workspace(run,phase,tid)
        if ws.get("mode")!="isolated-worktree": return {"refreshed":False,"reason":"not-isolated"}
        task=dsd_task.load_task(run,phase,tid)
        if dsd_task.task_has_unresolved_attempt(task): return {"refreshed":False,"reason":"attempt-unresolved"}
        if not _workspace_tree_matches_baseline(ws):
            changed,primary_reason=_workspace_primary_changed(run,phase,task,ws)
            if changed:
                return {
                    "refreshed":False,
                    "reason":"task-delta-present-primary-changed",
                    "primary_change":primary_reason,
                    "workspace_primary_head":ws.get("primary_head"),
                    "current_primary_head":git_text(Path(ws["primary_root"]),"rev-parse","HEAD"),
                }
            return {"refreshed":False,"reason":"task-delta-present"}
        changed,reason=_workspace_primary_changed(run,phase,task,ws)
        if not changed: return {"refreshed":False,"reason":"current"}

        primary=Path(ws["primary_root"]).resolve(); wt=Path(ws["worktree"]).resolve()
        refresh_count=int(ws.get("refresh_count") or 0)+1
        run_cmd(["git","worktree","remove","--force",str(wt)],primary,check=False)
        run_cmd(["git","worktree","prune"],primary,check=False)
        run_cmd(["git","branch","-D",str(ws["task_branch"])],primary,check=False)
        run_cmd(["git","branch","-D",str(ws["baseline_branch"])],primary,check=False)
        path.unlink(missing_ok=True)

        class A: pass
        args=A(); args.run_root=run; args.phase_id=phase; args.task_id=tid
        fresh=_command_create_unlocked(args)
        fresh["refreshed_at"]=now(); fresh["refresh_count"]=refresh_count; fresh["refresh_reason"]=reason
        dsd_task.write_json(path,fresh)
        return {"refreshed":True,"reason":reason,"primary_head":fresh.get("primary_head"),"baseline_ref":git_text(Path(fresh["worktree"]),"rev-parse",str(fresh["baseline_branch"]))}

def command_create(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve()
    # Multiple independent snapshots may proceed together. Integration takes the
    # exclusive side of this lock, preventing snapshots from seeing a half-applied
    # primary patch without serializing worktree preparation behind other snapshots.
    with dsd_task.file_lock(run/".workspace.lock", shared=True):
        return _command_create_unlocked(args)


def command_checkpoint(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id); ws=load_workspace(run,phase,tid)
    if ws.get("mode","isolated-worktree")!="isolated-worktree": raise ValueError("shared analysis views are frozen and cannot receive task checkpoints")
    wt=Path(ws["worktree"]); label=safe_component(args.label); ref="/".join(["dsd-checkpoint", safe_component(dsd_task.load_run(run)["run_id"]), safe_component(phase), safe_component(tid), label])
    if run_cmd(["git","show-ref","--verify","--quiet",f"refs/heads/{ref}"],wt,check=False).returncode==0: raise ValueError(f"checkpoint already exists: {ref}")
    _stage_durable_project_state(wt,fixture_prefixes=_workspace_fixture_prefixes(ws))
    run_cmd(internal_git(run,"-c","user.name=TBag","-c","user.email=analyst-grunt@local","commit","--allow-empty","-m",f"Analyst-Grunt checkpoint {phase}/{tid} before {label}"),wt)
    run_cmd(["git","branch",ref,"HEAD"],wt)
    return {"task_id":tid,"checkpoint_ref":ref,"checkpoint_oid":git_text(wt,"rev-parse",ref),"worktree":str(wt)}


def _integration_review_authority(task: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return the exact Reviewer checkpoint authorized for integration.

    Normal integration authority is a fresh Reviewer PASS. A Human-targeted explicit
    acceptance may instead authorize the exact checkpoint from a recorded Reviewer
    FAIL/ESCALATE without rewriting that red semantic outcome. The Human decision is
    valid only while it still matches the current review and accepted-report record.
    """
    review=task.get("last_review") if isinstance(task.get("last_review"),dict) else {}
    ref=review.get("checkpoint_ref")
    if not isinstance(ref,str) or not ref:
        return None,None
    if review.get("outcome")=="pass":
        return ref,"reviewer-pass"
    human=task.get("human_acceptance") if isinstance(task.get("human_acceptance"),dict) else {}
    decision=str(human.get("decision") or "")
    if (
        review.get("outcome") in {"fail","escalate"}
        and human.get("review_outcome")==review.get("outcome")
        and str(human.get("review_report") or "")==str(review.get("report") or "")
        and str(human.get("review_checkpoint_ref") or "")==ref
        and decision
        and str(task.get("accepted_report") or "")==decision
        and Path(decision).is_file()
    ):
        return ref,"explicit-human-authority"
    return None,None


def _command_integrate_unlocked(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    task=dsd_task.load_task(run,phase,tid); ws=load_workspace(run,phase,tid)
    if ws.get("mode","isolated-worktree")!="isolated-worktree": raise ValueError("only isolated mutable task worktrees can be integrated")
    status=str(task.get("status") or "")
    reviewed_ref,acceptance_basis=_integration_review_authority(task)
    retrying_conflict=False
    if status=="needs-analysis":
        conflict=task.get("last_integration_conflict") or {}
        retrying_conflict=bool(
            conflict and reviewed_ref and conflict.get("reviewed_ref")==reviewed_ref
        )
    if status!="accepted" and not retrying_conflict:
        raise ValueError("task must be accepted before integration; a prior integration conflict is retryable only while the same reviewed checkpoint remains authoritative")
    if not task.get("requires_integration"):
        raise ValueError("task is marked as not requiring project integration")
    wt=Path(ws["worktree"]); primary=Path(ws["primary_root"])
    review=task.get("last_review") or {}
    if not reviewed_ref or not acceptance_basis:
        raise ValueError("accepted project-changing task has no integration authority: require a fresh Reviewer PASS or explicit Human acceptance of the exact red Reviewer checkpoint")
    if run_cmd(["git","show-ref","--verify","--quiet",f"refs/heads/{reviewed_ref}"],wt,check=False).returncode!=0:
        raise ValueError(f"review checkpoint ref is missing: {reviewed_ref}")
    fixture_prefixes=_workspace_fixture_prefixes(ws); durable_pathspec=_project_pathspec(fixture_prefixes=fixture_prefixes)
    if run_cmd(["git","diff","--quiet",f"{reviewed_ref}..{ws['task_branch']}","--",*durable_pathspec],wt,check=False).returncode!=0 or git_text(wt,"status","--porcelain=v1","--untracked-files=all","--",*durable_pathspec):
        raise ValueError("task worktree changed after the passing Review; obtain a fresh Reviewer PASS before integration")
    baseline=str(ws["baseline_branch"]); diff_base=baseline; rebased=False
    ancestor=run_cmd(["git","merge-base","--is-ancestor",baseline,reviewed_ref],wt,check=False)
    if ancestor.returncode==1:
        # A sanctioned/manual rebase can legitimately displace the original task
        # baseline. Only use merge-base fallback when that baseline was an empty
        # snapshot; otherwise it may encode pre-existing owner-dirty state and
        # reclassifying it as task work would be unsafe.
        parent=run_cmd(["git","rev-parse",f"{baseline}^"],wt,check=False)
        baseline_dirty = parent.returncode==0 and run_cmd(["git","diff","--quiet",f"{baseline}^..{baseline}","--",*durable_pathspec],wt,check=False).returncode!=0
        if baseline_dirty:
            raise ValueError("task was rebased after its baseline captured pre-existing primary changes; refusing to infer task delta because owner-dirty state could be re-integrated. Route a bounded Analyst integration recovery/rebase instead")
        primary_head=git_text(primary,"rev-parse","HEAD")
        merge=run_cmd(["git","merge-base",primary_head,reviewed_ref],wt,check=False)
        if merge.returncode!=0 or not merge.stdout.strip():
            raise ValueError("task baseline is no longer an ancestor of the reviewed checkpoint and no merge-base with current primary can be established")
        diff_base=merge.stdout.decode(errors="replace").strip(); rebased=True
    elif ancestor.returncode!=0:
        raise ValueError("cannot determine whether the reviewed checkpoint descends from the task baseline")
    integration_paths,added_paths=_review_delta_paths(wt,diff_base,reviewed_ref,fixture_prefixes=fixture_prefixes)
    patch=run_cmd(["git","diff","--binary",f"{diff_base}..{reviewed_ref}","--",*durable_pathspec],wt).stdout
    patch_path=dsd_task.task_root(run,phase,tid)/"accepted.patch"; patch_path.write_bytes(patch)
    already_applied=False
    if patch:
        cp=run_cmd(["git","apply","--check",str(patch_path)],primary,check=False)
        if cp.returncode!=0:
            # If the exact reviewed delta is already present in primary (including an
            # identical ambient/untracked addition), integration is already materially
            # satisfied. This is a Git proof, not a semantic guess or automatic merge.
            reverse=run_cmd(["git","apply","--reverse","--check",str(patch_path)],primary,check=False)
            already_applied=reverse.returncode==0
        if cp.returncode!=0 and not already_applied:
            # Preserve the exact conflict without mutating the reviewed task delta.
            # A purely primary-tree precondition may be fixed and this same reviewed
            # ref retried; semantic/merge conflicts still require Analyst diagnosis.
            evidence_path=dsd_task.task_root(run,phase,tid)/"integration-conflict.json"
            untracked_collisions=[
                path for path in added_paths
                if ((primary/path).exists() or (primary/path).is_symlink()) and not _path_is_tracked(primary,path)
            ]
            producers=_known_untracked_producers(run,phase,untracked_collisions)
            conflict_kind="divergent-untracked-authority" if untracked_collisions else "git-apply-conflict"
            conflict={
                "format":"dsd-integration-conflict-v1",
                "task_id":tid,"phase_id":phase,"recorded_at":now(),
                "kind":conflict_kind,
                "primary_head":git_text(primary,"rev-parse","HEAD"),
                "reviewed_ref":reviewed_ref,"diff_base":diff_base,"patch":str(patch_path),
                "changed_paths":integration_paths,"untracked_collisions":untracked_collisions,
                "known_tbag_producers":producers,
                "git_apply_error":cp.stderr.decode(errors="replace")[:4000],
            }
            dsd_task.write_json(evidence_path,conflict)
            task_path=dsd_task.task_file(run,phase,tid)
            with dsd_task.file_lock(task_path.with_suffix(".lock")):
                current=dsd_task.load_json(task_path)
                current["status"]="needs-analysis"
                current["last_integration_conflict"]={**conflict,"evidence":str(evidence_path.resolve())}
                current["updated_at"]=now(); dsd_task.write_json(task_path,current)
            return {
                "task_id":tid,"integrated":False,"changed":False,"integration_conflict":True,
                "status":"needs-analysis","next_action":"diagnose-or-fix-primary-precondition-then-retry-integrate",
                "acceptance_preserved":True,"reviewed_ref":reviewed_ref,
                "evidence":str(evidence_path.resolve()),"patch":str(patch_path),
                "diff_base":diff_base,"rebased_baseline_fallback":rebased,
            }
        if not already_applied:
            run_cmd(["git","apply",str(patch_path)],primary)
        # Git apply is normally atomic, but integration is an authority boundary: do
        # not assert ``integrated`` until Git can prove the complete reviewed patch is
        # materially present in primary, including newly added ignored files.
        materialized=run_cmd(["git","apply","--reverse","--check",str(patch_path)],primary,check=False)
        if materialized.returncode!=0:
            evidence_path=dsd_task.task_root(run,phase,tid)/"integration-conflict.json"
            conflict={
                "format":"dsd-integration-conflict-v1",
                "task_id":tid,"phase_id":phase,"recorded_at":now(),
                "kind":"integration-materialization-mismatch",
                "primary_head":git_text(primary,"rev-parse","HEAD"),
                "reviewed_ref":reviewed_ref,"diff_base":diff_base,"patch":str(patch_path),
                "changed_paths":integration_paths,
                "git_reverse_check_error":materialized.stderr.decode(errors="replace")[:4000],
            }
            dsd_task.write_json(evidence_path,conflict)
            task_path=dsd_task.task_file(run,phase,tid)
            with dsd_task.file_lock(task_path.with_suffix(".lock")):
                current=dsd_task.load_json(task_path)
                current["status"]="needs-analysis"
                current["last_integration_conflict"]={**conflict,"evidence":str(evidence_path.resolve())}
                current["updated_at"]=now(); dsd_task.write_json(task_path,current)
            return {
                "task_id":tid,"integrated":False,"changed":True,"integration_conflict":True,
                "status":"needs-analysis","next_action":"inspect-incomplete-primary-materialization",
                "acceptance_preserved":True,"reviewed_ref":reviewed_ref,
                "evidence":str(evidence_path.resolve()),"patch":str(patch_path),
            }
    # A failed apply must not consume an unchanged Reviewer PASS. If this is a
    # direct retry after the primary-tree precondition was repaired, restore the
    # accepted lifecycle state only after the exact reviewed patch applies.
    if retrying_conflict:
        task_path=dsd_task.task_file(run,phase,tid)
        with dsd_task.file_lock(task_path.with_suffix(".lock")):
            current=dsd_task.load_json(task_path)
            conflict=current.get("last_integration_conflict") or {}
            current_ref,current_basis=_integration_review_authority(current)
            if current.get("status")!="needs-analysis" or not current_ref or conflict.get("reviewed_ref")!=current_ref:
                raise ValueError("integration retry authority changed while applying the patch; reconcile before continuing")
            current["status"]="accepted"; current["updated_at"]=now(); dsd_task.write_json(task_path,current)
            acceptance_basis=current_basis
    # Mark integrated only after primary apply succeeds. Record which reviewed paths
    # remain non-tracked in primary so every later T-BAG view can reconstruct the full
    # integrated primary state without importing unrelated ambient untracked files.
    integrated_untracked=[
        path for path in integration_paths
        if ((primary/path).exists() or (primary/path).is_symlink()) and not _path_is_tracked(primary,path)
    ]
    class A: pass
    a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.integration_paths=integration_paths; a.integration_untracked_paths=integrated_untracked
    result=dsd_task.command_integrated(a)
    # Successful integration output is intentionally tiny; detailed provenance remains
    # in task/workspace state and accepted.patch. Emit exceptional mechanics only when
    # they actually occurred.
    result["changed"]=bool(patch) and not already_applied
    if already_applied: result["already_applied"]=True
    if rebased: result["rebased_baseline_fallback"]=True
    if retrying_conflict: result["retried_prior_integration_conflict"]=True
    if acceptance_basis=="explicit-human-authority": result["acceptance_basis"]=acceptance_basis
    return result


def _prepare_review_pass_for_integration(args: argparse.Namespace) -> dict[str, Any]:
    """Collapse the routine Reviewer-PASS -> accept prelude into integration.

    The parent still supplies the semantic PASS explicitly by choosing
    ``--review-pass-report``. T-BAG only performs the deterministic lifecycle steps
    that always follow that decision. If a later integration conflict occurs, the
    recorded Reviewer PASS remains authoritative under the existing retry rules.
    """
    raw=getattr(args,"review_pass_report",None)
    if raw is None: return
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id); report=Path(raw).resolve()
    task=dsd_task.load_task(run,phase,tid); status=str(task.get("status") or "")
    review_recorded=False; accepted=False
    if status=="awaiting-review":
        class R: pass
        r=R(); r.run_root=run; r.phase_id=phase; r.task_id=tid; r.outcome="pass"; r.report=report
        dsd_task.command_review(r); review_recorded=True
        task=dsd_task.load_task(run,phase,tid); status=str(task.get("status") or "")
    else:
        review=task.get("last_review") if isinstance(task.get("last_review"),dict) else {}
        if review.get("outcome")!="pass" or str(Path(str(review.get("report") or "")).resolve())!=str(report):
            raise ValueError("--review-pass-report must name the current gated/passing Reviewer report for this task")
    if status=="review-passed":
        class A: pass
        a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.report=report
        dsd_task.command_accept(a); accepted=True
    elif status not in {"accepted","needs-analysis"}:
        raise ValueError(f"cannot land Reviewer PASS from task status {status!r}")
    return


def command_integrate(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve()
    _prepare_review_pass_for_integration(args)
    # Integration and retirement share one exclusive workspace boundary. Once Git has
    # proved the exact reviewed patch is materialized in primary, the task worktree is
    # no longer unique authority and should disappear immediately.
    with dsd_task.file_lock(run/".workspace.lock"):
        result=_command_integrate_unlocked(args)
        if result.get("status")=="integrated":
            _invalidate_analysis_view_unlocked(run)
            class C: pass
            c=C(); c.run_root=run; c.phase_id=args.phase_id; c.task_id=args.task_id; c.force=False; c.reason=None
            try:
                cleaned=_command_cleanup_unlocked(c)
                result["runtime_cleaned"]=bool(cleaned.get("cleaned"))
            except (OSError,ValueError) as exc:
                # Integration is already durable. Cleanup failure must never roll back or
                # obscure that semantic success; normal reconcile will retry the reaper.
                result["runtime_cleanup_deferred"]=str(exc)[:800]
    if result.get("status")=="integrated": gc_analysis_views(run)
    return result


def live_attempt_exists(task: dict[str,Any]) -> bool:
    # Cleanup is destructive: an attempt without a terminal event is unresolved even
    # when its monitor died. Preserve its worktree/evidence for Recovery.
    return dsd_task.task_has_unresolved_attempt(task)


def _owned_cleanup_targets(run: Path, phase: str, tid: str, ws: dict[str, Any]) -> tuple[Path,Path,Path,str,str]:
    """Validate every destructive target against exact run-owned derivation."""
    info=dsd_task.load_run(run); primary=Path(str(info["project_root"])).resolve(); runtime=Path(str(info["runtime_root"])).resolve()
    if Path(str(ws.get("primary_root") or "")).resolve()!=primary:
        raise ValueError("workspace primary_root no longer matches this run; refusing automatic cleanup")
    expected_db=(runtime/"opencode-db"/safe_component(phase)/f"{safe_component(tid)}.sqlite").resolve()
    db=Path(str(ws.get("db") or "")).resolve()
    if db!=expected_db:
        raise ValueError(f"workspace DB is outside its exact run-owned location; refusing cleanup: {db}")
    ns="/".join(["dsd",safe_component(info["run_id"]),safe_component(phase),safe_component(tid)])
    task_branch=ns; baseline_branch=ns+"-base"
    mode=str(ws.get("mode") or "isolated-worktree")
    wt=Path(str(ws.get("worktree") or "")).resolve()
    if mode=="isolated-worktree":
        expected_wt=(runtime/"worktrees"/safe_component(phase)/safe_component(tid)).resolve()
        if wt!=expected_wt:
            raise ValueError(f"workspace path is outside its exact run-owned location; refusing cleanup: {wt}")
        if str(ws.get("task_branch") or "")!=task_branch or str(ws.get("baseline_branch") or "")!=baseline_branch:
            raise ValueError("workspace branch identity does not match this run/task; refusing cleanup")
    elif mode=="analysis-view":
        try: wt.relative_to((runtime/"analysis-views").resolve())
        except ValueError as exc: raise ValueError(f"analysis view escapes this run runtime; refusing cleanup: {wt}") from exc
    return primary,wt,db,task_branch,baseline_branch


def _command_cleanup_unlocked(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id); tid=dsd_task.slug(args.task_id)
    task=dsd_task.load_task(run,phase,tid)
    ws_path=workspace_path(run,phase,tid)
    if not ws_path.is_file() and task.get("workspace_cleaned_at"):
        return {"task_id":tid,"cleaned":False,"already_cleaned":True,"reason":task.get("workspace_cleanup_reason")}
    ws=load_workspace(run,phase,tid)
    if live_attempt_exists(task): raise ValueError("task still has a live/unresolved worker attempt; refusing cleanup")
    mode=str(ws.get("mode") or "isolated-worktree"); status=str(task.get("status") or "")
    if mode=="analysis-view" and ws.get("released") and task.get("workspace_cleaned_at"):
        return {"task_id":tid,"cleaned":False,"already_cleaned":True,"reason":task.get("workspace_cleanup_reason")}
    force=bool(getattr(args,"force",False)); explicit_reason=str(getattr(args,"reason",None) or "").strip()

    retention=None
    if status=="superseded" and mode=="isolated-worktree":
        retention=dsd_task.superseded_workspace_retention(run,phase,task)
        if retention.get("retain"):
            raise ValueError(
                "superseded workspace still contains an unintegrated delta with no durable disposition; refusing cleanup. "
                f"reason={retention.get('reason')} changed_paths={retention.get('changed_paths',[])[:8]}"
            )
    if force and not explicit_reason:
        raise ValueError("--force cleanup requires --reason so discarded workspace authority is auditable")
    if task.get("requires_integration") and status not in {"integrated","superseded"} and not force:
        raise ValueError("project-changing task is not integrated; refusing to delete the worktree needed for integration")
    if status not in {"integrated","accepted","superseded"} and not force:
        raise ValueError(f"task status {status!r} is not complete; use --force --reason only for explicit abandonment/recovery")

    if force:
        cleanup_reason=f"explicit-discard:{explicit_reason}"
    elif status=="integrated":
        cleanup_reason="reviewed-delta-integrated"
    elif status=="accepted":
        cleanup_reason="durable-nonintegrating-result"
    elif retention is not None:
        cleanup_reason=str(retention.get("reason") or "superseded-safe")
    else:
        cleanup_reason="superseded-no-runtime-authority"

    primary,wt,db,task_branch,baseline_branch=_owned_cleanup_targets(run,phase,tid,ws)
    if mode=="isolated-worktree":
        run_cmd(["git","worktree","remove","--force",str(wt)],primary,check=False)
        if wt.exists():
            raise ValueError(f"Git worktree removal did not reclaim {wt}; refusing to delete branch authority underneath it")
        all_refs=git_text(primary,"for-each-ref","--format=%(refname:short)","refs/heads").splitlines()
        checkpoint_prefix="/".join(["dsd-checkpoint", safe_component(dsd_task.load_run(run)["run_id"]), safe_component(phase), safe_component(tid)])+"/"
        for ref in all_refs:
            if ref==ws["task_branch"] or ref.startswith(checkpoint_prefix):
                run_cmd(["git","branch","-D",ref],primary,check=False)
        run_cmd(["git","branch","-D",task_branch],primary,check=False)
        run_cmd(["git","branch","-D",baseline_branch],primary,check=False)
        workspace_path(run,phase,tid).unlink(missing_ok=True)
    elif mode=="analysis-view":
        ws["released"]=True; ws["released_at"]=now(); ws["release_reason"]=cleanup_reason; dsd_task.write_json(workspace_path(run,phase,tid),ws)
    else:
        raise ValueError(f"unsupported workspace mode: {mode!r}")

    # Fixture snapshots and worker CLI DBs are launcher-owned derived state. Once the
    # workspace disposition is durable they are not project authority and must not
    # accumulate for hours/days.
    fixture_root=Path(str(ws.get("fixture_snapshot_root") or "")) if ws.get("fixture_snapshot_root") else None
    if fixture_root is not None:
        try: fixture_root.resolve().relative_to(dsd_task.task_root(run,phase,tid).resolve())
        except ValueError: raise ValueError(f"refusing to delete fixture snapshot outside task root: {fixture_root}")
        if fixture_root.exists(): shutil.rmtree(fixture_root)
    for candidate in (db,Path(str(db)+"-wal"),Path(str(db)+"-shm")):
        candidate.unlink(missing_ok=True)

    task_path=dsd_task.task_file(run,phase,tid)
    with dsd_task.file_lock(task_path.with_suffix(".lock")):
        current=dsd_task.load_json(task_path); current.pop("workspace",None)
        current["workspace_cleaned_at"]=now(); current["workspace_cleanup_reason"]=cleanup_reason; current["updated_at"]=now()
        if force:
            current["workspace_disposition"]={"mode":"discarded","reason":explicit_reason,"recorded_at":current["workspace_cleaned_at"]}
        dsd_task.write_json(task_path,current)
    return {"task_id":tid,"cleaned":True,"mode":mode,"reason":cleanup_reason}


def command_cleanup(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve()
    with dsd_task.file_lock(run/".workspace.lock"):
        return _command_cleanup_unlocked(args)




def _reclaim_failed_setup_without_workspace(run: Path, phase: str, task: dict[str, Any], primary: Path, runtime: Path) -> list[str]:
    """Reclaim exact T-BAG setup residue for never-launched tasks.

    A failed ``git worktree add -b`` can create the task baseline branch before
    checkout fails.  If no workspace record or attempt was ever created, those
    exact run/task names are safe setup residue rather than durable task work.
    """
    status=str(task.get("status") or "")
    attempts=[a for a in task.get("attempts",[]) if isinstance(a,dict)]
    if status not in {"planned","ready"} or attempts:
        return []
    tid=dsd_task.slug(str(task.get("task_id") or ""))
    info=dsd_task.load_run(run)
    ns="/".join(["dsd",safe_component(info["run_id"]),safe_component(phase),safe_component(tid)])
    branches=[ns,ns+"-base"]
    expected=runtime/"worktrees"/safe_component(phase)/safe_component(tid)
    run_cmd(["git","worktree","remove","--force",str(expected)],primary,check=False)
    if expected.exists(): shutil.rmtree(expected,ignore_errors=True)
    run_cmd(["git","worktree","prune"],primary,check=False)
    removed=[]
    for branch in branches:
        if run_cmd(["git","show-ref","--verify","--quiet",f"refs/heads/{branch}"],primary,check=False).returncode==0:
            cp=run_cmd(["git","branch","-D",branch],primary,check=False)
            if cp.returncode==0: removed.append(branch)
    db=runtime/"opencode-db"/safe_component(phase)/f"{safe_component(tid)}.sqlite"
    for path in (db,Path(str(db)+"-wal"),Path(str(db)+"-shm")):
        path.unlink(missing_ok=True)
    return removed

def _gc_orphan_task_databases(run: Path) -> list[str]:
    """Delete run-owned worker DBs that no live workspace still references."""
    info=dsd_task.load_run(run); runtime=Path(info["runtime_root"]).resolve(); db_root=runtime/"opencode-db"
    if not db_root.is_dir(): return []
    referenced=set(); phases=run/"phases"
    for ws_path in phases.glob("*/tasks/*/workspace.json") if phases.is_dir() else []:
        try: ws=dsd_task.load_json(ws_path)
        except Exception: continue
        if ws.get("released"): continue
        raw=ws.get("db")
        if isinstance(raw,str) and raw: referenced.add(str(Path(raw).resolve()))
    removed=[]
    bases=set(db_root.rglob("*.sqlite"))
    for sidecar in [*db_root.rglob("*.sqlite-wal"),*db_root.rglob("*.sqlite-shm")]:
        name=sidecar.name[:-4]
        bases.add(sidecar.with_name(name))
    for base in sorted(bases):
        if str(base.resolve()) in referenced: continue
        for candidate in (base,Path(str(base)+"-wal"),Path(str(base)+"-shm")):
            if candidate.exists(): candidate.unlink(missing_ok=True); removed.append(str(candidate))
    return removed


def _prune_empty_runtime_dirs(root: Path) -> None:
    if not root.is_dir(): return
    for path in sorted((p for p in root.rglob("*") if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        try: path.rmdir()
        except OSError: pass


def reap_safe_runtime(run: Path, *, phase_id: str | None = None, drop_current_analysis: bool = False) -> dict[str, Any]:
    """Reclaim every mechanically disposable run resource without parent bookkeeping."""
    run=run.resolve(); info=dsd_task.load_run(run); primary=Path(info["project_root"]).resolve(); runtime=Path(info["runtime_root"]).resolve()
    phases_root=run/"phases"
    phases=[dsd_task.slug(phase_id)] if phase_id else sorted(p.name for p in phases_root.iterdir() if p.is_dir()) if phases_root.is_dir() else []
    cleaned=[]; skipped=[]; orphan_setup=[]
    for phase in phases:
        tasks_dir=dsd_task.phase_root(run,phase)/"tasks"
        for state_path in sorted(tasks_dir.glob("*/task.json")) if tasks_dir.is_dir() else []:
            task=dsd_task.load_json(state_path); tid=str(task.get("task_id") or state_path.parent.name)
            ws_path=workspace_path(run,phase,tid)
            if not ws_path.is_file():
                removed=_reclaim_failed_setup_without_workspace(run,phase,task,primary,runtime)
                orphan_setup.extend({"task_id":tid,"branch":ref} for ref in removed)
                continue
            if live_attempt_exists(task):
                skipped.append({"phase_id":phase,"task_id":tid,"reason":"live-attempt"}); continue
            status=str(task.get("status") or "")
            complete=status in {"integrated","superseded"} or (status=="accepted" and not task.get("requires_integration"))
            if not complete:
                skipped.append({"phase_id":phase,"task_id":tid,"reason":f"status:{status}"}); continue
            class A: pass
            a=A(); a.run_root=run; a.phase_id=phase; a.task_id=tid; a.force=False; a.reason=None
            try:
                command_cleanup(a); cleaned.append({"phase_id":phase,"task_id":tid})
            except (OSError,ValueError) as exc:
                skipped.append({"phase_id":phase,"task_id":tid,"reason":str(exc)[:500]})
    removed_dbs=_gc_orphan_task_databases(run)
    removed_views=gc_analysis_views(run,drop_current_if_unused=drop_current_analysis)
    gc_fixture_store(run)
    _prune_empty_runtime_dirs(runtime/"worktrees"); _prune_empty_runtime_dirs(runtime/"opencode-db")
    return {"cleaned":cleaned,"skipped":skipped,"orphan_setup_branches_removed":orphan_setup,"orphan_databases_removed":removed_dbs,"analysis_views_removed":removed_views}


def command_cleanup_phase(args: argparse.Namespace) -> dict[str, Any]:
    run=args.run_root.resolve(); phase=dsd_task.slug(args.phase_id)
    result=reap_safe_runtime(run,phase_id=phase,drop_current_analysis=True)
    return {"phase_id":phase,**result,"cleaned":[str(x.get("task_id")) for x in result.get("cleaned",[]) if x.get("task_id")]}


def _purge_run_blockers(run: Path) -> list[dict[str, str]]:
    """Return reasons this run's runtime cache is not yet safe to reclaim.

    This deliberately mirrors ordinary cleanup safety instead of inventing a second
    notion of "merged". A completed run should have no live attempts, no unresolved
    carry-forward source, and no project-changing task still awaiting integration.
    """
    blockers=[]; phases=run/"phases"
    for state_path in sorted(phases.glob("*/tasks/*/task.json")) if phases.is_dir() else []:
        task=dsd_task.load_json(state_path); phase=state_path.parents[2].name; tid=str(task.get("task_id") or state_path.parent.name)
        if live_attempt_exists(task):
            blockers.append({"phase_id":phase,"task_id":tid,"reason":"live-attempt"}); continue
        ws_path=workspace_path(run,phase,tid)
        if not ws_path.is_file(): continue
        status=str(task.get("status") or "")
        if status=="superseded":
            retention=dsd_task.superseded_workspace_retention(run,phase,task)
            if retention.get("retain"):
                blockers.append({"phase_id":phase,"task_id":tid,"reason":"superseded-carry-forward-not-durable"}); continue
        if task.get("requires_integration") and status not in {"integrated","superseded"}:
            blockers.append({"phase_id":phase,"task_id":tid,"reason":f"project-change-not-integrated:{status}"}); continue
        if status not in {"integrated","accepted","superseded"}:
            blockers.append({"phase_id":phase,"task_id":tid,"reason":f"task-not-complete:{status}"})
    return blockers


def command_purge_run(args: argparse.Namespace) -> dict[str, Any]:
    """Reclaim only this completed run's runtime/cache subtree.

    The caller supplies a run root, never a filesystem deletion target. The target is
    resolved exclusively from run.json and must carry the matching ownership marker.
    Durable run state under PROJECT/TBag is intentionally preserved.
    """
    run=args.run_root.resolve(); info=dsd_task.load_run(run); status=str(info.get("status") or "active")
    runtime=Path(str(info["runtime_root"])).resolve(); project=Path(str(info["project_root"])).resolve()
    protected={Path.home().resolve(),project,run,Path(tempfile.gettempdir()).resolve()}
    shared=(Path.home()/".cache"/dsd_task.CACHE_DIR).resolve(); protected.update({shared,(shared/"projects").resolve()})
    if runtime==Path(runtime.anchor): raise ValueError(f"unsafe runtime_root for purge-run: {runtime}")
    for root in protected:
        if runtime==root: raise ValueError(f"unsafe runtime_root for purge-run: {runtime}")
        try: root.relative_to(runtime)
        except ValueError: pass
        else: raise ValueError(f"unsafe runtime_root contains protected/shared state: {runtime}")
    marker=runtime/".tbag-run-owner.json"
    if not marker.is_file():
        raise ValueError(f"runtime ownership marker missing; refusing destructive purge: {marker}. For an upgraded legacy run using T-BAG's canonical per-project/per-run cache path, rerun idempotent init-run once to backfill ownership; legacy custom runtime roots are never auto-claimed")
    owner=dsd_task.load_json(marker)
    if owner.get("format")!="tbag-runtime-owner-v1" or owner.get("run_id")!=info.get("run_id") or Path(str(owner.get("run_root") or "")).resolve()!=run or Path(str(owner.get("project_root") or "")).resolve()!=project:
        raise ValueError("runtime ownership marker does not match this run/project; refusing destructive purge")
    blockers=[]
    if status!="completed": blockers.append({"phase_id":"","task_id":"","reason":f"run-not-completed:{status}"})
    blockers.extend(_purge_run_blockers(run))
    result={"run_id":info.get("run_id"),"runtime_root":str(runtime),"safe_to_purge":not blockers,"blockers":blockers}
    if args.dry_run: return {**result,"dry_run":True}
    if blockers: raise ValueError(f"run runtime is not cleanup-safe; run purge-run --dry-run for blockers: {blockers[:8]}")
    phases=run/"phases"
    for phase_dir in sorted(phases.iterdir()) if phases.is_dir() else []:
        if not phase_dir.is_dir(): continue
        class P: pass
        p=P(); p.run_root=run; p.phase_id=phase_dir.name
        command_cleanup_phase(p)
    gc_analysis_views(run,drop_current_if_unused=True)
    # All Git worktrees/branches must have been removed by guarded cleanup before the
    # runtime subtree itself is deleted. Never raw-delete a still-populated worktree.
    residual=[]
    for ws_path in phases.glob("*/tasks/*/workspace.json") if phases.is_dir() else []:
        try: ws=dsd_task.load_json(ws_path)
        except Exception: continue
        wt=Path(str(ws.get("worktree") or ""))
        if wt and wt.exists() and runtime in [wt.resolve(),*wt.resolve().parents]: residual.append(str(wt.resolve()))
    if residual: raise ValueError(f"purge-run found retained runtime worktrees after cleanup; refusing raw deletion: {residual[:8]}")
    shutil.rmtree(runtime)
    return {**result,"purged":True}

def parser() -> argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="command",required=True)
    for name in ("create","checkpoint","integrate","cleanup"):
        p=sub.add_parser(name); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True); p.add_argument("--task-id",required=True)
        if name=="checkpoint": p.add_argument("--label",required=True)
        if name=="integrate": p.add_argument("--review-pass-report",type=Path,help="explicitly record this gated Reviewer report as PASS, accept, then integrate in one control call")
        if name=="cleanup":
            p.add_argument("--force",action="store_true",help="explicitly discard otherwise-protected non-live workspace state; never bypasses unresolved-attempt or superseded delta retention")
            p.add_argument("--reason",help="required with --force; durable reason for discarding workspace authority")
    p=sub.add_parser("cleanup-phase"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--phase-id",required=True)
    p=sub.add_parser("purge-run"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--dry-run",action="store_true")
    p=sub.add_parser("gc-analysis-views"); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--drop-current-if-unused",action="store_true")
    p=sub.add_parser("invalidate-analysis-view"); p.add_argument("--run-root",type=Path,required=True)
    return ap


def main()->int:
    args=parser().parse_args()
    try:
        if args.command=="create": out=command_create(args)
        elif args.command=="checkpoint": out=command_checkpoint(args)
        elif args.command=="integrate": out=command_integrate(args)
        elif args.command=="cleanup-phase": out=command_cleanup_phase(args)
        elif args.command=="purge-run": out=command_purge_run(args)
        elif args.command=="gc-analysis-views": out={"removed":gc_analysis_views(args.run_root.resolve(),drop_current_if_unused=args.drop_current_if_unused)}
        elif args.command=="invalidate-analysis-view": invalidate_analysis_view(args.run_root.resolve()); out={"invalidated":True}
        else: out=command_cleanup(args)
        print(json.dumps(out,sort_keys=True,separators=(",",":"))); return 0
    except (OSError,ValueError,TypeError,KeyError,json.JSONDecodeError) as exc:
        print(json.dumps({"ok":False,"command":getattr(args,"command",None),"error":str(exc)},sort_keys=True,separators=(",",":")))
        print(f"ERROR: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
