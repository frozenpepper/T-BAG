#!/usr/bin/env python3
"""Parse only task-contract fields needed for objective T-BAG mechanics.

No helper here interprets acceptance quality or worker prose. The deterministic layer
may read explicit control fields such as write boundaries and explicit context-loading hints.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from _roles import ALWAYS_PROJECT_WRITER_ROLES


WORKER_SKILL_HEADINGS = (
    "Worker skills",
    "Implementer skills",
    "Reviewer skills",
    "Analyst skills",
    "Verification skills",
)


def _markdown_h2_sections(text: str) -> list[tuple[str, int, int]]:
    """Return level-two headings outside fenced code blocks.

    Briefs often need to quote malformed contracts while diagnosing them. A quoted
    ``## Worker skills`` heading is prose evidence, not control data, so fenced
    regions must be invisible to the mechanical section parser.
    """
    headings: list[tuple[str, int, int]] = []
    offset = 0
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        raw = line.rstrip("\r\n")
        fence_match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", raw)
        if fence_match:
            marker = fence_match.group(1)
            rest = fence_match.group(2)
            marker_kind = marker[0]
            marker_len = len(marker)
            if fence is None:
                fence = (marker_kind, marker_len)
            elif marker_kind == fence[0] and marker_len >= fence[1] and not rest.strip():
                fence = None
            offset += len(line)
            continue
        if fence is None:
            match = re.match(r"^##\s+(.+?)\s*$", raw)
            if match:
                headings.append((match.group(1), offset, offset + len(line)))
        offset += len(line)
    return headings


def markdown_section(text: str, heading: str) -> str:
    headings = _markdown_h2_sections(text)
    target_index = next((i for i, (name, _, _) in enumerate(headings) if name.casefold() == heading.casefold()), None)
    if target_index is None:
        return ""
    _, _, start = headings[target_index]
    end = headings[target_index + 1][1] if target_index + 1 < len(headings) else len(text)
    return re.sub(r"<!--.*?-->", "", text[start:end], flags=re.S).strip()


def _safe_prefixes(text: str, heading: str, *, forbid_dsd: bool = False) -> list[str]:
    section = markdown_section(text, heading)
    if not section or section.strip().upper() == "NONE":
        return []
    result: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("-"):
            raise ValueError(f"{heading} must contain only '- path' bullets or NONE; offending line: {stripped[:120]}")
        raw_value = stripped[1:].strip()
        if not raw_value or raw_value.upper() == "NONE":
            continue
        # Contract paths are either one bare token or one whole backtick-wrapped
        # path.  This rejects natural-language/decorated bullets (for example
        # ``- DELETE `src/a.py``` or ``- Nothing else may change.``) at preflight
        # instead of silently turning prose into a prefix that can never match.
        if raw_value.startswith("`") or raw_value.endswith("`"):
            if len(raw_value) < 2 or not (raw_value.startswith("`") and raw_value.endswith("`")) or "`" in raw_value[1:-1]:
                raise ValueError(f"{heading} entry must be exactly one path, optionally whole backtick-wrapped; offending line: {stripped[:120]}")
            value = raw_value[1:-1]
        else:
            if "`" in raw_value or any(ch.isspace() for ch in raw_value):
                raise ValueError(f"{heading} entry must be exactly one path, optionally whole backtick-wrapped; offending line: {stripped[:120]}")
            value = raw_value
        value = value.replace("\\", "/").rstrip("/")
        if not value or value.upper() == "NONE":
            continue
        # Allowed/fixture entries are path prefixes, not a general glob language.
        # Accept the common directory-tree spelling `path/**` as exactly `path` so
        # every downstream consumer (gate, carry-forward validation, fixtures)
        # shares one canonical prefix semantics rather than reimplementing globbing.
        if value.endswith("/**"):
            value = value[:-3].rstrip("/")
            if not value:
                raise ValueError(f"unsafe {heading} entry: /**")
        if any(token in value for token in ("*", "?", "[")):
            raise ValueError(f"{heading} entries are path prefixes, not globs; only a trailing '/**' tree shorthand is supported: {value}")
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or value in {".", "./"}:
            raise ValueError(f"unsafe {heading} entry: {value}")
        normalized = path.as_posix()
        if forbid_dsd and (normalized in {"TBag", "AnalystAndGrunt"} or normalized.startswith("TBag/") or normalized.startswith("AnalystAndGrunt/")):
            raise ValueError(f"{heading} cannot target TBag/** or legacy AnalystAndGrunt/**")
        result.append(normalized)
    return list(dict.fromkeys(result))


def _bullet_values(text: str, heading: str) -> list[str]:
    section = markdown_section(text, heading)
    if not section or section.strip().upper() == "NONE":
        return []
    out: list[str] = []
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("-"):
            raise ValueError(f"{heading} must contain only bare '- skill-id' bullets or NONE; offending line: {stripped[:120]}")
        value = stripped[1:].strip().strip("`")
        if not value or value.upper() == "NONE":
            continue
        out.append(value)
    return list(dict.fromkeys(out))


def has_explicit_write_restriction(text: str) -> bool:
    """Whether authority supplied an explicit project-write boundary.

    Implementer/Fixer contracts do not need to predict their implementation surface.
    When this section is present, however, it is a real hard restriction; `NONE`
    therefore means no project writes for that task.
    """
    return any(name.casefold() == "allowed source changes" for name, _, _ in _markdown_h2_sections(text))


def allowed_source_changes(text: str) -> list[str]:
    """Return an optional authority-supplied hard write restriction.

    An absent section means no predeclared restriction for inherent writer roles.
    A present `NONE` section is an explicit no-write restriction. Prose elsewhere
    never creates or widens this boundary.
    """
    return _safe_prefixes(text, "Allowed source changes")


def required_worktree_fixtures(text: str) -> list[str]:
    """Explicit project-relative ignored/runtime inputs needed inside this task worktree.

    These are copied for execution/validation only. They are not durable outputs and
    remain outside Git integration provenance.
    """
    return _safe_prefixes(text, "Required worktree fixtures", forbid_dsd=True)


def _safe_skill_ids(text: str, heading: str) -> list[str]:
    tags = _bullet_values(text, heading)
    safe: list[str] = []
    for tag in tags:
        value = tag.strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", value):
            raise ValueError(f"{heading} entries must be bare skill IDs with no description/parenthetical: {value}")
        safe.append(value)
    return list(dict.fromkeys(safe))


def worker_skill_tags(text: str, role: str | None = None) -> list[str]:
    """Reusable worker-skill IDs applicable to one launched role.

    `Worker skills` is role-neutral. Role-specific headings prevent an
    implementation strategy from automatically anchoring an independent Reviewer.
    """
    role = (role or "").lower().replace("_", "-")
    headings = ["Worker skills"]
    if role in {"implementer", "fixer"}:
        headings.append("Implementer skills")
    if role == "reviewer":
        headings.append("Reviewer skills")
    if role in {"goal-planner", "plan-reviewer", "context-reviewer", "planner", "discovery", "phase-surveyor", "recovery", "phase-auditor"}:
        headings.append("Analyst skills")
    if role in {"verification", "evidence-clerk"}:
        headings.append("Verification skills")
    out: list[str] = []
    for heading in headings:
        out.extend(_safe_skill_ids(text, heading))
    return list(dict.fromkeys(out))


def declared_worker_skill_tags(text: str) -> list[str]:
    """All skill IDs declared anywhere in a brief, independent of launch role.

    Preflight uses this wider view because one task brief can later be consumed by
    several lifecycle roles (for example Implementer, Reviewer and Fixer). Launch
    still uses ``worker_skill_tags`` so each worker receives only its own hints.
    """
    out: list[str] = []
    for heading in WORKER_SKILL_HEADINGS:
        out.extend(_safe_skill_ids(text, heading))
    return list(dict.fromkeys(out))

def role_writes_project(role: str, text: str) -> bool:
    """Whether this exact role+contract may mutate accepted project state."""
    role = role.lower().replace("_", "-")
    if role in ALWAYS_PROJECT_WRITER_ROLES:
        return True
    if role == "verification":
        return bool(allowed_source_changes(text))
    # Evidence Clerk is always project-read-only. It may write T-BAG attempt artifacts,
    # never project state. Project documentation updates are ordinary writer tasks.
    return False


def validate_role_contract(role: str, text: str) -> list[str]:
    """Reserved for objective role/contract contradictions; currently none."""
    return []
