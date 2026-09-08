import json, sys, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/"scripts"
sys.path.insert(0,str(SCRIPTS))


class DocsTests(unittest.TestCase):
    def test_top_level_skill_frontmatter_has_required_discovery_fields(self):
        text=(ROOT/"SKILL.md").read_text()
        self.assertTrue(text.startswith("---\n"))
        front=text.split("---",2)[1]
        self.assertIn("\nname: t-bag\n", "\n"+front+"\n")
        self.assertIn("\ndescription:", "\n"+front+"\n")
        self.assertNotIn("\nsummary:", "\n"+front+"\n")

    def test_document_architecture_is_compact_and_single_owner(self):
        budgets={
            "SKILL.md":6500,
            "PROMPTS.md":6500,
            "README.md":5000,
            "worker/COMMON.md":4000,
            "worker/QUALITY.md":3500,
            "worker/PLAN-AUTHORING.md":4000,
            "WORKSPACE.md":10000,
            "CONTEXT.md":5500,
            "HARNESS.md":2200,
        }
        for rel,limit in budgets.items():
            size=(ROOT/rel).stat().st_size
            self.assertLessEqual(size,limit,f"{rel} grew to {size} bytes; move detail to its owning layer instead of duplicating it")
        for role in (ROOT/"worker"/"roles").glob("*/SKILL.md"):
            self.assertLessEqual(role.stat().st_size,3000,f"role mandate is no longer concise: {role}")
        hot=(ROOT/"SKILL.md").read_text(); readme=(ROOT/"README.md").read_text()
        self.assertIn("## Instruction architecture",hot)
        self.assertIn("`README.md` is the documentation map",hot)
        self.assertIn("| Parent/orchestration behavior | `SKILL.md` |",readme)
        self.assertNotIn("`worker/QUALITY.md` — shared deep technical reasoning method",hot)


    def test_compaction_orientation_is_single_owned_and_reconcile_first(self):
        checkpoint=(SCRIPTS/"context_checkpoint.py").read_text()
        harness=(ROOT/"HARNESS.md").read_text()
        opencode=(ROOT/"OPENCODE.md").read_text()
        self.assertFalse((ROOT/"COMPACTION.md").exists())
        self.assertIn("Execution truth remains `run.json` plus task-local state",harness)
        self.assertIn("reconcile-run",harness)
        self.assertNotIn("checkpoint-*.json",checkpoint)
        self.assertNotIn("OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS",harness)
        self.assertNotIn("OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS",opencode)
        self.assertIn("tbag_follow",opencode)

    def test_prompts_is_a_command_cookbook_not_duplicate_policy_manual(self):
        text=(ROOT/"PROMPTS.md").read_text()
        self.assertIn("Commands only.",text)
        for forbidden in ("## Non-negotiable boundaries","## Engineering depth","## Quality bar","## Parent loop"):
            self.assertNotIn(forbidden,text)
        self.assertIn("reconcile-run",text)
        self.assertIn("register-plan",text)
        self.assertIn("dsd_attempt.py launch",text)
        self.assertIn("dsd_task.py review",text)
        self.assertIn("dsd_workspace.py integrate",text)

    def test_worker_doctrine_is_composed_not_repeated(self):
        common=(ROOT/"worker/COMMON.md").read_text()
        quality=(ROOT/"worker/QUALITY.md").read_text()
        launch=(ROOT/"scripts/render_worker_prompt.py").read_text()
        prep=(ROOT/"scripts/prepare_worker_rules.py").read_text()
        self.assertIn("Acceptance criteria are frozen for the attempt",common)
        self.assertIn("BLOCKED: inconsistent baseline",common)
        self.assertIn("production-grade, bounded by authority",quality)
        self.assertIn("object-oriented design",quality)
        self.assertIn("competing explanation",quality)
        self.assertIn('"QUALITY.md": "worker/QUALITY.md"',prep)
        self.assertIn('quality_candidate = protocol / "QUALITY.md"',launch)
        self.assertNotIn("Quality bar: production-grade",launch)
        self.assertNotIn("Acceptance integrity:",launch)
        self.assertNotIn("Review mandate:",launch)

    def test_evidence_clerk_remains_clerical(self):
        text=(ROOT/"worker/roles/dsd-evidence-clerk/SKILL.md").read_text()
        self.assertIn("Do **not** perform engineering diagnosis",text)
        launch=(ROOT/"scripts/render_worker_prompt.py").read_text()
        self.assertIn("TECHNICAL_QUALITY_ROLES",launch)

    def test_roles_keep_only_distinct_mandates(self):
        reviewer=(ROOT/"worker/roles/dsd-reviewer/SKILL.md").read_text()
        discovery=(ROOT/"worker/roles/dsd-discovery/SKILL.md").read_text()
        implementer=(ROOT/"worker/roles/dsd-implementer/SKILL.md").read_text()
        planner=(ROOT/"worker/roles/dsd-planner/SKILL.md").read_text()
        verifier=(ROOT/"worker/roles/dsd-verification/SKILL.md").read_text()
        self.assertIn("fresh acceptance firewall",reviewer)
        self.assertIn("stopping after the first concrete defect",reviewer)
        self.assertIn("causal model",discovery)
        self.assertIn("smallest **complete** change",implementer)
        self.assertIn("interaction contracts",planner)
        self.assertIn("Follow-up obligations",reviewer)
        self.assertIn("already binds this triage task",planner)
        self.assertIn("named predicate through the real mechanism",verifier)
        for text in (reviewer,discovery,implementer,planner,verifier):
            self.assertIn("QUALITY.md",text)

    def test_acceptance_truth_and_feedback_latency_are_owned_at_the_right_layers(self):
        common=(ROOT/"worker/COMMON.md").read_text()
        goal=(ROOT/"worker/roles/dsd-goal-planner/SKILL.md").read_text()
        planner=(ROOT/"worker/roles/dsd-planner/SKILL.md").read_text()
        surveyor=(ROOT/"worker/roles/dsd-phase-surveyor/SKILL.md").read_text()
        prereg=(ROOT/"worker/skills/preregistered-acceptance/SKILL.md").read_text()
        self.assertIn("Evidence being accepted/recorded never means the measured predicate passed",common)
        self.assertIn("high-value integration feedback",goal)
        self.assertIn("feedback critical path",planner)
        self.assertNotIn("learning ladder",goal.lower())
        self.assertIn("control-plane progress",surveyor)
        self.assertIn("cannot be laundered into PASS",prereg)

    def test_workspace_economy_excludes_ambient_untracked_and_uses_shared_readonly_view(self):
        workspace=(SCRIPTS/"dsd_workspace.py").read_text()
        hot=(ROOT/"SKILL.md").read_text()
        lifecycle=(ROOT/"WORKSPACE.md").read_text()
        self.assertNotIn("copy_untracked",workspace)
        self.assertIn('"--untracked-files=no"',workspace)
        self.assertIn("shared frozen project view",hot)
        self.assertIn("Ambient untracked/ignored files",lifecycle)
        self.assertIn("reverse-checked before `integrated`",lifecycle)
        self.assertIn("even when `.gitignore` hides them",lifecycle)

    def test_parent_algorithm_keeps_technical_work_out_of_parent(self):
        hot=(ROOT/"SKILL.md").read_text()
        self.assertIn("Parent loop",hot)
        self.assertIn("Parent never authors or repairs technical plans",hot)
        self.assertIn("Keep unresolved root cause/architecture with Analysts",hot)
        self.assertIn("fresh Reviewer owns task acceptance",hot)
        self.assertIn("Grunt → Analyst",hot)
        self.assertIn("Analyst → Human",hot)
        self.assertNotIn("DECISION_REQUIRED",hot)

    def test_owner_reporting_contract_is_short_and_self_contained(self):
        hot=(ROOT/"SKILL.md").read_text()
        self.assertIn("Owner communication",hot)
        self.assertIn("Status; Decisions/blockers; Material outcomes; Running now; Backlog",hot)
        self.assertIn("Never sell task counts as progress",hot)
        prompts=(ROOT/"PROMPTS.md").read_text(); self.assertIn("Owner-requested status",prompts); self.assertIn("do not shadow-review",prompts)

    def test_parent_harness_wake_contract_is_canonical_in_opencode(self):
        hot=(ROOT/"SKILL.md").read_text(); harness=(ROOT/"HARNESS.md").read_text(); oc=(ROOT/"OPENCODE.md").read_text()
        self.assertIn("One supervision primitive",harness)
        self.assertIn("degrade conversation-first",harness)
        self.assertIn("`OPENCODE.md` is the sole protocol",hot)
        self.assertIn("normal detached core `launch`, immediately call `tbag_follow`",hot)
        self.assertIn("never run core `follow`",hot)
        self.assertIn("The only required custom tool is **`tbag_follow`**",oc)
        self.assertIn("Always make this call",oc); self.assertIn("already_armed:true",oc)
        self.assertIn("Canonical OpenCode loop",oc)
        self.assertIn("installer proves the **file on disk**, not the live OpenCode tool registry",oc)
        self.assertIn("`reconcile-run.live_attempts`",oc)
        self.assertIn("end the parent turn",oc)
        self.assertIn("in-memory wake bit",oc)
        self.assertIn("never polls idleness",oc)
        self.assertIn("older follow-only project adapters remain compatible",oc)
        self.assertNotIn("OPENCODE_EXPERIMENTAL_BACKGROUND_SUBAGENTS",oc)
        self.assertNotIn("background:true",oc)
        self.assertNotIn("tbag_launch",oc)

    def test_current_opencode_authority_never_requires_retired_launch_tool(self):
        active=(
            "SKILL.md", "HARNESS.md", "OPENCODE.md", "PROMPTS.md", "CONFIG.md",
            "worker-cli/OPENCODE.md", "scripts/detect_harness.py",
            "scripts/install_harness_adapter.py", "adapters/opencode/tbag.js",
        )
        for rel in active:
            self.assertNotIn("tbag_launch",(ROOT/rel).read_text(),rel)

    def test_long_running_attempts_remain_inspectable(self):
        hot=(ROOT/"SKILL.md").read_text(); prompts=(ROOT/"PROMPTS.md").read_text()
        self.assertIn("Every live attempt must have the selected harness observer armed",hot)
        self.assertIn("liveness, not semantic progress",hot)
        self.assertIn("elapsed/report age",prompts)
        self.assertIn("progress unknown",prompts)
        self.assertIn("2h for Grunts and 6h for Analysts",prompts)
        self.assertIn("dsd_attempt.py inspect",prompts)
        self.assertIn("detached core launch → immediate `tbag_follow`",prompts)
        self.assertIn("tbag_follow",(ROOT/"OPENCODE.md").read_text())

    def test_context_composition_document_includes_shared_quality_layer(self):
        text=(ROOT/"CONTEXT.md").read_text()
        self.assertIn("shared `QUALITY.md`",text)
        self.assertIn("one role skill",text)
        self.assertIn("only role-applicable task-selected skills",text)

    def test_plan_authoring_is_mechanical_and_minimum_sufficient(self):
        text=(ROOT/"worker/PLAN-AUTHORING.md").read_text()
        self.assertIn("mechanical contract",text)
        self.assertIn("minimum-sufficient",text)
        self.assertIn("preflight-plan",text)
        self.assertIn("bare `- skill-id`",text)
        self.assertIn("accepted-but-red",text.lower())
        self.assertIn("already bound to its exact finding IDs",text)

    def test_specialist_proof_skills_remain_focused(self):
        self.assertIn("break → observe RED → restore → observe GREEN",(ROOT/"worker/skills/positive-control/SKILL.md").read_text())
        self.assertIn("first production divergence",(ROOT/"worker/skills/llm-boundary/SKILL.md").read_text())
        self.assertIn("real production entry point",(ROOT/"worker/skills/preregistered-acceptance/SKILL.md").read_text())

    def test_removed_global_orchestration_scripts(self):
        for name in ("dsd_state.py","dsd_parallel.py","render_task_contract.py"):
            self.assertFalse((SCRIPTS/name).exists())
        self.assertFalse((ROOT/"templates/task-contract-spec.example.json").exists())

    def test_public_environment_names_have_no_legacy_aliases(self):
        checkpoint=(SCRIPTS/"context_checkpoint.py").read_text(); harness=(SCRIPTS/"detect_harness.py").read_text(); task=(SCRIPTS/"dsd_task.py").read_text()
        self.assertIn("TBAG_RUN_ROOT",checkpoint)
        self.assertIn("TBAG_ORCHESTRATOR_HARNESS",harness)
        for obsolete in ("AG_RUN_ROOT","DSD_RUN_ROOT","DSD_ORCHESTRATOR_HARNESS","DSD_PROJECT_ROOT"):
            self.assertNotIn(f'"{obsolete}"',checkpoint+harness+task)

    def test_runtime_core_has_no_sha256_coupling(self):
        files=["dsd_task.py","dsd_workspace.py","dsd_attempt.py","run_worker.py","evidence_gate.py","scope_snapshot.py","render_worker_prompt.py"]
        for name in files:
            self.assertNotIn("sha256",(SCRIPTS/name).read_text().lower(),name)

    def test_obsolete_duplicate_artifacts_are_not_shipped(self):
        removed=(
            "RESEARCH-2026-08-SKILL-PRACTICES.md", "COMPACTION.md",
            "scripts/install_compaction_adapter.py", "scripts/opencode_probe.py", "scripts/check_state.py",
            "adapters/README.md", "adapters/codex/config.fragment.toml", "adapters/kilo/README.md",
            "worker-cli/COMMAND-CODE.md", "worker-cli/KILO.md", "templates/task-plan.example.json",
            "contrib/kilo/install_agents.py", "contrib/kilo/install_compaction.py",
        )
        for rel in removed:
            self.assertFalse((ROOT/rel).exists(),rel)

    def test_no_current_contract_in_hot_or_workspace(self):
        self.assertNotIn("task.current_contract",(ROOT/"SKILL.md").read_text())
        self.assertNotIn("task.current_contract",(ROOT/"WORKSPACE.md").read_text())

    def test_cli_notes_are_cold_and_only_wired_tools_are_shipped(self):
        router=(ROOT/"WORKER-CLI.md").read_text(); skill=(ROOT/"SKILL.md").read_text()
        for name in ("worker-cli/OPENCODE.md","worker-cli/OPENCODE2.md","worker-cli/CODEX.md","worker-cli/CLAUDE.md"):
            self.assertIn(name,router); self.assertTrue((ROOT/name).is_file())
        self.assertNotIn("COMMAND-CODE",router); self.assertNotIn("worker-cli/KILO.md",router)
        self.assertIn("WORKER-CLI.md",skill)
        self.assertNotIn("Too Many Requests",skill)

    def test_parent_adapters_do_not_embed_worker_transport_manuals(self):
        self.assertNotIn("Failed to execute statement",(ROOT/"OPENCODE.md").read_text())
        self.assertNotIn("command-code",(ROOT/"CODEX.md").read_text().lower())
        self.assertIn("worker-cli/OPENCODE.md",(ROOT/"OPENCODE.md").read_text())


if __name__=="__main__": unittest.main()
