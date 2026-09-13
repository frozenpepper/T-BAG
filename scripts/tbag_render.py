#!/usr/bin/env python3
"""Human-facing renderers for the read-only T-BAG status snapshot.

This module never mutates orchestration state.  It is intentionally a presentation
layer over ``tbag_status.build_snapshot`` so OpenCode, Claude Code, Codex and a
plain terminal can all show the same durable truth without reimplementing control
logic in host-specific plugins.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import tbag_status

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"


def _ansi(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{RESET}" if enabled else text


def _width(value: int | None = None, *, fallback: int = 120) -> int:
    if value is not None and value > 20:
        return value
    raw = os.environ.get("COLUMNS")
    try:
        parsed = int(raw or 0)
    except ValueError:
        parsed = 0
    if parsed > 20:
        return parsed
    try:
        return max(40, shutil.get_terminal_size((fallback, 40)).columns)
    except OSError:
        return fallback


def _fit(text: str, width: int) -> str:
    if width <= 1:
        return text[:width]
    if len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def _pct(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(100.0, number))


def _bar(value: Any, width: int = 12) -> str:
    percent = _pct(value)
    filled = int(round(width * percent / 100.0))
    return "█" * filled + "░" * max(0, width - filled)


def _duration(value: Any) -> str:
    try:
        seconds = max(0, int(float(value)))
    except (TypeError, ValueError):
        return "?"
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _short(value: Any, limit: int = 16) -> str:
    text = str(value or "")
    if not text:
        return "—"
    return text if len(text) <= limit else text[: max(1, limit - 1)] + "…"


def _health(worker: dict[str, Any]) -> tuple[str, str]:
    attention = str(worker.get("attention") or "")
    if attention:
        return f"⚠ {attention}", "warn"
    process = worker.get("process") if isinstance(worker.get("process"), dict) else {}
    proc = process.get("worker") if isinstance(process.get("worker"), dict) else {}
    if proc and not proc.get("alive"):
        return "○ process-down", "bad"
    observer = worker.get("observer") if isinstance(worker.get("observer"), dict) else {}
    if observer.get("known") is False:
        return "● process", "ok"
    if observer and not observer.get("healthy"):
        return "◐ observer-missing", "warn"
    deadline = worker.get("deadline") if isinstance(worker.get("deadline"), dict) else {}
    if deadline.get("exceeded") or worker.get("deadline_exceeded"):
        return "⚠ overdue", "warn"
    return "● healthy", "ok"


def _state_marker(status: Any) -> tuple[str, str]:
    text = str(status or "unknown").lower()
    if text == "completed":
        return "✓", "ok"
    if text in {"human-blocked", "abandoned"}:
        return "!", "bad"
    if text in {"paused-by-user"}:
        return "Ⅱ", "warn"
    return "●", "ok"


def compact_header(snapshot: dict[str, Any], *, width: int = 120, color: bool = False, host: dict[str, Any] | None = None) -> str:
    run = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    budget = snapshot.get("worker_budget") if isinstance(snapshot.get("worker_budget"), dict) else {}
    phase = snapshot.get("current_phase") if isinstance(snapshot.get("current_phase"), dict) else {}
    analysts = snapshot.get("analysts_active") if isinstance(snapshot.get("analysts_active"), list) else []
    grunts = snapshot.get("grunts_active") if isinstance(snapshot.get("grunts_active"), list) else []
    attention = snapshot.get("attention") if isinstance(snapshot.get("attention"), list) else []
    marker, level = _state_marker(run.get("status"))
    marker_color = GREEN if level == "ok" else YELLOW if level == "warn" else RED
    phase_label = str(phase.get("phase_id") or "—")
    pct = _pct(progress.get("registered_percent"))
    parts = [
        _ansi("T-BAG", BOLD, color),
        f"{_ansi(marker, marker_color, color)} {str(run.get('status') or 'unknown').upper()}",
        f"phase {phase_label}",
        f"{_bar(pct, 10)} {pct:g}%",
        f"A{len(analysts)} G{len(grunts)}",
        f"slots {budget.get('live', 0)}/{budget.get('max', 0)}",
    ]
    if attention:
        parts.append(_ansi(f"⚠{len(attention)}", YELLOW, color))
    if host:
        model = str(host.get("model") or "").strip()
        context = host.get("context_percent")
        if model:
            host_text = model
            if context is not None:
                host_text += f" ctx {_pct(context):g}%"
            parts.append(_ansi(host_text, DIM, color))
    return _fit(" · ".join(parts), width)


def _worker_summary(worker: dict[str, Any], *, width: int, color: bool, prefix: str) -> str:
    health, level = _health(worker)
    health_color = GREEN if level == "ok" else YELLOW if level == "warn" else RED
    objective = " ".join(str(worker.get("objective") or "").split())
    model = _short(worker.get("model"), 24)
    session = worker.get("session") if isinstance(worker.get("session"), dict) else {}
    text = (
        f"{prefix} {worker.get('task_id') or '?'} {worker.get('role') or '?'}"
        f" · {objective or 'no objective'}"
        f" · {_duration(worker.get('elapsed_seconds'))}"
        f" · {model}"
        f" · {_short(session.get('id'), 13)}"
        f" · {_ansi(health, health_color, color)}"
    )
    return _fit(text, width)


def claude_status_lines(snapshot: dict[str, Any], *, host: dict[str, Any] | None = None, width: int = 120, color: bool = True) -> list[str]:
    """Render a compact persistent Claude Code status surface.

    Keep the surface intentionally short: one run line plus one Analyst and one Grunt
    line.  Multiple workers are represented explicitly up to the width budget and
    summarized with ``+N`` rather than growing the terminal footer indefinitely.
    """
    lines = [compact_header(snapshot, width=width, color=color, host=host)]
    for key, label, prefix, tint in (
        ("analysts_active", "Analysts", "◆", MAGENTA),
        ("grunts_active", "Grunts", "●", CYAN),
    ):
        workers = snapshot.get(key) if isinstance(snapshot.get(key), list) else []
        if not workers:
            continue
        segments = []
        for worker in workers:
            health, _ = _health(worker)
            objective = " ".join(str(worker.get("objective") or "").split())
            segments.append(
                f"{prefix} {worker.get('task_id') or '?'} {worker.get('role') or '?'}"
                f" · {objective or 'no objective'}"
                f" · {_duration(worker.get('elapsed_seconds'))}"
                f" · {_short(worker.get('model'), 18)}"
                f" · {_short((worker.get('session') or {}).get('id') if isinstance(worker.get('session'), dict) else None, 11)}"
                f" · {health}"
            )
        lead = _ansi(label, tint, color) + ": "
        rendered = lead
        shown = 0
        for segment in segments:
            candidate = rendered + ("  |  " if shown else "") + segment
            reserve = 8 if shown + 1 < len(segments) else 0
            if len(candidate) + reserve > width and shown:
                break
            rendered = candidate
            shown += 1
        if shown < len(segments):
            rendered += f"  |  +{len(segments) - shown}"
        lines.append(_fit(rendered, width))
    if len(lines) == 1:
        lines.append(_ansi("No active T-BAG worker sessions.", DIM, color))
    return lines[:3]


def detail_lines(snapshot: dict[str, Any], *, width: int = 120, color: bool = True) -> list[str]:
    lines = [compact_header(snapshot, width=width, color=color)]
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    phase = snapshot.get("current_phase") if isinstance(snapshot.get("current_phase"), dict) else {}
    lines.append(
        _fit(
            f"Registered work {progress.get('registered_done', 0)}/{progress.get('registered_total', 0)}"
            f" · phases {progress.get('phases_done', 0)}/{progress.get('phases_total', 0)}"
            f" · current {phase.get('phase_id') or '—'} {phase.get('percent', 0):g}%"
            f" · gate {((phase.get('gate') or {}).get('result') if isinstance(phase.get('gate'), dict) else None) or 'pending'}",
            width,
        )
    )
    analysts = snapshot.get("analysts_active") if isinstance(snapshot.get("analysts_active"), list) else []
    grunts = snapshot.get("grunts_active") if isinstance(snapshot.get("grunts_active"), list) else []
    for workers, title, prefix, tint in ((analysts, "ACTIVE ANALYSTS", "◆", MAGENTA), (grunts, "ACTIVE GRUNTS", "●", CYAN)):
        lines.extend(["", _ansi(f"{title} ({len(workers)})", BOLD + tint, color)])
        if not workers:
            lines.append(_ansi("  none", DIM, color))
            continue
        for worker in workers:
            lines.append(_worker_summary(worker, width=width, color=color, prefix=prefix))
            process = worker.get("process") if isinstance(worker.get("process"), dict) else {}
            proc = process.get("worker") if isinstance(process.get("worker"), dict) else {}
            observer = worker.get("observer") if isinstance(worker.get("observer"), dict) else {}
            evidence = (
                f"    proc {'alive' if proc.get('alive') else 'unknown/down'}"
                f" CPU {proc.get('cpu_percent', '?')}%/{_duration(proc.get('cpu_seconds'))}"
                f" · observer {'healthy' if observer.get('healthy') else ('missing' if observer.get('known') is False else 'unhealthy')}"
                f" · log {_duration(worker.get('log_age_seconds'))} ago"
                f" · report {_duration(worker.get('report_age_seconds'))} ago"
            )
            lines.append(_fit(_ansi(evidence, DIM, color), width))
    attention = snapshot.get("attention") if isinstance(snapshot.get("attention"), list) else []
    if attention:
        lines.extend(["", _ansi(f"ATTENTION ({len(attention)})", BOLD + YELLOW, color)])
        for item in attention[:8]:
            lines.append(_fit(f"⚠ {item.get('phase_id') or ''}/{item.get('task_id') or ''} · {item.get('status') or 'attention'} · {item.get('objective') or ''}", width))
    phases = snapshot.get("phases") if isinstance(snapshot.get("phases"), list) else []
    if phases:
        lines.extend(["", _ansi("PHASES", BOLD, color)])
        for item in phases:
            gate = item.get("gate") if isinstance(item.get("gate"), dict) else {}
            mark = "✓" if item.get("complete") else "○"
            lines.append(_fit(f"{mark} {item.get('phase_id')}  {_bar(item.get('percent'), 12)} {item.get('percent', 0):g}%  gate:{gate.get('result') or '—'}", width))
    return lines


def _project_from_claude(payload: dict[str, Any]) -> Path:
    workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    raw = workspace.get("project_dir") or workspace.get("current_dir") or payload.get("cwd") or os.getcwd()
    return Path(str(raw)).resolve()


def render_claude_payload(payload: dict[str, Any], *, width: int | None = None, color: bool | None = None) -> list[str]:
    project = _project_from_claude(payload)
    session_id = str(payload.get("session_id") or "") or None
    if color is None:
        color = not bool(os.environ.get("NO_COLOR"))
    actual_width = _width(width)
    host_model = ((payload.get("model") or {}).get("display_name") if isinstance(payload.get("model"), dict) else None) or "Claude"
    context = ((payload.get("context_window") or {}).get("used_percentage") if isinstance(payload.get("context_window"), dict) else None)
    try:
        snapshot = tbag_status.build_snapshot(project, parent_session_id=session_id)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        suffix = f" · {host_model}" + (f" ctx {_pct(context):g}%" if context is not None else "")
        return [_fit(_ansi("T-BAG ○ no active run", DIM, color) + suffix, actual_width)]
    return claude_status_lines(snapshot, host={"model": host_model, "context_percent": context}, width=actual_width, color=color)


def _snapshot(project_root: Path, run_root: Path | None = None, parent_session_id: str | None = None) -> dict[str, Any]:
    return tbag_status.build_snapshot(project_root.resolve(), run_root=run_root.resolve() if run_root else None, parent_session_id=parent_session_id)


def command_status(args: argparse.Namespace) -> int:
    snapshot = _snapshot(args.project_root, args.run_root, args.parent_session_id)
    for line in detail_lines(snapshot, width=_width(args.width), color=not args.no_color):
        print(line)
    return 0


def command_watch(args: argparse.Namespace) -> int:
    interval = max(0.5, float(args.interval))
    try:
        while True:
            try:
                snapshot = _snapshot(args.project_root, args.run_root, args.parent_session_id)
                lines = detail_lines(snapshot, width=_width(args.width), color=not args.no_color)
            except Exception as exc:  # presentation loop: stay useful across transient rewrites
                lines = [f"T-BAG status unavailable: {exc}"]
            if not args.no_clear:
                sys.stdout.write("\033[2J\033[H")
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.write(_ansi(f"refresh {interval:g}s · Ctrl-C closes display only", DIM, not args.no_color) + "\n")
            sys.stdout.flush()
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def command_claude(args: argparse.Namespace) -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    for line in render_claude_payload(payload if isinstance(payload, dict) else {}, width=args.width, color=not args.no_color):
        print(line)
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--project-root", type=Path, default=Path.cwd())
        p.add_argument("--run-root", type=Path)
        p.add_argument("--parent-session-id")
        p.add_argument("--width", type=int)
        p.add_argument("--no-color", action="store_true")

    status = sub.add_parser("status", help="print one detailed read-only status view")
    common(status); status.set_defaults(func=command_status)
    watch = sub.add_parser("watch", help="refresh the detailed status view in a terminal pane")
    common(watch); watch.add_argument("--interval", type=float, default=2.0); watch.add_argument("--no-clear", action="store_true"); watch.set_defaults(func=command_watch)
    claude = sub.add_parser("claude-statusline", help="render Claude Code statusLine JSON from stdin")
    claude.add_argument("--width", type=int); claude.add_argument("--no-color", action="store_true"); claude.set_defaults(func=command_claude)
    return ap


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"T-BAG status unavailable: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
