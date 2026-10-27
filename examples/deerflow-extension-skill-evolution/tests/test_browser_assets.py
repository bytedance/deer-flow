import json
import re
import sys
import types
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

from deerflow_extension_skill_evolution import install

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "deerflow_extension_skill_evolution"
MANIFEST = PACKAGE_DIR / "ui_manifest.json"
MODULE_JS = PACKAGE_DIR / "static" / "index.mjs"
STYLE_CSS = PACKAGE_DIR / "static" / "style.css"
DECLARED_MODULE = "skill-evolution.v1"
DECLARED_ACTIONS = {
    "status",
    "skill_config",
    "skill_config_write",
    "evolved_skills",
    "evolved_version",
    "managed_read",
    "managed_stage",
    "managed_check",
    "managed_publish",
    "managed_rollback",
    "annotation_draft",
    "annotation_evolve",
    "evolution_status",
    "evolution_discard",
    "skill_trajectories",
    "trajectory_annotate",
    "trajectory_unannotate",
}
REGISTERED_ACTIONS = DECLARED_ACTIONS | {"managed_propose", "managed_discard"}


def _fake_tool() -> StructuredTool:
    def _run(action: str, name: str = "", content: str = "") -> str:
        return "ok"

    return StructuredTool.from_function(func=_run, name="skill_manage", description="fake host tool")


def _stub_host_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    leaf = types.ModuleType("deerflow.tools.skill_manage_tool")
    leaf.skill_manage_tool = _fake_tool()
    monkeypatch.setitem(sys.modules, "deerflow.tools.skill_manage_tool", leaf)


def _browser_source() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((PACKAGE_DIR / "static").glob("*.mjs")))


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_matches_the_host_schema() -> None:
    manifest = _manifest()
    # load_browser_assets rejects any extra or missing key.
    assert set(manifest) == {"schema_version", "entry", "files"}
    assert manifest["schema_version"] == 1
    assert manifest["entry"] == "static/index.mjs"
    assert manifest["entry"] in manifest["files"]
    # Every listed file exists and paths stay inside the package.
    for relative in manifest["files"]:
        path = (PACKAGE_DIR / relative).resolve()
        assert path.is_file(), relative
        assert PACKAGE_DIR.resolve() in path.parents


def test_declared_browser_assets_resolve_to_real_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from deerflow_extension_api import BrowserAssets

    _stub_host_tool(monkeypatch)

    class _Registry:
        def __init__(self) -> None:
            self.plugins: list = []

        def middlewares(self, contributor) -> None:
            return None

        def service(self, service) -> None:
            return None

        def plugin(self, contribution) -> bool:
            self.plugins.append(contribution)
            return True

    registry = _Registry()
    install(registry, {})
    (contribution,) = registry.plugins
    assets = contribution.frontend
    assert isinstance(assets, BrowserAssets)
    assert assets.module == DECLARED_MODULE
    assert Path(assets.root) == PACKAGE_DIR
    assert (Path(assets.root) / assets.manifest).is_file()


def test_browser_module_matches_the_python_declaration() -> None:
    source = _browser_source()
    # The frontend loader rejects a module whose `module` field disagrees with
    # the contribution's BrowserAssets module string.
    assert f'module: "{DECLARED_MODULE}"' in source
    assert "apiVersion: 1" in source


def test_browser_module_declares_one_valid_page_surface() -> None:
    source = _browser_source()
    # Surface ids must match the host's /^[a-z][a-z0-9-]{0,63}$/ rule.
    assert re.search(r'id: "status"', source)
    assert re.search(r'slot: "page"', source)
    assert "title:" in source and "mount" in source
    # Navigation labels: nonempty, at most 120 UTF-16 units each.
    for field in ("label:", "labelZh:"):
        match = re.search(rf'{field}\s*"([^"]+)"', source)
        assert match, field
        assert 0 < len(match.group(1)) <= 120


def test_browser_module_only_calls_declared_backend_actions() -> None:
    source = _browser_source()
    # Direct backend calls plus the callAction() indirection used by the
    # operation buttons; both must stay within the declared action set.
    called = set(re.findall(r'callBackend\("([a-z_]+)"', source))
    called |= set(re.findall(r'callAction\(context, "([a-z_]+)"', source))
    assert called <= DECLARED_ACTIONS
    assert called == DECLARED_ACTIONS


def test_registered_backend_actions_cover_the_page_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_host_tool(monkeypatch)

    class _Registry:
        def __init__(self) -> None:
            self.plugins: list = []

        def middlewares(self, contributor) -> None:
            return None

        def service(self, service) -> None:
            return None

        def plugin(self, contribution) -> bool:
            self.plugins.append(contribution)
            return True

    registry = _Registry()
    install(registry, {})
    registered = {action.name for action in registry.plugins[0].backend}
    assert REGISTERED_ACTIONS <= registered


def test_browser_module_lists_self_evolved_skills_with_client_side_pagination() -> None:
    source = _browser_source()
    # The authorship list comes from the plugin's own evolved_skills action
    # (per-owner records of pipeline commits/reverts)...
    assert 'callBackend("evolved_skills", {})' in source
    assert "Self-evolved skills" in source
    # ...joined with the host's authenticated public listing API for live
    # description/enabled state, fetched from the packaged asset origin with
    # session credentials (the agent-teams pattern).
    assert '"/api/plugins/"' in source
    assert '"/api/skills"' in source
    assert 'credentials: "include"' in source
    # Client-side pagination: bounded page size plus edge-disabled buttons.
    assert "PAGE_SIZE" in source
    assert "prev.disabled" in source
    assert "next.disabled" in source


def test_browser_module_folds_secondary_sections_behind_details() -> None:
    source = _browser_source()
    # Installation / evolution policy / host capabilities are secondary: each
    # renders inside a collapsed <details> so the skill list stays primary.
    assert 'className: "status-fold"' in source
    assert '"summary"' in source
    for title in ("Installation", "Agent behavior guidance", "Runtime requirements and permissions", "Advanced diagnostics"):
        assert f't("{title}"' in source
        # The skills card is the page's primary content and renders before
        # the configuration card and the folded status root.
        assert "container.append(header, modulesRoot)" in source


def test_browser_module_renders_operation_buttons_from_the_grant() -> None:
    source = _browser_source()
    # One button per operator-granted operation (config.yaml
    # host_access.skill_mutations.operations), in canonical pipeline order.
    assert 'const OP_ORDER = ["stage", "check", "commit", "revert"];' in source
    # The operations come from the status snapshot's skill_mutations grant.
    assert "setOperations" in source
    # stage opens the inline editor bound to managed_stage/managed_read.
    assert 'callAction(context, "managed_read"' in source
    assert 'callAction(context, "managed_stage"' in source
    # check / commit / revert bind to their pipeline actions with the staged
    # proposal id or the recorded operation id.
    assert 'callAction(context, "managed_check", { proposal_id: state.proposal_id })' in source
    assert 'callAction(context, "managed_publish", { proposal_id: state.proposal_id })' in source
    assert 'callAction(context, "managed_rollback", { operation_id: operationId })' in source


def test_browser_module_offers_a_version_picker_for_revert() -> None:
    source = _browser_source()
    # The host's revert only undoes the head operation, so the revert button
    # opens a version history panel instead of reverting immediately.
    assert "versionPanel" in source
    assert "versionFor" in source
    assert '"Undo this operation"' in source
    assert '"Restore this version"' in source
    # The head entry undoes via managed_rollback; older entries fetch the
    # saved bytes through evolved_version and replay them via the stage
    # editor (stage → check → commit as a new forward version).
    assert 'runPipeline("revert", skill.name, entry.operation_id)' in source
    assert 'callAction(context, "evolved_version", { operation_id: entry.operation_id })' in source
    # A cancel button beside the undo button closes the panel without acting.
    assert "ops.append(undo, cancel)" in source
    # Every history entry also offers "View changes": it fetches this
    # version's saved content plus the previous one and renders the inline
    # line diff (toggleable) under the entry.
    assert '"View changes"' in source
    assert '"Hide changes"' in source
    assert "versionDiffs" in source
    assert "diffView(context, diff.before, diff.after)" in source
    # Entries without a content snapshot are not restorable.
    assert "restore.disabled = true" in source


def test_browser_module_offers_per_skill_usage_trajectories() -> None:
    source = _browser_source()
    # Every skill row offers a trajectories toggle that loads the recent
    # sealed runs which activated the skill, through the plugin's own action.
    assert 'callAction(context, "skill_trajectories", { skill_name: name })' in source
    assert "trajectoryPanel" in source
    assert "trajFor" in source
    assert '"skill-traj-invocation"' in source
    # Events render as a bounded timeline; invocation points carry a badge.
    assert "skill-traj-timeline" in source
    assert 'node("span", t("Invocation", "调用点")' in source
    # Every event renders with a kind label (You / Model / Tool / Skill), an
    # optional tool name chip, and a bounded preview line of the caller's own
    # sealed content, so the timeline is readable for annotation.
    assert "eventKindLabel" in source
    assert "skill-traj-kind-" in source
    assert "skill-traj-tool" in source
    assert "skill-traj-preview" in source
    # Clicking an event opens an annotation editor bound to the plugin's
    # annotation store actions; saving and removing both refresh the panel.
    assert '"trajectory_annotate"' in source
    assert '"trajectory_unannotate"' in source
    assert "loadTrajectories(name)" in source
    # The save handler's parameter must not shadow the note() notifier —
    # `note(name, ...)` after a successful save once called the string.
    assert "async function saveAnnotation(name, runId, eventId, noteText)" in source
    assert "note: noteText," in source
    # Opening the trajectories panel closes the editor and version panels.
    assert "trajFor = null" in source


def test_browser_module_offers_the_annotation_draft_in_draft_mode() -> None:
    source = _browser_source()
    # Plan A: in draft feedback mode every skill row offers a draft button
    # that synthesizes the current content plus the caller's annotations and
    # prefills the stage editor; the backend enforces the same switch.
    assert 'callAction(context, "annotation_draft", { skill_name: name })' in source
    assert "skill-draft-btn" in source
    assert "loadDraft(name)" in source
    # The mode comes from the status snapshot; agent mode hides the button.
    assert "setFeedbackMode" in source
    assert 'feedbackMode === "draft"' in source
    # The status page explains the resolved mode and warns when agent mode
    # lacks a configured store.
    assert 'config.feedback_mode === "agent"' in source
    assert "skill_feedback" in source


def test_browser_module_offers_annotation_triggered_evolution_in_agent_mode() -> None:
    source = _browser_source()
    # Plan B: the trajectory panel offers an evolve trigger bound to the
    # plugin's background job actions; the panel renders only in agent mode.
    # The chosen model travels with the launch payload as a role.
    assert "annotation_evolve" in source
    assert "const payload = selectedModel ? { skill_name: name, model_name: selectedModel } : { skill_name: name }" in source
    assert 'callAction(context, "evolution_status", { skill_name: name })' in source
    assert 'callAction(context, "evolution_discard", { skill_name: name, job_id: jobId })' in source
    assert "evolutionPanel" in source
    assert 'feedbackMode === "agent"' in source
    # Opening the trajectory panel fetches the current job state and polls
    # while it runs; closing the panel stops the poll.
    assert "refreshEvolution(name)" in source
    assert "stopEvoPoll" in source
    # A terminal job also stops the poll: the finished diff must not repaint
    # (and reset its scroll) every interval tick.
    assert "Terminal (or absent): stop polling" in source
    # The finished draft renders as a bounded line diff against the base
    # content, with human-gated actions back into the managed pipeline.
    assert "lineDiff" in source
    assert "skill-evo-diff" in source
    assert '"Stage this draft"' in source
    assert '"Discard"' in source
    # A draft already published through the pipeline shows a quiet
    # confirmation with a clear-record action instead of the diff.
    assert "skill-evo-published" in source
    assert '"Clear record"' in source
    # A draft identical to its input (the model kept the content) is called
    # out as unchanged rather than rendered as an empty diff.
    assert "job.unchanged" in source
    assert "模型保持了当前内容" in source
    # The transient "started" note is replaced by the outcome when the poll
    # sees a terminal job, so a quiet finish never looks like a stuck launch.
    assert "Draft ready — review the diff below." in source
    assert "Draft published through the pipeline." in source
    assert "The model kept the current content; nothing to change." in source
    # Saving an annotation supersedes a consumed draft: the backend
    # auto-clears the published job, so the page refreshes the evolution
    # panel back to the trigger state.
    assert 'if (feedbackMode === "agent") void refreshEvolution(name);' in source
    # The model picker lists the caller's configured models with their grant
    # state, and the chosen model travels with the launch payload.
    assert "skill-evo-model" in source
    assert "evoModelChoice" in source
    assert "loadEvolutionModels" in source
    assert 'callAction(context, "annotation_evolve", payload)' in source


def test_browser_module_offers_the_grant_configuration_card() -> None:
    source = _browser_source()
    # The configuration card edits the operator grants from the page: skills
    # come from the host's public catalog (dropdown checkboxes) with a
    # single-shot validated free input.
    assert "createConfigureCard" in source
    assert 'callAction(context, "skill_config", {})' in source
    assert 'callAction(context, "skill_config_write"' in source
    # The free input is consumed on the first successful add.
    assert "customUsed" in source
    assert "Skill not found" in source
    # Submitting reports the reinstall command and restart requirement.
    assert "reinstall_command" in source
    assert "restart the Gateway" in source.lower() or "重启 Gateway" in source
    # Only granted owners may save; the button reflects can_write.
    assert "can_write" in source
    # The card is collapsed by default (an occasional operator task, not the
    # page's primary content).
    assert "skill-config-fold" in source
    # Model choice is deliberately NOT configured here: evolution models are
    # a per-launch selection in the trajectory panel's picker.
    assert "evolution_models" not in source
    # The model picker always renders once the catalog loads — even a
    # single-model host sees it, with a hint where more models come from.
    assert "loadEvolutionModels" in source
    assert "evolutionDefaultModel" in source
    assert "Only one chat model is available" in source
    assert "No plugin-specific model configuration or authorization" in source
    # The evolution mode is a peer of the target-skills group inside the
    # same fold: two radios (model / append), persisted via the same save,
    # and applied to the page immediately after a successful write.
    assert "自演进方式（evolution_mode）" in source
    assert 'input[name="skill-config-evolution-mode"]' in source
    assert "evolution_mode" in source
    assert "onModeChange" in source
    assert "Evolution mode applied" in source
    assert "applies immediately after saving, no restart" in source
    assert "const payload = selectedModel ? { skill_name: name, model_name: selectedModel } : { skill_name: name }" in source


def test_browser_module_loads_styles_and_handles_disposal() -> None:
    source = _browser_source()
    # The stylesheet is a manifest-listed relative asset, and disposal removes
    # both the sheet and the container (agent-teams' mount contract).
    assert 'new URL("./style.css", import.meta.url)' in source
    assert "function dispose" in source
    assert 'addEventListener("abort"' in source
    assert STYLE_CSS.is_file()


def test_agent_evolution_shell_and_module_registry():
    source = _browser_source()
    modules = (PACKAGE_DIR / "static" / "modules.mjs").read_text(encoding="utf-8")
    assert 'labelZh: "Agent 自演进"' in source
    assert 't("Information", "信息")' in source
    assert "createEvolutionModules" in source
    assert 'id: "skill"' in modules
    assert 'id: "memory"' in modules
    assert 'state: "planned"' in modules
    assert "module.create(context)" in source


def test_all_relative_module_imports_are_packaged():
    files = set(_manifest()["files"])
    for asset in files:
        if not asset.endswith(".mjs"):
            continue
        source = (PACKAGE_DIR / asset).read_text(encoding="utf-8")
        for relative in re.findall(r'from "(\./[^\"]+)"', source):
            imported = (Path(asset).parent / relative).as_posix()
            assert imported in files, f"{asset} imports undeclared asset {imported}"


def test_refresh_and_information_belong_to_skill_module():
    shell = MODULE_JS.read_text(encoding="utf-8")
    skill = (PACKAGE_DIR / "static/skill.mjs").read_text(encoding="utf-8")
    assert 'node("h1"' not in shell
    assert "moduleHead.append(instance.headerActions)" in shell
    assert "section.append(instance.content)" in shell
    assert "content.append(status, skills.card, configure.card, statusRoot)" in skill
    assert "headerActions: refresh" in skill
    assert "renderInformation(context, snapshot, statusRoot)" in skill
    assert "callBackend" not in shell


def test_skill_sections_share_semantic_heading_hierarchy():
    shell = MODULE_JS.read_text(encoding="utf-8")
    skill = (PACKAGE_DIR / "static/skill.mjs").read_text(encoding="utf-8")
    assert 'node("h1"' not in shell  # Host already renders the page h1.
    assert 'node("h2", zh(context) ? module.label.zh' in shell
    assert 'node("h3", title, { className: "status-title" })' in skill
    for title in ("Self-evolved skills", "Configuration", "Information"):
        assert f'createSectionHeading(\n    t("{title}"' in skill
    assert 'node("h4", t("Target skills' in skill
    assert 'node("h4", t("Evolution mode' in skill


def test_information_explains_guidance_and_separates_diagnostics():
    source = (PACKAGE_DIR / "static/skill.mjs").read_text(encoding="utf-8")
    assert 't("Agent behavior guidance", "Agent 行为建议")' in source
    assert 't("Runtime requirements and permissions", "运行条件与权限")' in source
    assert 't("Advanced diagnostics", "高级诊断")' in source
    assert '"反馈演进模式"' not in source
    assert "不会计数或自动启动演进" in source
    assert "不是程序强制审批" in source
    assert "capabilityRows.push(detail)" not in source


def test_trajectories_warm_before_clicks_and_refresh_after_annotations():
    source = (PACKAGE_DIR / "static/skill.mjs").read_text(encoding="utf-8")
    assert "new TrajectoryCache" in source
    assert "trajs.warm(evolved.slice(0, PAGE_SIZE * 2)" in source
    assert "(page + 2) * PAGE_SIZE" in source
    assert source.count("await loadTrajectories(name, { force: true })") == 2
    assert "state.loading && !state.data" in source
    assert "trajs.clear()" in source
    assert "trajFor === name && !annotFor" in source
