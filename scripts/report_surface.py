#!/usr/bin/env python3
"""Return a small routing-oriented surface from a worker report."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_DECISION_LABELS=("conclusion","disposition","verdict","outcome","recommendation","result","status")


def _bounded(lines:list[str], *, max_lines:int, max_chars:int)->list[str]:
    out=[]; used=0
    for raw in lines:
        line=raw.strip()
        if not line: continue
        remaining=max_chars-used
        if remaining<=0 or len(out)>=max_lines: break
        if len(line)>remaining: line=line[:max(0,remaining-1)]+"…"
        out.append(line); used+=len(line)
        if used>=max_chars: break
    return out


def surface(path: Path, *, max_lines: int = 8, max_chars: int = 1600) -> list[str]:
    """Prefer an explicit routing conclusion; otherwise return a bounded prefix.

    The whole file is scanned locally, but only the small selected surface is printed
    into parent context. This is extraction, not semantic judgment.
    """
    raw_lines=path.read_text(encoding="utf-8",errors="replace").splitlines()
    start=None
    for idx,raw in enumerate(raw_lines):
        text=re.sub(r"^\s*#{1,6}\s*","",raw).strip()
        lowered=text.casefold()
        if any(lowered==label or lowered.startswith(label+":") or lowered.startswith(label+" —") or lowered.startswith(label+" -") for label in _DECISION_LABELS):
            start=idx; break
    if start is not None:
        selected=[]
        for raw in raw_lines[start:]:
            if selected and re.match(r"^\s*#{1,6}\s+",raw): break
            selected.append(raw)
        bounded=_bounded(selected,max_lines=max_lines,max_chars=max_chars)
        if bounded: return bounded
    return _bounded(raw_lines,max_lines=max_lines,max_chars=max_chars)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report",type=Path,required=True)
    ap.add_argument("--lines",type=int,default=8)
    ap.add_argument("--chars",type=int,default=1600)
    ap.add_argument("--json",action="store_true")
    args=ap.parse_args()
    report=args.report.resolve()
    if not report.is_file():
        error={"ok":False,"command":"report-surface","error":f"report missing: {report}"}
        print(json.dumps(error,sort_keys=True,separators=(",",":"))); print(f"ERROR: {error['error']}",file=sys.stderr); return 2
    lines=surface(report,max_lines=max(1,args.lines),max_chars=max(200,args.chars))
    if args.json: print(json.dumps({"report":str(report),"surface":lines},indent=2,sort_keys=True))
    else: print("\n".join(lines))
    return 0


if __name__=="__main__": raise SystemExit(main())
