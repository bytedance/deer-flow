"""Image profiles are encrypted, isolated from chat models and safe to inspect."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from deerflow.config.app_config import AppConfig
from deerflow.config.image_generation import (
    ImageConfigurationError,
    ImageGenerationProfile,
    ManagedImageGenerationProfile,
    ManagedImageGenerationProfileStore,
    resolve_image_generation_profile,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    return ManagedImageGenerationProfileStore()


def profile(**fields):
    values = {"name": "pictures", "provider": "openai", "model": "image-model", "base_url": "https://images.example/v1", "api_key": "synthetic-image-secret"}
    return ManagedImageGenerationProfile(**{**values, **fields})


def test_encrypted_profile_revision_secret_and_precedence(store):
    first = store.save(profile(), expected_revision=None)
    assert b"synthetic-image-secret" not in store.path.read_bytes()
    assert b"synthetic-image-secret" not in str(first.public()).encode()
    assert first.public()["has_api_key"] is True
    selected, source, _ = resolve_image_generation_profile({"GEMINI_API_KEY": "legacy-secret"})
    assert (selected.model, source) == ("image-model", "managed")

    updated = store.save(profile(model="new-model", api_key=None), expected_revision=first.revision)
    assert updated.api_key.get_secret_value() == "synthetic-image-secret"
    assert updated.revision != first.revision
    with pytest.raises(FileExistsError):
        store.save(profile(), expected_revision=first.revision)

    disabled = store.save(profile(enabled=False, api_key=None), expected_revision=updated.revision)
    selected, source, _ = resolve_image_generation_profile({"GEMINI_API_KEY": "legacy-secret"})
    assert (selected.provider.value, source) == ("gemini", "sandbox_environment")
    assert disabled.enabled is False


def test_only_one_enabled_and_test_results_reset_on_edit(store):
    first = store.save(profile(), expected_revision=None)
    with pytest.raises(ImageConfigurationError, match="Disable"):
        store.save(profile(name="second"), expected_revision=None)
    tested = store.record_test(first.name, first.revision, "generation", "success")
    assert tested.verified_generation is True
    failed = store.record_test(first.name, first.revision, "edit", "unreachable")
    assert failed.verified_edit is False
    assert failed.last_edit_result == "unreachable"
    toggled = store.save(profile(enabled=False, api_key=None), expected_revision=first.revision)
    assert toggled.verified_generation is True
    assert toggled.last_edit_result == "unreachable"
    changed = store.save(profile(model="changed", enabled=False, api_key=None), expected_revision=toggled.revision)
    assert changed.verified_generation is False
    assert changed.last_edit_result is None


def test_missing_key_not_silently_recreated(store):
    store.save(profile(), expected_revision=None)
    store.key_path.unlink()
    with pytest.raises(ValueError, match="key"):
        store.list()
    assert not store.key_path.exists()


def test_legacy_explicit_provider_without_key_is_invalid(store):
    chosen, source, _ = resolve_image_generation_profile({"IMAGE_GENERATION_PROVIDER": "openai", "IMAGE_GENERATION_BASE_URL": "https://images.example/v1"})
    assert source == "sandbox_environment"
    assert chosen.usable() is False


def test_enabled_web_profile_without_key_does_not_silently_fall_back(store):
    store.save(profile(api_key=""), expected_revision=None)
    selected, source, _ = resolve_image_generation_profile({"GEMINI_API_KEY": "legacy-secret"})
    assert source == "managed"
    assert selected.usable() is False


def test_malformed_server_settings_do_not_block_an_enabled_web_profile(store):
    from deerflow.config.image_generation import ImageGenerationDefaultStore, effective_image_generation_source, image_profile_choice_needed, image_profile_identity

    web = store.save(profile(), expected_revision=None)
    invalid_server = {"IMAGE_GENERATION_PROVIDER": "unknown-provider"}
    selected, source, _ = resolve_image_generation_profile(invalid_server)
    assert (selected.model, source) == (web.model, "managed")
    assert image_profile_choice_needed(invalid_server) is False

    ImageGenerationDefaultStore().save(
        "managed",
        target_identity=image_profile_identity(web),
        expected_revision=None,
        environment=invalid_server,
    )
    assert effective_image_generation_source(invalid_server) == "managed"


def test_profile_catalog_marks_the_effective_source_when_server_and_web_both_exist(store, monkeypatch):
    from app.gateway.routers import image_generation as router

    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "server-image"}}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    saved = store.save(profile(), expected_revision=None)

    catalog = router._list_profiles()
    by_source = {item["source"]: item for item in catalog["profiles"]}
    assert catalog["status"]["source"] == "managed"
    assert catalog["status"]["choice_required"] is True
    assert by_source["managed"]["selected"] is False
    assert by_source["managed"]["conflict"] is True
    assert by_source["config"]["selected"] is False
    assert by_source["config"]["conflict"] is True
    assert "synthetic-server-key" not in str(catalog)

    store.save(profile(enabled=False, api_key=None), expected_revision=saved.revision)
    catalog = router._list_profiles()
    by_source = {item["source"]: item for item in catalog["profiles"]}
    assert catalog["status"]["source"] == "sandbox_environment"
    assert by_source["config"]["selected"] is True
    assert by_source["managed"]["selected"] is False
    assert by_source["managed"]["conflict"] is False


def test_coexisting_server_and_web_require_explicit_image_choice_without_saved_default(store):
    from deerflow.config.image_generation import (
        bind_image_generation_source,
        image_profile_choice_needed,
        legacy_image_model_identity,
    )

    original = {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "server-first"}
    store.save(profile(server_model_at_enable=legacy_image_model_identity(original)), expected_revision=None)
    assert image_profile_choice_needed(original) is True
    changed = {**original, "GEMINI_IMAGE_MODEL": "server-second"}
    assert image_profile_choice_needed(changed) is True
    assert resolve_image_generation_profile(changed)[1] == "managed"
    with bind_image_generation_source("sandbox_environment"):
        selected, source, managed = resolve_image_generation_profile(changed)
        assert (selected.model, source, managed) == ("server-second", "sandbox_environment", None)
    assert resolve_image_generation_profile(changed)[1] == "managed"


def test_matching_model_ids_at_different_endpoints_still_require_a_choice(store):
    from deerflow.config.image_generation import image_profile_choice_needed

    store.save(profile(), expected_revision=None)
    environment = {
        "IMAGE_GENERATION_PROVIDER": "openai",
        "IMAGE_GENERATION_API_KEY": "synthetic-server-key",
        "IMAGE_GENERATION_MODEL": "image-model",
        "IMAGE_GENERATION_BASE_URL": "https://server-images.example/v1",
    }
    assert image_profile_choice_needed(environment) is True


@pytest.mark.parametrize("source", ["managed", "sandbox_environment"])
def test_saved_default_survives_store_reload_and_invalidates_on_server_change(store, source):
    from deerflow.config.image_generation import (
        ImageGenerationDefaultStore,
        image_profile_choice_needed,
        image_profile_identity,
        legacy_image_storage_identity,
    )

    environment = {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "new-server"}
    managed = store.save(profile(server_model_at_enable="gemini:old-server"), expected_revision=None)
    assert image_profile_choice_needed(environment) is True

    target_identity = image_profile_identity(managed) if source == "managed" else legacy_image_storage_identity(environment)
    saved = ImageGenerationDefaultStore().save(source, target_identity=target_identity, expected_revision=None, environment=environment)
    assert ImageGenerationDefaultStore().read().revision == saved.revision
    assert "synthetic-server-key" not in ImageGenerationDefaultStore().path.read_text(encoding="utf-8")
    assert image_profile_choice_needed(environment) is False
    assert resolve_image_generation_profile(environment)[1] == source
    from deerflow.config.image_generation import bind_image_generation_source

    other_source = "managed" if source == "sandbox_environment" else "sandbox_environment"
    with bind_image_generation_source(other_source):
        assert resolve_image_generation_profile(environment)[1] == other_source
    assert resolve_image_generation_profile(environment)[1] == source

    changed = {**environment, "GEMINI_IMAGE_MODEL": "changed-again"}
    assert image_profile_choice_needed(changed) is True
    assert resolve_image_generation_profile(changed)[1] == "managed"


def test_saved_default_can_switch_between_two_openai_model_ids(store):
    from deerflow.config.image_generation import ImageGenerationDefaultStore, image_profile_choice_needed, image_profile_identity, legacy_image_storage_identity

    environment = {
        "IMAGE_GENERATION_PROVIDER": "openai",
        "IMAGE_GENERATION_API_KEY": "synthetic-server-key",
        "IMAGE_GENERATION_BASE_URL": "https://server-images.example/v1",
        "IMAGE_GENERATION_MODEL": "qwen-image-2.0",
    }
    web = store.save(profile(model="qwen-image-3.0", server_model_at_enable="openai:old-server"), expected_revision=None)
    assert image_profile_choice_needed(environment) is True
    server_default = ImageGenerationDefaultStore().save(
        "sandbox_environment",
        target_identity=legacy_image_storage_identity(environment),
        expected_revision=None,
        environment=environment,
    )
    assert resolve_image_generation_profile(environment)[0].model == "qwen-image-2.0"
    ImageGenerationDefaultStore().save(
        "managed",
        target_identity=image_profile_identity(web),
        expected_revision=server_default.revision,
        environment=environment,
    )
    assert resolve_image_generation_profile(environment)[0].model == "qwen-image-3.0"


def test_admin_save_rejects_duplicate_server_model_id(store, monkeypatch):
    from app.gateway.routers import image_generation as router

    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "same-id"}}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    with pytest.raises(HTTPException) as denied:
        router._save(router.SaveImageProfileRequest(config=profile(model="same-id")))
    assert denied.value.status_code == 409
    assert store.list() == []


def test_web_profile_saved_after_server_model_requires_choice_immediately(store, monkeypatch):
    from app.gateway.routers import image_generation as router

    original = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "server-first"}}})
    monkeypatch.setattr(router, "get_app_config", lambda: original)
    router._save(router.SaveImageProfileRequest(config=profile()))
    assert store.list()[0].server_model_at_enable == "gemini:server-first"
    catalog = router._list_profiles()
    assert catalog["status"]["choice_required"] is True
    assert all(item["selected"] is False and item["conflict"] is True for item in catalog["profiles"])

    web = next(item for item in catalog["profiles"] if item["source"] == "managed")
    router._set_default(router.SetImageDefaultRequest(source="managed", target_identity=web["identity"], expected_revision=None))
    catalog = router._list_profiles()
    assert catalog["status"]["choice_required"] is False
    assert next(item for item in catalog["profiles"] if item["source"] == "managed")["selected"] is True

    changed = AppConfig.model_validate({"sandbox": {"use": "test", "environment": {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "server-second"}}})
    monkeypatch.setattr(router, "get_app_config", lambda: changed)
    catalog = router._list_profiles()
    assert catalog["status"]["choice_required"] is True
    assert all(item["selected"] is False for item in catalog["profiles"])


def test_admin_sets_server_default_and_rejects_stale_selection(store, monkeypatch):
    from app.gateway.routers import image_generation as router
    from deerflow.config.image_generation import legacy_image_storage_identity

    environment = {"GEMINI_API_KEY": "synthetic-server-key", "GEMINI_IMAGE_MODEL": "server-second"}
    config = AppConfig.model_validate({"sandbox": {"use": "test", "environment": environment}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    store.save(profile(server_model_at_enable="gemini:server-first"), expected_revision=None)

    before = router._list_profiles()
    assert before["status"]["default_active"] is False
    server = next(item for item in before["profiles"] if item["source"] == "config")
    assert server["identity"] == legacy_image_storage_identity(environment)
    body = router.SetImageDefaultRequest(source="sandbox_environment", target_identity=server["identity"], expected_revision=None)
    router._set_default(body)

    after = router._list_profiles()
    assert after["status"]["choice_required"] is False
    assert after["status"]["source"] == "sandbox_environment"
    assert after["status"]["default_revision"]
    assert after["status"]["default_active"] is True
    assert next(item for item in after["profiles"] if item["source"] == "config")["selected"] is True
    assert next(item for item in after["profiles"] if item["source"] == "managed")["selected"] is False

    with pytest.raises(HTTPException) as stale:
        router._set_default(body)
    assert stale.value.status_code == 409

    with pytest.raises(HTTPException) as wrong_target:
        router._set_default(router.SetImageDefaultRequest(source="managed", target_identity="stale-profile", expected_revision=after["status"]["default_revision"]))
    assert wrong_target.value.status_code == 409


@pytest.mark.asyncio
async def test_admin_api_redacts_key_and_tracks_capabilities(store, monkeypatch):
    from app.gateway.routers import image_generation as router

    config = AppConfig.model_validate({"sandbox": {"use": "test"}})
    monkeypatch.setattr(router, "get_app_config", lambda: config)
    admin = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))
    body = router.SaveImageProfileRequest(config=profile())
    with pytest.raises(HTTPException) as denied:
        await router.save_image_profile(member, body)
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException) as denied:
        await router.list_image_profiles(member)
    assert denied.value.status_code == 403

    saved = await router.save_image_profile(admin, body)
    assert saved["has_api_key"] is True
    assert "api_key" not in saved
    catalog = await router.list_image_profiles(admin)
    assert "synthetic-image-secret" not in str(catalog)
    assert catalog["status"]["status"] == "configured_unverified"
    default_request = router.SetImageDefaultRequest(source="managed", target_identity=catalog["profiles"][0]["identity"])
    with pytest.raises(HTTPException) as denied:
        await router.set_image_default(member, default_request)
    assert denied.value.status_code == 403
    selected = await router.set_image_default(admin, default_request)
    assert selected["revision"]

    monkeypatch.setattr(router, "probe_image_profile", lambda _profile, operation: "success" if operation == "generation" else "unsupported_edit")
    test = router.TestImageProfileRequest(expected_revision=saved["revision"])
    assert (await router.test_image_profile(admin, "pictures", "generation", test))["ok"] is True
    assert (await router.test_image_profile(admin, "pictures", "edit", test))["message"] == "unsupported_edit"
    status = await router.image_generation_status(admin)
    assert status["supports_generation"] is True
    assert status["supports_edit"] is False

    monkeypatch.setattr(router, "probe_image_profile", lambda _profile, _operation: "unreachable")
    await router.test_image_profile(admin, "pictures", "edit", test)
    assert (await router.image_generation_status(admin))["status"] == "unreachable"


def test_command_environment_is_provider_specific():
    profile = ImageGenerationProfile(provider="openai", model="image-model", base_url="https://images.example/v1", api_key="synthetic-key")
    env = profile.command_environment()
    assert env["IMAGE_GENERATION_PROVIDER"] == "openai"
    assert env["IMAGE_GENERATION_API_KEY"] == "synthetic-key"
    assert env["GEMINI_API_KEY"] == ""
