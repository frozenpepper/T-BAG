#!/usr/bin/env python3
"""Detect the current orchestrator harness and describe continuity/supervision capabilities.

Detection is conservative. An explicit --harness or TBAG_ORCHESTRATOR_HARNESS wins. When evidence is ambiguous, the script reports candidates rather than silently choosing the wrong adapter.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from typing import Iterable

KNOWN = {"codex", "claude-code", "opencode", "kilo", "unknown"}


def parent_commands(limit: int = 8) -> list[str]:
    commands: list[str] = []
    pid = os.getpid()
    for _ in range(limit):
        try:
            out = subprocess.check_output(["ps", "-o", "ppid=,command=", "-p", str(pid)], text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            break
        if not out:
            break
        parts = out.split(None, 1)
        if len(parts) != 2:
            break
        ppid, command = parts
        commands.append(command)
        try:
            pid = int(ppid)
        except ValueError:
            break
        if pid <= 1:
            break
    return commands


def score_candidates(commands: Iterable[str]) -> dict[str, int]:
    env = os.environ
    scores = {"codex": 0, "claude-code": 0, "opencode": 0, "kilo": 0}
    explicit = env.get("TBAG_ORCHESTRATOR_HARNESS", "").strip().lower()
    if explicit in scores:
        scores[explicit] += 100
    if env.get("CODEX_HOME") or env.get("CODEX_THREAD_ID") or env.get("CODEX_SESSION_ID"):
        scores["codex"] += 5
    if env.get("CLAUDE_PROJECT_DIR") or env.get("CLAUDE_ENV_FILE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        scores["claude-code"] += 5
    if env.get("OPENCODE") or env.get("OPENCODE_DB") or env.get("OPENCODE_CONFIG") or env.get("OPENCODE_CLIENT"):
        scores["opencode"] += 5
    joined = "\n".join(commands).lower()
    if "codex" in joined: scores["codex"] += 8
    if "claude" in joined: scores["claude-code"] += 8
    if "opencode" in joined: scores["opencode"] += 8
    if "kilo" in joined: scores["kilo"] += 8
    return scores


def select_harness(explicit: str | None = None) -> tuple[str, str, dict[str, int], list[str]]:
    """Return selected harness, confidence, scores, and inspected parent commands."""
    if explicit:
        value = explicit.strip().lower()
        if value not in KNOWN - {"unknown"}:
            raise ValueError(f"unsupported harness: {explicit}")
        commands = parent_commands()
        return value, "explicit", score_candidates(commands), commands
    commands = parent_commands()
    scores = score_candidates(commands)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if ranked[0][1] <= 0 or (len(ranked) > 1 and ranked[0][1] == ranked[1][1]):
        return "unknown", "ambiguous", scores, commands
    return ranked[0][0], "detected", scores, commands


def capabilities(harness: str) -> dict[str, object]:
    base: dict[str, object] = {
        "harness": harness,
        "durable_state": "run.json + task-local files",
        "compaction_checkpoint_stream": False,
        "degraded_supervision_policy": "conversation-first",
    }
    if harness == "claude-code":
        base.update({"compaction_resume": "sessionstart-hook", "autonomous_supervision": "native-background-follow", "interactive_supervision": "background-task-chip", "adapter": "CLAUDE.md"})
    elif harness == "codex":
        base.update({"compaction_resume": "sessionstart-hook", "autonomous_supervision": False, "adapter": "CODEX.md"})
    elif harness == "opencode":
        base.update({
            "compaction_resume": "requires-live-project-plugin",
            "autonomous_supervision": "requires-live-tbag_follow",
            "interactive_supervision": "detached-core-launch-then-tbag-follow",
            "requires_project_adapter": True,
            "required_live_tool": "tbag_follow",
            "live_capability_verified": False,
            "adapter": "OPENCODE.md",
        })
    elif harness == "kilo":
        base.update({"compaction_resume": "precompact-context-injection", "autonomous_supervision": False, "adapter": "KILO.md"})
    else:
        base.update({"compaction_resume": "manual-reconcile", "autonomous_supervision": False, "adapter": "HARNESS.md"})
    return base


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", choices=sorted(KNOWN - {"unknown"}), help="Explicit harness")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    args = parser.parse_args()
    selected, confidence, scores, commands = select_harness(args.harness)
    result = {"selected": selected, "confidence": confidence, "scores": scores,
              "parent_commands": commands, "capabilities": capabilities(selected),
              "instruction": "Use explicit current-session identity when detection is ambiguous."}
    if args.json: print(json.dumps(result, indent=2))
    else:
        print(f"HARNESS={selected}"); print(f"CONFIDENCE={confidence}"); print(f"ADAPTER={result['capabilities']['adapter']}")
        if selected == "unknown": print("AMBIGUOUS: set TBAG_ORCHESTRATOR_HARNESS or pass --harness.")
    return 0 if selected != "unknown" else 3

if __name__ == "__main__": raise SystemExit(main())
