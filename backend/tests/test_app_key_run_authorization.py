import pytest
from fastapi import HTTPException

from app.gateway.services import validate_app_key_profile


def test_app_key_profiles_default_deny_unlisted_agents_and_models():
    profile = {"agents": ["reviewer"], "models": ["fast-model"]}
    validate_app_key_profile(profile, assistant_id="reviewer", model_name="fast-model")

    with pytest.raises(HTTPException, match="agent"):
        validate_app_key_profile(profile, assistant_id="lead-agent", model_name="fast-model")
    with pytest.raises(HTTPException, match="model"):
        validate_app_key_profile(profile, assistant_id="reviewer", model_name=None)
