"""Existing storage writers participate in the same version chain as plugins."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.skills.mutations.guard import SkillMutationRuntime, configure_mutation_runtime
from deerflow.skills.mutations.repository import SkillMutationRepository
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

CONTENT = "---\nname: example\ndescription: Before\n---\nA\n"


@pytest.fixture
def assets(tmp_path, monkeypatch):
    from deerflow.persistence.user.model import UserRow

    monkeypatch.setattr("deerflow.config.paths._paths", Paths(base_dir=tmp_path / "home"))
    storage = UserScopedSkillStorage("owner", host_path=str(tmp_path / "skills"))
    root = storage.get_custom_skill_dir("example")
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(CONTENT, encoding="utf-8")
    engine = create_engine(f"sqlite:///{tmp_path / 'mutations.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserRow(id="owner", email="owner@example.test"))
    repository = SkillMutationRepository(sessions)
    runtime = SkillMutationRuntime(repository, owners=frozenset({"owner"}))
    configure_mutation_runtime(runtime)
    # This suite checks canonical versions; view semantics have their own suite.
    monkeypatch.setattr("deerflow.skills.projection._rebuild_user_locked", lambda *_: None)
    yield storage, runtime, repository
    configure_mutation_runtime(None)
    engine.dispose()


def test_managed_aba_conflicts_even_when_digest_matches(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.write_custom_skill("example", "SKILL.md", CONTENT.replace("\nA\n", "\nB\n"))
    storage.write_custom_skill("example", "SKILL.md", CONTENT)
    last = runtime.read_revision(storage, "example")
    assert last.content_digest == first.content_digest
    assert last.incarnation_id == first.incarnation_id
    assert last.mutation_seq == first.mutation_seq + 2


def test_no_change_does_not_increment_revision(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.write_custom_skill("example", "SKILL.md", CONTENT)
    assert runtime.read_revision(storage, "example") == first


def test_delete_recreate_changes_incarnation_and_retains_sequence(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.delete_custom_skill("example")
    storage.write_custom_skill("example", "SKILL.md", CONTENT)
    last = runtime.read_revision(storage, "example")
    assert last.incarnation_id != first.incarnation_id
    assert last.mutation_seq > first.mutation_seq


def test_support_file_and_toggle_changes_invalidate_prior_revision(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.write_custom_skill("example", "references/help.txt", "help")
    second = runtime.read_revision(storage, "example")
    assert second.mutation_seq == first.mutation_seq + 1
    storage.set_skill_enabled_state("example", False)
    third = runtime.read_revision(storage, "example")
    assert third.mutation_seq == second.mutation_seq + 1
    assert third.content_digest == second.content_digest


def test_other_skill_does_not_conflict(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.write_custom_skill("other", "SKILL.md", CONTENT.replace("example", "other"))
    assert runtime.read_revision(storage, "example") == first


def test_observed_external_edit_advances_revision(assets):
    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    storage.get_custom_skill_file("example").write_text(CONTENT + "external", encoding="utf-8")
    assert runtime.read_revision(storage, "example").mutation_seq == first.mutation_seq + 1


def test_catalog_read_uses_owner_guard(assets, monkeypatch):
    from contextlib import contextmanager

    storage, runtime, _ = assets
    entered = []

    @contextmanager
    def guard(_storage, **_kwargs):
        entered.append(True)
        yield

    monkeypatch.setattr("deerflow.skills.projection.skill_projection_read_lock", guard)
    storage.load_skills()
    assert entered


def test_owner_prompt_cache_never_hides_other_worker_change(assets):
    from deerflow.agents.lead_agent.prompt import get_enabled_skills_for_config
    from deerflow.config.app_config import AppConfig

    storage, _, _ = assets
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "skills": {"path": str(storage.get_skills_root_path())}})
    first = get_enabled_skills_for_config(config, "owner")
    storage.write_custom_skill("example", "SKILL.md", CONTENT.replace("Before", "After"))
    second = get_enabled_skills_for_config(config, "owner")
    assert next(skill.description for skill in first if skill.name == "example") == "Before"
    assert next(skill.description for skill in second if skill.name == "example") == "After"


def test_global_disable_participates_in_effective_revision(assets, monkeypatch):
    from deerflow.config.extensions_config import ExtensionsConfig

    storage, runtime, _ = assets
    first = runtime.read_revision(storage, "example")
    monkeypatch.setattr(ExtensionsConfig, "from_file", lambda *a, **kw: ExtensionsConfig(skills={"example": {"enabled": False}}))
    assert runtime.state(storage, "example")[1] is False
    assert runtime.read_revision(storage, "example").mutation_seq > first.mutation_seq


def test_deleted_owner_cannot_read_catalog(assets):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.persistence.user.model import UserRow

    storage, _, repository = assets
    with repository.sessions.begin() as session:
        session.delete(session.get(UserRow, "owner"))
    with pytest.raises(HostCapabilityError, match="NOT_FOUND_OR_FORBIDDEN"):
        storage.load_skills()


def test_uncertain_legacy_write_blocks_catalog_until_revalidated(assets):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    storage, runtime, repository = assets
    digest, enabled, exists = runtime.state(storage, "example")
    repository.observe("owner", "example", digest, enabled, exists=exists, mark_mutating=True)
    with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
        storage.load_skills()
    runtime.read_revision(storage, "example")
    assert storage.load_skills()


@pytest.mark.parametrize("entry", ["shared", "thread", "rebuild", "slash"])
def test_every_new_asset_acquire_rejects_unresolved_owner(assets, monkeypatch, entry):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.skills.projection import ensure_skill_projections, ensure_thread_skill_projection, rebuild_skill_projections

    storage, _, repository = assets

    def blocked(_):
        raise HostCapabilityError("NEEDS_REPAIR")

    monkeypatch.setattr(repository, "check_readable", blocked)
    # Even an otherwise fresh thread projection must honor the DB barrier.
    monkeypatch.setattr("deerflow.skills.projection._thread_projection_is_fresh", lambda *_: True)
    with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
        if entry == "shared":
            ensure_skill_projections(storage)
        elif entry == "thread":
            ensure_thread_skill_projection(storage, "thread", {"example"})
        elif entry == "rebuild":
            rebuild_skill_projections(storage, include_public=False)
        else:
            from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

            SkillActivationMiddleware._read_skill_content(storage.get_custom_skill_file("example"), storage.get_skills_root_path(), storage=storage)


def test_uncertain_owner_blocks_other_managed_writer_before_touching_source(assets):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    storage, runtime, repository = assets
    digest, enabled, exists = runtime.state(storage, "example")
    repository.observe("owner", "example", digest, enabled, exists=exists, mark_mutating=True)
    with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
        storage.write_custom_skill("other", "SKILL.md", CONTENT.replace("example", "other"))
    assert not storage.get_custom_skill_file("other").exists()


def test_global_toggle_aba_invalidates_same_named_custom_asset(assets, monkeypatch, tmp_path):
    from app.gateway.routers.skills import _write_extensions_skill_state
    from deerflow.config.extensions_config import reload_extensions_config, reset_extensions_config

    storage, runtime, _ = assets
    config_file = tmp_path / "extensions.json"
    config_file.write_text('{"skills": {}}', encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_file))
    reload_extensions_config()
    first = runtime.read_revision(storage, "example")
    _write_extensions_skill_state(storage, "example", False, rebuild_public_projection=False)
    _write_extensions_skill_state(storage, "example", True, rebuild_public_projection=False)
    last = runtime.read_revision(storage, "example")
    assert last.content_digest == first.content_digest
    assert last.mutation_seq == first.mutation_seq + 2
    reset_extensions_config()


def test_export_refuses_uncertain_canonical_state(assets):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.skills.export import export_manifest

    storage, runtime, repository = assets
    digest, enabled, exists = runtime.state(storage, "example")
    repository.observe("owner", "example", digest, enabled, exists=exists, mark_mutating=True)
    with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
        export_manifest(storage, "example")


@pytest.mark.asyncio
async def test_tool_candidate_copy_refuses_uncertain_canonical_state(assets):
    from deerflow_extension_api.host_capabilities import HostCapabilityError

    from deerflow.tools.skill_manage_tool import _scan_static_candidate_or_raise

    storage, runtime, repository = assets
    digest, enabled, exists = runtime.state(storage, "example")
    repository.observe("owner", "example", digest, enabled, exists=exists, mark_mutating=True)
    with pytest.raises(HostCapabilityError, match="NEEDS_REPAIR"):
        await _scan_static_candidate_or_raise("example", {"help.txt": "help"}, storage)
