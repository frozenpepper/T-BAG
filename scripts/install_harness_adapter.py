#!/usr/bin/env python3
"""Install the project-local T-BAG adapter for the selected orchestrator harness.

The installer is idempotent and backs up changed JSON configuration files. It
never edits user-global harness configuration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from detect_harness import select_harness

MARKER = "TBag/tools/context_checkpoint.py"


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def git_root(start: Path) -> Path:
    try:
        out = subprocess.check_output(["git", "-C", str(start), "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL).strip()
        if out:
            return Path(out).resolve()
    except Exception:
        pass
    return start.resolve()


def backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    destination = path.with_name(path.name + f".dsd-backup-{utc_stamp()}")
    shutil.copy2(path, destination)
    return destination


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def ensure_hook(data: dict[str, Any], event: str, group: dict[str, Any], marker: str = MARKER) -> bool:
    hooks = data.setdefault("hooks", {})
    groups = hooks.setdefault(event, [])
    for existing in groups:
        for handler in existing.get("hooks", []):
            if marker in str(handler.get("command", "")) and (event.lower() in str(handler.get("command", "")).lower() or marker != MARKER):
                if existing == group:
                    return False
                existing.clear(); existing.update(group); return True
    groups.append(group)
    return True


def install_hook_fragment(path: Path, fragment_path: Path) -> tuple[bool, Path | None]:
    """Merge canonical hook groups from a checked-in adapter fragment."""
    data = load_json(path)
    fragment = load_json(fragment_path)
    changed = False
    canonical_events=set((fragment.get("hooks") or {}).keys())
    hooks=data.get("hooks") if isinstance(data.get("hooks"),dict) else {}
    for event, groups in list(hooks.items()):
        if event in canonical_events or not isinstance(groups,list):
            continue
        kept=[]
        for group in groups:
            handlers=group.get("hooks",[]) if isinstance(group,dict) else []
            if any(
                MARKER in str(handler.get("command", "")) or "claude_worker_rewake.py" in str(handler.get("command", ""))
                for handler in handlers if isinstance(handler,dict)
            ):
                changed=True
            else:
                kept.append(group)
        if kept:
            hooks[event]=kept
        else:
            hooks.pop(event,None)
    if "description" in fragment and data.get("description") != fragment["description"]:
        data["description"] = fragment["description"]
        changed = True
    for event, groups in (fragment.get("hooks") or {}).items():
        for group in groups:
            marker = "claude_worker_rewake.py" if any(
                "claude_worker_rewake.py" in str(h.get("command", ""))
                for h in group.get("hooks", [])
            ) else MARKER
            changed |= ensure_hook(data, event, group, marker=marker)
    backup_path = backup(path) if changed and path.exists() else None
    if changed:
        write_json(path, data)
    return changed, backup_path


def write_skill_shim(destination: Path, target: Path) -> None:
    """Write a tiny project-local hook shim that always executes the installed skill."""
    scripts = target.parent.resolve()
    body = (
        "#!/usr/bin/env python3\n"
        "import runpy, sys\n"
        f"SCRIPTS = {str(scripts)!r}\n"
        "sys.path.insert(0, SCRIPTS)\n"
        f"runpy.run_path({str(target.resolve())!r}, run_name='__main__')\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    destination.chmod(0o755)


def install_helper(skill_root: Path, project_root: Path) -> dict[str, Path]:
    tools = project_root / "TBag" / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    target = tools / "context_checkpoint.py"
    dsd_task = tools / "dsd_task.py"
    dsd_attempt = tools / "dsd_attempt.py"
    write_skill_shim(target, skill_root / "scripts" / "context_checkpoint.py")
    write_skill_shim(dsd_task, skill_root / "scripts" / "dsd_task.py")
    write_skill_shim(dsd_attempt, skill_root / "scripts" / "dsd_attempt.py")
    # Remove legacy copied control-plane modules. Immutable run evidence remains in runs/;
    # project hooks need only the stable shim above.
    for name in ("check_state.py", "dsd_state.py", "_contract.py", "_rules_snapshot.py", "_roles.py"):
        (tools / name).unlink(missing_ok=True)
    return {"context_checkpoint": target, "dsd_task": dsd_task, "dsd_attempt": dsd_attempt}


def install_codex(project_root: Path, skill_root: Path) -> dict[str, Any]:
    path = project_root / ".codex" / "hooks.json"
    changed, backup_path = install_hook_fragment(path, skill_root / "adapters" / "codex" / "hooks.json")
    return {
        "harness": "codex",
        "config": str(path),
        "changed": changed,
        "backup": str(backup_path) if backup_path else None,
        "manual_step": "Open /hooks in Codex and trust the project-local hooks before relying on them.",
    }


def install_claude(project_root: Path, skill_root: Path) -> dict[str, Any]:
    path = project_root / ".claude" / "settings.json"
    changed, backup_path = install_hook_fragment(path, skill_root / "adapters" / "claude" / "settings.fragment.json")
    legacy_rewake = project_root / "TBag" / "tools" / "claude_worker_rewake.py"
    legacy_removed = legacy_rewake.exists()
    legacy_rewake.unlink(missing_ok=True)
    return {
        "harness": "claude-code",
        "config": str(path),
        "changed": changed or legacy_removed,
        "backup": str(backup_path) if backup_path else None,
        "interactive_supervision": "native-background-follow",
        "autonomous_supervision": "background-follow-completion",
        "legacy_rewake_removed": legacy_removed,
        "manual_step": "After each detached launch, run TBag/tools/dsd_attempt.py follow for that exact event_dir as a Claude Code background Bash task. The task chip is the display; its completion wakes the parent. Do not add a second polling/re-wake hook.",
    }


def install_plugin_file(project_root: Path, harness: str, destination: Path, source_path: Path) -> dict[str, Any]:
    source = source_path.read_text(encoding="utf-8")
    source_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
    path = project_root / destination
    changed = not path.exists() or path.read_text(encoding="utf-8") != source
    backup_path = backup(path) if changed and path.exists() else None
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    installed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "harness": harness,
        "plugin": str(path),
        "changed": changed,
        "backup": str(backup_path) if backup_path else None,
        "source_sha256": source_sha256,
        "installed_sha256": installed_sha256,
        "disk_matches_source": installed_sha256 == source_sha256,
    }


def install_opencode(project_root: Path, skill_root: Path) -> dict[str, Any]:
    result = install_plugin_file(
        project_root, "opencode", Path(".opencode/plugins/tbag.js"),
        skill_root / "adapters" / "opencode" / "tbag.js",
    )
    legacy = project_root / ".opencode" / "plugins" / "dsd-compaction.ts"
    legacy_removed = legacy.exists()
    legacy.unlink(missing_ok=True)
    result.update({
        "interactive_supervision": "detached-core-launch-then-tbag-follow",
        "autonomous_supervision": "per-attempt-tbag-follow-wake",
        "required_live_tool": "tbag_follow",
        "live_capability_verified": False,
        "activation": "restart-required-to-load-refreshed-adapter" if result.get("changed") or legacy_removed else "disk-current-live-registry-unverified",
        "legacy_plugin_removed": legacy_removed,
        "manual_step": "The installer proves only the project adapter file on disk; it cannot inspect the current OpenCode tool registry. If the adapter changed, restart/reload OpenCode to activate the refreshed hooks. The stable parent protocol is detached core dsd_attempt.py launch, then immediate tbag_follow for the exact returned run_root/phase_id/task_id/event_dir, then yield. If tbag_follow is already visible, that protocol remains safe even with an older follow-only adapter. Never run core dsd_attempt.py follow or a Bash/Python wait/poll in the OpenCode parent turn.",
    })
    return result


def install_kilo(project_root: Path, skill_root: Path) -> dict[str, Any]:
    result = install_plugin_file(
        project_root, "kilo", Path(".kilo/plugin/dsd-compaction.ts"),
        skill_root / "adapters" / "kilo" / "dsd-compaction.ts",
    )
    result["manual_step"] = "Restart/reload Kilo so the project-local plugin is active; it injects reconcile-first T-BAG orientation during compaction."
    return result

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--harness", default="auto", choices=["auto", "codex", "claude-code", "opencode", "kilo"])
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--skill-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    project_root = git_root(args.project_root)
    skill_root = args.skill_root.resolve()
    try:
        selected, _confidence, _scores, _commands = select_harness(None if args.harness == "auto" else args.harness)
        if selected == "unknown":
            raise RuntimeError("Harness detection is ambiguous; pass --harness codex|claude-code|opencode|kilo")
        harness = selected
        helpers = install_helper(skill_root, project_root)
        if harness == "codex": result = install_codex(project_root, skill_root)
        elif harness == "claude-code": result = install_claude(project_root, skill_root)
        elif harness == "opencode": result = install_opencode(project_root, skill_root)
        else: result = install_kilo(project_root, skill_root)
        result.update({"project_root": str(project_root), "helper": str(helpers["context_checkpoint"]), "helpers": {k: str(v) for k, v in helpers.items()}, "installed_at": utc_stamp()})
        report = project_root / "TBag" / "harness-adapter-installation.md"
        report.write_text("# T-BAG Harness Adapter\n\n```json\n" + json.dumps(result, indent=2) + "\n```\n", encoding="utf-8")
        print(json.dumps(result, indent=2)); return 0
    except Exception as exc:
        print(json.dumps({"ok":False,"command":"install-harness-adapter","error":str(exc)},sort_keys=True,separators=(",",":")))
        print(f"ERROR: {exc}", file=sys.stderr); return 2

if __name__ == "__main__": raise SystemExit(main())
