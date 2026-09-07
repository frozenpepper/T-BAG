#!/usr/bin/env python3
"""Worker role registry for T-BAG."""
from __future__ import annotations

ROLE_SKILLS = {
    "goal-planner": "roles/dsd-goal-planner/SKILL.md",
    "plan-reviewer": "roles/dsd-plan-reviewer/SKILL.md",
    "context-reviewer": "roles/dsd-context-reviewer/SKILL.md",
    "planner": "roles/dsd-planner/SKILL.md",
    "discovery": "roles/dsd-discovery/SKILL.md",
    "phase-surveyor": "roles/dsd-phase-surveyor/SKILL.md",
    "implementer": "roles/dsd-implementer/SKILL.md",
    "fixer": "roles/dsd-fixer/SKILL.md",
    "reviewer": "roles/dsd-reviewer/SKILL.md",
    "verification": "roles/dsd-verification/SKILL.md",
    "recovery": "roles/dsd-recovery/SKILL.md",
    "phase-auditor": "roles/dsd-phase-auditor/SKILL.md",
    "evidence-clerk": "roles/dsd-evidence-clerk/SKILL.md",
}

ROLE_NAMES = tuple(ROLE_SKILLS)
ALWAYS_PROJECT_WRITER_ROLES = frozenset({"implementer", "fixer"})
CONDITIONALLY_WRITING_ROLES = frozenset({"verification"})
ALWAYS_READ_ONLY_ROLES = frozenset(set(ROLE_NAMES) - set(ALWAYS_PROJECT_WRITER_ROLES) - set(CONDITIONALLY_WRITING_ROLES))

DEFAULT_TIER = {
    "goal-planner": "analyst",
    "plan-reviewer": "analyst",
    "context-reviewer": "analyst",
    "planner": "analyst",
    "discovery": "analyst",
    "phase-surveyor": "analyst",
    "reviewer": "grunt",
    "phase-auditor": "analyst",
    "recovery": "analyst",
    "implementer": "grunt",
    "fixer": "grunt",
    "verification": "grunt",
    "evidence-clerk": "grunt",
}

ANALYST_ROLES = frozenset(name for name, tier in DEFAULT_TIER.items() if tier == "analyst")

TECHNICAL_QUALITY_ROLES = frozenset(set(ROLE_NAMES) - {"evidence-clerk", "context-reviewer"})

# Escalation policy belongs to the orchestrator/control plane, not worker roles.
# Workers only report ESCALATE; the current tier determines the next authority tier.
ESCALATION_LADDER = {"grunt": "analyst", "analyst": "human"}
