#!/usr/bin/env python3
"""OpenCode host-version and TUI-config compatibility helpers.

The server adapter is stable across supported hosts; only the optional TUI
companion differs. These helpers edit only the top-level ``plugin`` value in
`tui.json`/`tui.jsonc`, preserving unrelated owner text and comments.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

V1_SPEC = "./plugins/tbag-status-tui-v1.tsx"
LEGACY_V1_SPECS = ("./plugins/tbag-status-tui.tsx",)


def detect_opencode_version() -> tuple[str | None, int | None]:
    try:
        text = subprocess.check_output(
            ["opencode", "--version"], text=True, stderr=subprocess.STDOUT, timeout=10
        ).strip()
    except Exception:
        return None, None
    for raw in text.replace("/", " ").split():
        token = raw.strip().lstrip("vV")
        parts = token.split(".")
        if parts and parts[0].isdigit() and (len(parts) == 1 or parts[1].isdigit()):
            return token, int(parts[0])
    return text or None, None


def tui_config_path(project_root: Path) -> Path:
    root = project_root / ".opencode"
    jsonc = root / "tui.jsonc"
    return jsonc if jsonc.exists() else root / "tui.json"


def _skip_trivia(text: str, index: int) -> int:
    n = len(text)
    while index < n:
        if text[index].isspace():
            index += 1
            continue
        if text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = n if newline < 0 else newline + 1
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            index = end + 2
            continue
        break
    return index


def _string_end(text: str, index: int) -> int:
    if index >= len(text) or text[index] != '"':
        raise ValueError("expected JSON string")
    index += 1
    while index < len(text):
        ch = text[index]
        if ch == "\\":
            index += 2
            continue
        if ch == '"':
            return index + 1
        index += 1
    raise ValueError("unterminated JSON string")


def _value_end(text: str, index: int) -> int:
    index = _skip_trivia(text, index)
    if index >= len(text):
        raise ValueError("missing JSONC value")
    if text[index] == '"':
        return _string_end(text, index)
    if text[index] not in "[{":
        i = index
        while i < len(text) and text[i] not in ",}]\n\r":
            i += 1
        return i
    stack = [text[index]]
    i = index + 1
    while i < len(text):
        if text.startswith("//", i):
            newline = text.find("\n", i + 2)
            i = len(text) if newline < 0 else newline + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            i = end + 2
            continue
        ch = text[i]
        if ch == '"':
            i = _string_end(text, i)
            continue
        if ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            opener = stack.pop()
            if (opener, ch) not in {("[", "]"), ("{", "}")}:
                raise ValueError("mismatched JSONC delimiters")
            if not stack:
                return i + 1
        i += 1
    raise ValueError("unterminated JSONC value")


def _root_property(text: str, name: str) -> tuple[int, int] | None:
    i = _skip_trivia(text, 0)
    if i >= len(text) or text[i] != "{":
        raise ValueError("TUI config root must be an object")
    i += 1
    while True:
        i = _skip_trivia(text, i)
        if i >= len(text):
            raise ValueError("unterminated TUI config")
        if text[i] == "}":
            return None
        key_start = i
        key_end = _string_end(text, key_start)
        key = json.loads(text[key_start:key_end])
        i = _skip_trivia(text, key_end)
        if i >= len(text) or text[i] != ":":
            raise ValueError("malformed TUI config property")
        start = _skip_trivia(text, i + 1)
        end = _value_end(text, start)
        if key == name:
            return start, end
        i = _skip_trivia(text, end)
        if i < len(text) and text[i] == ",":
            i += 1
            continue
        if i < len(text) and text[i] == "}":
            return None
        raise ValueError("malformed TUI config object")


def _root_close_info(text: str) -> tuple[int, bool, bool]:
    i = _skip_trivia(text, 0)
    if i >= len(text) or text[i] != "{":
        raise ValueError("TUI config root must be an object")
    i += 1
    has_members = False
    trailing_comma = False
    while True:
        i = _skip_trivia(text, i)
        if i >= len(text):
            raise ValueError("unterminated TUI config")
        if text[i] == "}":
            return i, has_members, trailing_comma
        key_end = _string_end(text, i)
        i = _skip_trivia(text, key_end)
        if i >= len(text) or text[i] != ":":
            raise ValueError("malformed TUI config property")
        end = _value_end(text, i + 1)
        has_members = True
        i = _skip_trivia(text, end)
        if i < len(text) and text[i] == ",":
            trailing_comma = True
            i += 1
            probe = _skip_trivia(text, i)
            if probe < len(text) and text[probe] == "}":
                return probe, has_members, True
            trailing_comma = False
            continue
        if i < len(text) and text[i] == "}":
            return i, has_members, False
        raise ValueError("malformed TUI config object")


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            if end < 0:
                break
            out.append("\n")
            i = end + 1
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise ValueError("unterminated JSONC block comment")
            out.append(" " * (end + 2 - i))
            i = end + 2
            continue
        if text[i] == '"':
            end = _string_end(text, i)
            out.append(text[i:end])
            i = end
            continue
        out.append(text[i])
        i += 1
    cleaned = "".join(out)
    chars = list(cleaned)
    i = 0
    while i < len(chars):
        if chars[i] == '"':
            i = _string_end(cleaned, i)
            continue
        if chars[i] == ",":
            j = i + 1
            while j < len(chars) and chars[j].isspace():
                j += 1
            if j < len(chars) and chars[j] in "]}":
                chars[i] = " "
        i += 1
    return "".join(chars)


def _entry_spec_text(text: str) -> str | None:
    value = json.loads(_strip_jsonc(text))
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def _array_entries(text: str, start: int, end: int) -> list[tuple[int, int, int | None]]:
    if text[start] != "[" or text[end - 1] != "]":
        raise ValueError("expected JSONC array")
    entries: list[tuple[int, int, int | None]] = []
    i = start + 1
    while True:
        i = _skip_trivia(text, i)
        if i >= end:
            raise ValueError("unterminated JSONC array")
        if text[i] == "]":
            return entries
        value_start = i
        value_end = _value_end(text, value_start)
        after = _skip_trivia(text, value_end)
        comma = after if after < end and text[after] == "," else None
        entries.append((value_start, value_end, comma))
        if comma is not None:
            i = comma + 1
            continue
        after = _skip_trivia(text, value_end)
        if after < end and text[after] == "]":
            return entries
        raise ValueError("malformed JSONC array")


def _plugin_entries(text: str) -> tuple[tuple[int, int] | None, list[tuple[int, int, int | None]]]:
    value = _root_property(text, "plugin")
    if value is None:
        return None, []
    start, end = value
    return value, _array_entries(text, start, end)


def _remove_tui_plugin_once(project_root: Path, spec: str) -> tuple[bool, Path | None]:
    path = tui_config_path(project_root)
    if not path.exists():
        return False, None
    text = path.read_text(encoding="utf-8")
    value, entries = _plugin_entries(text)
    if value is None:
        return False, path
    match_index = None
    for index, (start, end, _comma) in enumerate(entries):
        if _entry_spec_text(text[start:end]) == spec:
            match_index = index
            break
    if match_index is None:
        return False, path
    start, end, comma = entries[match_index]
    if comma is not None:
        cut_start, cut_end = start, comma + 1
    elif match_index > 0 and entries[match_index - 1][2] is not None:
        cut_start, cut_end = entries[match_index - 1][2], end
    else:
        cut_start, cut_end = start, end
    path.write_text(text[:cut_start] + text[cut_end:], encoding="utf-8")
    return True, path


def ensure_tui_plugin(project_root: Path, spec: str = V1_SPEC) -> tuple[bool, Path]:
    changed = False
    if spec == V1_SPEC:
        for legacy_spec in LEGACY_V1_SPECS:
            removed, _ = _remove_tui_plugin_once(project_root, legacy_spec)
            changed |= removed

    path = tui_config_path(project_root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"$schema": "https://opencode.ai/tui.json", "plugin": [[spec, {}]]}, indent=2) + "\n",
            encoding="utf-8",
        )
        return True, path

    text = path.read_text(encoding="utf-8")
    value, entries = _plugin_entries(text)
    if any(_entry_spec_text(text[a:b]) == spec for a, b, _ in entries):
        return changed, path
    entry = json.dumps([spec, {}])
    if value is None:
        close, has_members, trailing_comma = _root_close_info(text)
        prefix = "" if not has_members or trailing_comma else ","
        replacement = text[:close] + f'{prefix}\n  "plugin": [\n    {entry}\n  ]\n' + text[close:]
    else:
        start, end = value
        close = end - 1
        prefix = "" if not entries or entries[-1][2] is not None else ","
        replacement = text[:close] + f'{prefix}\n    {entry}\n  ' + text[close:]
    path.write_text(replacement, encoding="utf-8")
    return True, path


def remove_tui_plugin(project_root: Path, spec: str = V1_SPEC) -> tuple[bool, Path | None]:
    specs = (spec, *LEGACY_V1_SPECS) if spec == V1_SPEC else (spec,)
    changed = False
    path: Path | None = None
    for candidate in specs:
        removed, current_path = _remove_tui_plugin_once(project_root, candidate)
        changed |= removed
        if current_path is not None:
            path = current_path
    return changed, path
