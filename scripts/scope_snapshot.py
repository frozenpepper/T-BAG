#!/usr/bin/env python3
"""Git-based attempt movement capture for T-BAG v2.2.

No content hashes are used. Each attempt begins from a named Git checkpoint in its
isolated task worktree. Comparison asks only what moved after that checkpoint.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str: return datetime.now(timezone.utc).isoformat()


def run(cmd: list[str], cwd: Path, *, check: bool=True) -> subprocess.CompletedProcess:
    cp=subprocess.run(cmd,cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    if check and cp.returncode!=0:
        raise ValueError(f"command failed ({cp.returncode}): {' '.join(cmd)}\n{cp.stderr.decode(errors='replace')[:1000]}")
    return cp


def resolve_ref(root: Path, ref: str) -> str:
    cp=run(["git","rev-parse","--verify",ref],root,check=False)
    if cp.returncode!=0:
        raise ValueError(f"Git baseline ref does not exist: {ref}")
    return cp.stdout.decode("utf-8",errors="replace").strip()


def ensure_ref(root: Path, ref: str) -> None:
    resolve_ref(root,ref)


def tracked_changes(root: Path, baseline_ref: str) -> tuple[list[str],list[str],list[str],list[str]]:
    raw=run(["git","diff","--name-status","-z",baseline_ref,"--","."],root).stdout
    changed=[]; added=[]; removed=[]; modified=[]; parts=raw.split(b"\0"); i=0
    while i < len(parts):
        status=parts[i].decode("utf-8",errors="surrogateescape") if parts[i] else ""; i+=1
        if not status: continue
        code=status[0]
        if code in {"R","C"}:
            if i+1>=len(parts): break
            old=parts[i].decode("utf-8",errors="surrogateescape"); new=parts[i+1].decode("utf-8",errors="surrogateescape"); i+=2
            changed.extend([old,new]); modified.extend([old,new])
        else:
            if i>=len(parts): break
            path=parts[i].decode("utf-8",errors="surrogateescape"); i+=1; changed.append(path)
            if code=="A": added.append(path)
            elif code=="D": removed.append(path)
            else: modified.append(path)
    untracked=run(["git","ls-files","-z","--others","--exclude-standard"],root).stdout
    for item in untracked.split(b"\0"):
        if item:
            path=item.decode("utf-8",errors="surrogateescape"); changed.append(path); added.append(path)
    def uniq(xs:list[str])->list[str]: return list(dict.fromkeys(xs))
    return uniq(changed),uniq(added),uniq(removed),uniq(modified)


def capture(root: Path, baseline_ref: str) -> dict[str,Any]:
    oid=resolve_ref(root,baseline_ref)
    return {"format":"dsd-scope-baseline-v2.1","project_root":str(root),"baseline_ref":baseline_ref,"baseline_oid":oid,"captured_at":now()}


def compare(root: Path, baseline: dict[str,Any]) -> dict[str,Any]:
    ref=str(baseline.get("baseline_ref") or ""); ensure_ref(root,ref)
    changed,added,removed,modified=tracked_changes(root,ref)
    return {
        "format":"dsd-scope-comparison-v2.1","project_root":str(root),"baseline_ref":ref,
        "baseline_oid":baseline.get("baseline_oid") or resolve_ref(root,ref),"baseline_captured_at":baseline.get("captured_at"),"compared_at":now(),
        "changed_since_attempt_baseline":changed,"changed_count":len(changed),
        "added":added,"removed":removed,"modified":modified,
        "semantics":"movement since the named attempt checkpoint; Git status/diff remains authoritative for current repository state",
    }


def write_new(path: Path, data: dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("x",encoding="utf-8") as f: f.write(json.dumps(data,indent=2,sort_keys=True)+"\n")


def parser()->argparse.ArgumentParser:
    ap=argparse.ArgumentParser(description=__doc__); sub=ap.add_subparsers(dest="command",required=True)
    p=sub.add_parser("capture"); p.add_argument("--root",type=Path,required=True); p.add_argument("--baseline-ref",required=True); p.add_argument("--output",type=Path,required=True)
    p=sub.add_parser("compare"); p.add_argument("--root",type=Path,required=True); p.add_argument("--baseline",type=Path,required=True); p.add_argument("--output",type=Path); p.add_argument("--fail-on-change",action="store_true")
    return ap


def main()->int:
    args=parser().parse_args(); root=args.root.resolve()
    try:
        if not root.is_dir(): raise ValueError(f"project/worktree missing: {root}")
        if args.command=="capture":
            data=capture(root,args.baseline_ref); write_new(args.output.resolve(),data); print(f"Captured attempt checkpoint {args.baseline_ref} -> {args.output.resolve()}"); return 0
        baseline=json.loads(args.baseline.read_text(encoding="utf-8")); data=compare(root,baseline)
        if args.output: write_new(args.output.resolve(),data); print(f"Compared scope; {data['changed_count']} path(s) changed -> {args.output.resolve()}")
        else: print(json.dumps(data,indent=2,sort_keys=True))
        return 1 if args.fail_on_change and data["changed_count"] else 0
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(f"scope_snapshot error: {exc}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
