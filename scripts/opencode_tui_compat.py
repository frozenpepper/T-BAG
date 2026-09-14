#!/usr/bin/env python3
"""OpenCode host-version and TUI-config compatibility helpers.

The server adapter is stable across supported hosts; only the optional TUI
companion differs.  These helpers deliberately edit only the top-level
``plugin`` value in tui.json/jsonc so unrelated owner config and comments stay
byte-preserved.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

V1_SPEC = "./plugins/tbag-status-tui-v1.tsx"


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
            return n if newline < 0 else _skip_trivia(text, newline + 1)
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
    # JSONC permits trailing commas. Remove only commas immediately before a
    # closing array/object delimiter in the comment-free projection.
    chars = list(cleaned)
    i = 0
    while i < len(chars):
        if chars[i] in "]}":
            j = i - 1
            while j >= 0 and chars[j].isspace():
                j -= 1
            if j >= 0 and chars[j] == ",":
                chars[j] = " "
        i += 1
    return "".join(chars)


def _plugin_specs(text: str) -> list[Any]:
    value = _root_property(text, "plugin")
    if value is None:
        return []
    parsed = json.loads(_strip_jsonc(text[value[0]:value[1]]))
    if not isinstance(parsed, list):
        raise ValueError("tui.json plugin must be an array")
    return parsed


def _entry_spec(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0]
    return None


def ensure_tui_plugin(project_root: Path, spec: str = V1_SPEC) -> tuple[bool, Path]:
    path = tui_config_path(project_root)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"$schema": "https://opencode.ai/tui.json", "plugin": [[spec, {}]]}, indent=2) + "\n",
            encoding="utf-8",
        )
        return True, path

    text = path.read_text(encoding="utf-8")
    if any(_entry_spec(row) == spec for row in _plugin_specs(text)):
        return False, path
    value = _root_property(text, "plugin")
    entry = json.dumps([spec, {}])
    if value is None:
        root_end = _value_end(text, _skip_trivia(text, 0)) - 1
        before = text[:root_end].rstrip()
        comma = "" if before.endswith("{") else ","
        replacement = f'{before}{comma}\n  "plugin": [\n    {entry}\n  ]\n' + text[root_end:]
    else:
        start, end = value
        if text[start] != "[":
            raise ValueError("tui.json plugin must be an array")
        close = end - 1
        j = close - 1
        while j > start and text[j].isspace():
            j -= 1
        empty = j == start
        trailing_comma = (not empty and text[j] == ",")
        prefix = "" if empty or trailing_comma else ","
        replacement = text[:close] + f'{prefix}\n    {entry}\n  ' + text[close:]
    path.write_text(replacement, encoding="utf-8")
    return True, path


def remove_tui_plugin(project_root: Path, spec: str = V1_SPEC) -> tuple[bool, Path | None]:
    path = tui_config_path(project_root)
    if not path.exists():
        return False, None
    text = path.read_text(encoding="utf-8")
    value = _root_property(text, "plugin")
    if value is None:
        return False, path
    start, end = value
    rows = _plugin_specs(text)
    if not any(_entry_spec(row) == spec for row in rows):
        return False, path
    kept = [row for row in rows if _entry_spec(row) != spec]
    indent = "  "
    rendered = json.dumps(kept, indent=2)
    rendered = rendered.replace("\n", "\n" + indent)
    path.write_text(text[:start] + rendered + text[end:], encoding="utf-8")
    return True, path
