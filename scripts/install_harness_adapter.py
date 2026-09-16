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
from opencode_tui_compat import V1_SPEC, detect_opencode_version, ensure_tui_plugin, remove_tui_plugin, tui_config_path

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


def backup_text(path: Path, text: str) -> Path:
    destination = path.with_name(path.name + f".dsd-backup-{utc_stamp()}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8")
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
    parent_tick = tools / "parent_tick.py"
    tbag_status = tools / "tbag_status.py"
    tbag_render = tools / "tbag_render.py"
    write_skill_shim(target, skill_root / "scripts" / "context_checkpoint.py")
    write_skill_shim(dsd_task, skill_root / "scripts" / "dsd_task.py")
    write_skill_shim(dsd_attempt, skill_root / "scripts" / "dsd_attempt.py")
    write_skill_shim(parent_tick, skill_root / "scripts" / "parent_tick.py")
    write_skill_shim(tbag_status, skill_root / "scripts" / "tbag_status.py")
    write_skill_shim(tbag_render, skill_root / "scripts" / "tbag_render.py")
    # Remove legacy copied control-plane modules. Immutable run evidence remains in runs/;
    # project hooks need only the stable shim above.
    for name in ("check_state.py", "dsd_state.py", "_contract.py", "_rules_snapshot.py", "_roles.py"):
        (tools / name).unlink(missing_ok=True)
    return {"context_checkpoint": target, "dsd_task": dsd_task, "dsd_attempt": dsd_attempt, "parent_tick": parent_tick, "tbag_status": tbag_status, "tbag_render": tbag_render}


def install_codex(project_root: Path, skill_root: Path) -> dict[str, Any]:
    path = project_root / ".codex" / "hooks.json"
    changed, backup_path = install_hook_fragment(path, skill_root / "adapters" / "codex" / "hooks.json")
    render = project_root / "TBag" / "tools" / "tbag_render.py"
    status_command = f'python3 "{render}" status --project-root "{project_root}"'
    watch_command = f'python3 "{render}" watch --project-root "{project_root}"'
    return {
        "harness": "codex",
        "config": str(path),
        "changed": changed,
        "backup": str(backup_path) if backup_path else None,
        "status_surface": "companion-terminal",
        "status_command": status_command,
        "watch_command": watch_command,
        "manual_step": "Open /hooks in Codex and trust the project-local hooks. Codex's stock status line currently accepts only built-in items; for live T-BAG visibility run the reported watch_command in an adjacent terminal/tmux/zellij pane. The display is read-only.",
    }


def install_claude(project_root: Path, skill_root: Path) -> dict[str, Any]:
    path = project_root / ".claude" / "settings.json"
    fragment_path = skill_root / "adapters" / "claude" / "settings.fragment.json"
    existed_before = path.exists()
    changed, backup_path = install_hook_fragment(path, fragment_path)
    fragment = load_json(fragment_path)
    desired = fragment.get("statusLine") if isinstance(fragment.get("statusLine"), dict) else None
    data = load_json(path)
    existing = data.get("statusLine")
    existing_command = str(existing.get("command") or "") if isinstance(existing, dict) else ""
    tbag_owned = bool(existing_command and "TBag/tools/tbag_render.py" in existing_command)
    status_line_changed = False
    status_line_conflict = False
    if desired is not None and (existing is None or tbag_owned):
        if existing != desired:
            if backup_path is None and existed_before:
                backup_path = backup(path)
            data["statusLine"] = desired
            write_json(path, data)
            status_line_changed = True
    elif desired is not None and existing != desired:
        status_line_conflict = True
    legacy_rewake = project_root / "TBag" / "tools" / "claude_worker_rewake.py"
    legacy_removed = legacy_rewake.exists()
    legacy_rewake.unlink(missing_ok=True)
    manual = (
        "Claude Code reloads project settings automatically. T-BAG's native status line refreshes every 5 seconds and is read-only; keep using a native background Bash follow task per live attempt for wake delivery."
        if not status_line_conflict
        else "An existing non-T-BAG Claude statusLine was preserved. Use TBag/tools/tbag_render.py status/watch manually or compose your existing status command with the T-BAG renderer; T-BAG will not overwrite custom presentation."
    )
    return {
        "harness": "claude-code",
        "config": str(path),
        "changed": changed or status_line_changed or legacy_removed,
        "backup": str(backup_path) if backup_path else None,
        "interactive_supervision": "native-background-follow",
        "autonomous_supervision": "background-follow-completion",
        "status_surface": "native-status-line" if not status_line_conflict else "custom-status-line-preserved",
        "status_line_installed": bool(desired is not None and not status_line_conflict),
        "status_line_conflict": status_line_conflict,
        "legacy_rewake_removed": legacy_removed,
        "manual_step": manual,
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
    version, major = detect_opencode_version()
    transport_source = "tbag-v2.js" if major == 2 else "tbag.js"
    transport_generation = "v2" if major == 2 else "v1"
    result = install_plugin_file(
        project_root, "opencode", Path(".opencode/plugins/tbag.js"),
        skill_root / "adapters" / "opencode" / transport_source,
    )
    ui_results: list[dict[str, Any]] = []
    tui_config: str | None = None
    tui_config_changed = False
    tui_config_backup: Path | None = None
    stale_v1_removed = False
    status_surface = "transport-only-host-version-unknown"
    tui_generation = "unknown"

    config_before_path = tui_config_path(project_root)
    config_before_text = config_before_path.read_text(encoding="utf-8") if config_before_path.exists() else None

    if major == 1:
        ui_results.append(install_plugin_file(
            project_root, "opencode", Path(".opencode/plugins/tbag-status-tui-v1.tsx"),
            skill_root / "adapters" / "opencode" / "tbag-status-tui-v1.tsx",
        ))
        tui_config_changed, config_path = ensure_tui_plugin(project_root, V1_SPEC)
        tui_config = str(config_path)
        if tui_config_changed and config_before_text is not None:
            tui_config_backup = backup_text(config_path, config_before_text)
        status_surface = "tui-v1-sidebar-route"
        tui_generation = "v1"
    elif major == 2:
        for name in ("index.ts", "tui.ts", "tui.tsx"):
            ui_results.append(install_plugin_file(
                project_root, "opencode", Path(".opencode/plugins/tbag-ui") / name,
                skill_root / "adapters" / "opencode" / "tbag-ui" / name,
            ))
        tui_config_changed, config_path = remove_tui_plugin(project_root, V1_SPEC)
        tui_config = str(config_path) if config_path else None
        if tui_config_changed and config_before_text is not None and config_path is not None:
            tui_config_backup = backup_text(config_path, config_before_text)
        stale_v1 = project_root / ".opencode" / "plugins" / "tbag-status-tui-v1.tsx"
        stale_v1_removed = stale_v1.exists()
        stale_v1.unlink(missing_ok=True)
        status_surface = "tui-v2-companion"
        tui_generation = "v2"

    legacy = project_root / ".opencode" / "plugins" / "dsd-compaction.ts"
    legacy_removed = legacy.exists()
    legacy.unlink(missing_ok=True)
    changed = bool(
        result.get("changed")
        or any(x.get("changed") for x in ui_results)
        or tui_config_changed
        or stale_v1_removed
        or legacy_removed
    )
    result["changed"] = changed

    if major == 1:
        presentation_note = "OpenCode 1.x requires the T-BAG TUI file to be listed in .opencode/tui.json or tui.jsonc; the installer has merged that registration. After restart, /tbag and the sidebar should appear. In the built-in Plugins dialog, tbag.status.v1 should be listed enabled+active."
    elif major == 2:
        presentation_note = "OpenCode 2.x uses the native setup()-based T-BAG server adapter plus the separately shipped tbag-ui companion. Restart/reload after changes and confirm both plugins are active."
    else:
        presentation_note = "OpenCode version detection failed or returned an unsupported major version, so T-BAG installed only the stable server transport adapter and did not guess a TUI API generation."

    result.update({
        "opencode_version": version,
        "opencode_major": major,
        "transport_generation": transport_generation,
        "tui_generation": tui_generation,
        "tui_plugin": [x.get("plugin") for x in ui_results],
        "tui_config": tui_config,
        "tui_config_changed": tui_config_changed,
        "tui_config_backup": str(tui_config_backup) if tui_config_backup else None,
        "status_surface": status_surface,
        "interactive_supervision": "detached-core-launch; optional-tbag-follow-rearm",
        "autonomous_supervision": "first-parent-tick-auto-enrolls-heartbeat-plus-launch-auto-arm",
        "live_probe_tool": None if major == 2 else "tbag_follow",
        "live_capability_verified": False,
        "activation": "restart-required-to-load-refreshed-adapter" if changed else "disk-current-live-registry-unverified",
        "legacy_plugin_removed": legacy_removed,
        "stale_v1_companion_removed": stale_v1_removed,
        "manual_step": "The installer proves only the project adapter file on disk plus project TUI config; it cannot inspect the current OpenCode plugin registry or prove transport/presentation live. " + presentation_note + " Once the server adapter is live, the first normal TBag/tools/parent_tick.py tick automatically enrolls the current session/run in heartbeat supervision; no separate heartbeat setup is required. Never run core dsd_attempt.py follow or a Bash/Python wait/poll in the parent turn.",
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
