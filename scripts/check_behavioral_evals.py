#!/usr/bin/env python3
"""Validate the behavioral-evaluation corpus shape; this does not score model behavior."""
from __future__ import annotations
import argparse, json
from pathlib import Path

REQUIRED={"id","scenario","expected","forbidden"}

def main()->int:
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--corpus",type=Path,default=Path(__file__).resolve().parents[1]/"evals"/"cases.jsonl")
    args=ap.parse_args(); seen=set(); count=0
    for n,line in enumerate(args.corpus.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip(): continue
        obj=json.loads(line); missing=REQUIRED-set(obj)
        if missing: raise SystemExit(f"line {n}: missing {sorted(missing)}")
        if obj["id"] in seen: raise SystemExit(f"line {n}: duplicate id {obj['id']}")
        if not isinstance(obj["expected"],list) or not obj["expected"]: raise SystemExit(f"line {n}: expected must be non-empty array")
        if not isinstance(obj["forbidden"],list): raise SystemExit(f"line {n}: forbidden must be array")
        seen.add(obj["id"]); count+=1
    if count<8: raise SystemExit(f"behavioral corpus too small: {count}")
    print(json.dumps({"ok":True,"cases":count,"corpus":str(args.corpus.resolve())},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
