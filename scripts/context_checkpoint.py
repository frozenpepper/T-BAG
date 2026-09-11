#!/usr/bin/env python3
"""Inject reconcile-first orientation after parent-session compaction/resume.

Execution truth already lives in ``run.json`` and task-local files.  This helper
selects the resumable run and emits orientation only; it never creates another
checkpoint/state stream.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


class NoActiveRun(RuntimeError):
    pass


class AmbiguousRun(RuntimeError):
    pass


def git_root(start: Path) -> Path:
    cp = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return Path(cp.stdout.strip()).resolve() if cp.returncode == 0 and cp.stdout.strip() else start.resolve()


def choose_run(project: Path, explicit: str | None) -> Path:
    configured = explicit or os.environ.get("TBAG_RUN_ROOT")
    if configured:
        run = Path(configured).resolve()
        if not (run / "run.json").is_file():
            raise NoActiveRun(f"configured run root is not a T-BAG run: {run}")
        return run

    runs = project / "TBag" / "runs"
    candidates: list[Path] = []
    if runs.is_dir():
        for path in runs.iterdir():
            run_json = path / "run.json"
            if not run_json.is_file():
                continue
            try:
                data = json.loads(run_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("status", "active") in {"active", "human-blocked", "paused-by-user"}:
                candidates.append(path.resolve())

    if not candidates:
        raise NoActiveRun("no resumable T-BAG run")
    if len(candidates) > 1:
        names = ", ".join(sorted(path.name for path in candidates))
        raise AmbiguousRun(f"multiple resumable T-BAG runs ({names}); set TBAG_RUN_ROOT explicitly")
    return candidates[0]


def instruction(project: Path, run_arg: str | None) -> str:
    run = choose_run(project, run_arg)
    return "\n".join([
        f"Resume T-BAG run `{run}`.",
        f"First run `python3 <skill>/scripts/parent_tick.py tick --run-root {run}` and follow its continue/launch/update/intervene/finish boundary; do not reconstruct a separate monitor loop.",
        "Do not reconstruct technical history from chat or scan every report. Open only evidence needed for the next routing decision; ambiguous technical orientation belongs to Analyst Discovery.",
    ])


def hook_response(harness: str, text: str = "") -> None:
    if harness == "claude-code":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}))
    else:
        print(json.dumps({"continue": True, "systemMessage": text or "T-BAG continuity hook completed"}))


def command_hook(args: argparse.Namespace) -> int:
    raw = sys.stdin.read()
    payload: dict[str, object] = {}
    if raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            pass
    project = git_root(Path(str(payload.get("cwd") or args.project_root or os.getcwd())))
    try:
        hook_response(args.harness, instruction(project, args.run_root))
    except NoActiveRun:
        hook_response(args.harness, "")
    except Exception as exc:
        hook_response(args.harness, f"T-BAG continuity warning: {exc}")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root")
    ap.add_argument("--run-root")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("instruction")
    p = sub.add_parser("hook")
    p.add_argument("--harness", required=True, choices=["codex", "claude-code"])
    return ap


def main() -> int:
    args = parser().parse_args()
    project = git_root(Path(args.project_root or os.getcwd()))
    try:
        if args.command == "instruction":
            print(instruction(project, args.run_root))
            return 0
        return command_hook(args)
    except NoActiveRun as exc:
        print(f"NO_ACTIVE_RUN: {exc}", file=sys.stderr)
        return 4
    except AmbiguousRun as exc:
        print(f"AMBIGUOUS_RUN: {exc}", file=sys.stderr)
        return 5
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
