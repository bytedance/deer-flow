"""Resolve SmsAdapter from config.yaml integrations section.

Single shared instance used by both abnormal.py and workbench.py routers.
Avoids duplicating the SMS connection config.
"""

from __future__ import annotations

import logging

import yaml

from deerflow.integrations.adapters.sms import SmsAdapter
from deerflow.integrations.config import IntegrationSystemConfig, IntegrationsConfig

logger = logging.getLogger(__name__)

_adapter: SmsAdapter | None = None
_adapter_initialized: bool = False


def _load_sms_config() -> IntegrationSystemConfig | None:
    """Load SMS system config from the integrations section of config.yaml."""
    from pathlib import Path

    config_path = Path("/app/config.yaml")
    if not config_path.exists():
        logger.warning("config.yaml not found at %s", config_path)
        return None

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read config.yaml")
        return None

    integrations_raw = raw.get("integrations")
    if not isinstance(integrations_raw, dict):
        return None

    systems_raw = integrations_raw.get("systems")
    if not isinstance(systems_raw, dict):
        return None

    sms_raw = systems_raw.get("sms")
    if not isinstance(sms_raw, dict):
        logger.warning("No 'sms' system found in config.yaml integrations.systems")
        return None

    # Inject system_key from the dict key (same behaviour as IntegrationsConfig parser)
    if "system_key" not in sms_raw:
        sms_raw["system_key"] = "sms"

    return IntegrationSystemConfig.model_validate(sms_raw)


def get_sms_adapter() -> SmsAdapter | None:
    """Get or create the shared SmsAdapter singleton."""
    global _adapter
    if _adapter is None:
        cfg = _load_sms_config()
        if cfg is None:
            logger.error("Cannot create SmsAdapter: SMS config missing")
            return None
        _adapter = SmsAdapter(cfg)
        logger.info("SmsAdapter created from config.yaml (base_url=%s)", cfg.base_url)
    return _adapter


async def ensure_sms_adapter() -> SmsAdapter:
    """Get the shared SmsAdapter, initialising on first call."""
    global _adapter_initialized
    adapter = get_sms_adapter()
    if adapter is None:
        raise RuntimeError("SmsAdapter not available — check config.yaml integrations.systems.sms")
    if not _adapter_initialized:
        await adapter.initialize()
        _adapter_initialized = True
        logger.info("SmsAdapter initialized")
    return adapter
