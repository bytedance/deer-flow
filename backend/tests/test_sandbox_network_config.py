import pytest
from pydantic import ValidationError

from deerflow.config.sandbox_config import SandboxConfig, SandboxNetworkConfig


def test_sandbox_network_defaults_to_open() -> None:
    config = SandboxConfig(use="test")

    assert config.network.mode == "open"
    assert config.network.allow_domains == []
    assert config.network.approval == "prompt"


def test_sandbox_network_normalizes_domains() -> None:
    config = SandboxNetworkConfig(allow_domains=["PyPI.org.", "*.PythonHosted.org", "pypi.org"])

    assert config.allow_domains == ["pypi.org", "*.pythonhosted.org"]


@pytest.mark.parametrize(
    "domain",
    [
        "*",
        "https://pypi.org",
        "pypi.org:443",
        "foo.*.example.com",
        "../example.com",
        "127.0.0.1",
        "localhost",
        "foo..example.com",
        "-foo.example.com",
        "foo_.example.com",
    ],
)
def test_sandbox_network_rejects_unsafe_domain_rules(domain: str) -> None:
    with pytest.raises(ValidationError, match="invalid sandbox network allowlist domain"):
        SandboxNetworkConfig(allow_domains=[domain])
