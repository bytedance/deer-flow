"""Startup namespace creation in the provisioner must tolerate a concurrent replica.

``_ensure_namespace()`` is the provisioner's one startup write. Two replicas
that start together against a missing ``K8S_NAMESPACE`` both read 404 and both
create; the loser's ``409 AlreadyExists`` used to escape the FastAPI lifespan
and crash that process. A 409 on create means the namespace now exists, the
same outcome the Pod and Service creates already accept.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


def _core_v1(provisioner_module, *, read_status: int | None = 404, create_status: int | None = None) -> MagicMock:
    core_v1 = MagicMock()
    if read_status is not None:
        core_v1.read_namespace.side_effect = provisioner_module.ApiException(status=read_status)
    if create_status is not None:
        core_v1.create_namespace.side_effect = provisioner_module.ApiException(status=create_status, reason="AlreadyExists" if create_status == 409 else "Forbidden")
    return core_v1


def test_ensure_namespace_treats_a_concurrent_create_as_already_existing(monkeypatch, provisioner_module, caplog):
    core_v1 = _core_v1(provisioner_module, create_status=409)
    monkeypatch.setattr(provisioner_module, "core_v1", core_v1)
    monkeypatch.setattr(provisioner_module, "K8S_NAMESPACE", "deer-flow-race")

    with caplog.at_level(logging.INFO, logger=provisioner_module.logger.name):
        provisioner_module._ensure_namespace()

    core_v1.create_namespace.assert_called_once()
    assert core_v1.create_namespace.call_args.args[0].metadata.name == "deer-flow-race"
    messages = [record.getMessage() for record in caplog.records if record.name == provisioner_module.logger.name]
    assert "Namespace 'deer-flow-race' was created concurrently; using it" in messages
    assert "Created namespace 'deer-flow-race'" not in messages


def test_ensure_namespace_creates_a_missing_namespace(monkeypatch, provisioner_module):
    core_v1 = _core_v1(provisioner_module)
    monkeypatch.setattr(provisioner_module, "core_v1", core_v1)

    provisioner_module._ensure_namespace()

    core_v1.create_namespace.assert_called_once()


def test_ensure_namespace_skips_create_when_the_namespace_exists(monkeypatch, provisioner_module):
    core_v1 = _core_v1(provisioner_module, read_status=None)
    monkeypatch.setattr(provisioner_module, "core_v1", core_v1)

    provisioner_module._ensure_namespace()

    core_v1.create_namespace.assert_not_called()


@pytest.mark.parametrize(
    "read_status, create_status",
    [
        pytest.param(404, 403, id="create-forbidden"),
        pytest.param(403, None, id="read-forbidden"),
    ],
)
def test_ensure_namespace_still_fails_on_other_api_errors(monkeypatch, provisioner_module, read_status, create_status):
    core_v1 = _core_v1(provisioner_module, read_status=read_status, create_status=create_status)
    monkeypatch.setattr(provisioner_module, "core_v1", core_v1)

    with pytest.raises(provisioner_module.ApiException) as error:
        provisioner_module._ensure_namespace()

    assert error.value.status == 403
