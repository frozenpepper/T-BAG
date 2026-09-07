#!/usr/bin/env python3
"""Validate one numbered worker-rules revision.

T-BAG intentionally does not checksum protocol/control files. A rules
revision is a numbered directory created once and treated as historical context;
verification checks structural identity and frozen path containment, not content
digests.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PROTOCOL_NAMES = (
    "COMMON.md", "PLAN-AUTHORING.md", "ANALYST-ESCALATION.md",
    "roles/dsd-goal-planner/SKILL.md", "roles/dsd-plan-reviewer/SKILL.md", "roles/dsd-context-reviewer/SKILL.md",
    "roles/dsd-planner/SKILL.md", "roles/dsd-discovery/SKILL.md",
    "roles/dsd-phase-surveyor/SKILL.md", "roles/dsd-implementer/SKILL.md",
    "roles/dsd-fixer/SKILL.md", "roles/dsd-reviewer/SKILL.md",
    "roles/dsd-verification/SKILL.md", "roles/dsd-recovery/SKILL.md",
    "roles/dsd-phase-auditor/SKILL.md", "roles/dsd-evidence-clerk/SKILL.md",
)
MANIFEST_FORMAT = "dsd-worker-rules-manifest-v2.2"
REVISION_DIR_RE = re.compile(r"^r([0-9]{4,})$")
SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def rules_revisions(run_root: Path) -> list[Path]:
    """Return completed numbered WORKER_RULES paths in numeric revision order."""
    root = run_root.resolve() / "worker-rules"
    found: list[tuple[int, Path]] = []
    if not root.is_dir():
        return []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = REVISION_DIR_RE.fullmatch(child.name)
        if not match or int(match.group(1)) < 1:
            continue
        rules = child / "WORKER_RULES.md"
        if rules.is_file() and not rules.is_symlink():
            found.append((int(match.group(1)), rules.resolve()))
    return [path for _, path in sorted(found, key=lambda item: item[0])]


def _require_within(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} escapes worker-rules revision: {resolved}") from exc
    return resolved


def verify_snapshot(rules_path: Path) -> dict:
    raw_rules = rules_path.absolute()
    if raw_rules.is_symlink():
        raise ValueError(f"worker rules must be a frozen regular file, not a symlink: {raw_rules}")
    rules_path = raw_rules.resolve()
    if rules_path.name != "WORKER_RULES.md" or not rules_path.is_file():
        raise ValueError(f"worker rules missing/invalid: {rules_path}")
    revision_root = rules_path.parent
    revision_match = REVISION_DIR_RE.fullmatch(revision_root.name)
    if not revision_match or int(revision_match.group(1)) < 1:
        raise ValueError(f"worker-rules revision directory must be rNNNN+: {revision_root}")
    revision_number = int(revision_match.group(1))

    manifest_path = revision_root / "MANIFEST.json"
    if manifest_path.is_symlink():
        raise ValueError(f"worker-rules manifest must be a frozen regular file, not a symlink: {manifest_path}")
    if not manifest_path.is_file():
        raise ValueError(f"worker-rules manifest missing: {manifest_path}")
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if data.get("format") != MANIFEST_FORMAT:
        raise ValueError(f"unsupported worker-rules manifest: {data.get('format')!r}")
    if data.get("revision") != revision_number:
        raise ValueError(
            f"worker-rules manifest revision mismatch: directory={revision_number} manifest={data.get('revision')!r}"
        )

    protocol_dir = revision_root / "protocol"
    declared_protocol = data.get("protocol_files", list(PROTOCOL_NAMES))
    if not isinstance(declared_protocol, list) or any(not isinstance(name, str) or not name or name.startswith("/") or ".." in Path(name).parts for name in declared_protocol):
        raise ValueError("worker-rules protocol_files must be safe relative paths")
    missing_core = [name for name in PROTOCOL_NAMES if name not in declared_protocol]
    if missing_core:
        raise ValueError("worker-rules protocol_files omitted required core entries: " + ", ".join(missing_core))
    missing = [str(protocol_dir / name) for name in declared_protocol if not (protocol_dir / name).is_file()]
    if missing:
        raise ValueError("worker-rules protocol incomplete: " + ", ".join(missing))
    for name in declared_protocol:
        entry = protocol_dir / name
        if entry.is_symlink():
            raise ValueError(f"worker-rules protocol entry must be a frozen regular file, not a symlink: {entry}")
        _require_within(entry, protocol_dir, "protocol snapshot")

    authority_root = revision_root / "authority"
    authority_files = data.get("authority_files", [])
    if not isinstance(authority_files, list):
        raise ValueError("worker-rules authority_files must be an array")
    frozen_authority: list[str] = []
    for raw in authority_files:
        raw_path = Path(str(raw))
        if raw_path.is_symlink():
            raise ValueError(f"worker-rules authority snapshot must be a frozen regular file, not a symlink: {raw_path}")
        path = _require_within(raw_path, authority_root, "authority snapshot")
        if not path.is_file():
            raise ValueError(f"worker-rules authority snapshot incomplete: {path}")
        frozen_authority.append(str(path))

    authority_plan = data.get("authority_plan")
    if authority_plan is not None:
        raw_plan = Path(str(authority_plan))
        if raw_plan.is_symlink():
            raise ValueError(f"worker-rules authority plan must be a frozen regular file, not a symlink: {raw_plan}")
        plan_path = _require_within(raw_plan, authority_root, "authority plan")
        if not plan_path.is_file():
            raise ValueError(f"worker-rules authority plan missing: {plan_path}")
        authority_plan = str(plan_path)

    project_protocol = data.get("project_protocol")
    if project_protocol is not None:
        expected = (revision_root / "project-context" / "PROJECT-PROTOCOL.md").resolve()
        actual = Path(str(project_protocol)).resolve()
        if actual != expected:
            raise ValueError(f"project protocol must be the frozen revision copy: {expected}; got {actual}")
        if (revision_root / "project-context" / "PROJECT-PROTOCOL.md").is_symlink():
            raise ValueError("project protocol snapshot must be a frozen regular file, not a symlink")
        _require_within(revision_root / "project-context" / "PROJECT-PROTOCOL.md", revision_root / "project-context", "project protocol snapshot")
        if not actual.is_file():
            raise ValueError(f"project protocol snapshot missing: {actual}")
        project_protocol = str(actual)

    catalog_raw = data.get("worker_skill_catalog")
    expected_catalog = (revision_root / "WORKER-SKILL-CATALOG.md").resolve()
    if catalog_raw is None:
        raise ValueError("worker-rules worker_skill_catalog is required")
    catalog = Path(str(catalog_raw)).resolve()
    if catalog != expected_catalog:
        raise ValueError(f"worker skill catalog must be the frozen revision copy: {expected_catalog}; got {catalog}")
    raw_catalog = revision_root / "WORKER-SKILL-CATALOG.md"
    if raw_catalog.is_symlink() or not raw_catalog.is_file():
        raise ValueError("worker skill catalog must be a frozen regular file, not a symlink")
    _require_within(raw_catalog, revision_root, "worker skill catalog")

    skills = data.get("worker_skills", {})
    if not isinstance(skills, dict):
        raise ValueError("worker-rules worker_skills must be an object")
    frozen_skills: dict[str, str] = {}
    for raw_name, raw_path in skills.items():
        name = str(raw_name)
        if not SKILL_ID_RE.fullmatch(name):
            raise ValueError(f"unsafe worker-skill id in manifest: {name!r}")
        expected = (revision_root / "worker-skills" / name / "SKILL.md").resolve()
        actual = Path(str(raw_path)).resolve()
        if actual != expected:
            raise ValueError(f"worker skill {name!r} must be the frozen revision copy: {expected}; got {actual}")
        skill_root = revision_root / "worker-skills" / name
        raw_expected = skill_root / "SKILL.md"
        if raw_expected.is_symlink():
            raise ValueError(f"worker skill {name!r} snapshot must be a frozen regular file, not a symlink")
        _require_within(raw_expected, revision_root / "worker-skills", f"worker skill {name!r} snapshot")
        if not actual.is_file():
            raise ValueError(f"worker-skill snapshot incomplete: {name}: {actual}")
        for entry in skill_root.rglob("*"):
            if entry.is_symlink():
                raise ValueError(f"worker skill {name!r} bundle must not contain symlinks: {entry}")
            _require_within(entry, skill_root, f"worker skill {name!r} bundle")
        frozen_skills[name] = str(actual)

    run_rules = data.get("run_rules", [])
    if not isinstance(run_rules, list) or any(not isinstance(item, str) for item in run_rules):
        raise ValueError("worker-rules run_rules must be an array of strings")

    return {
        "format": data.get("format"),
        "revision": revision_number,
        "path": str(rules_path),
        "manifest": str(manifest_path),
        "protocol_dir": str(protocol_dir),
        "project_protocol": project_protocol,
        "worker_skill_catalog": str(catalog),
        "worker_skills": frozen_skills,
        "run_rules": list(run_rules),
        "authority_plan": authority_plan,
        "authority_files": frozen_authority,
    }
