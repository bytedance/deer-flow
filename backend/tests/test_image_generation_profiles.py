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
