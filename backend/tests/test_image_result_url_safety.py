"""The image providers enforce the same string-only result URL policy."""

import importlib
from unittest.mock import patch

import pytest


@pytest.fixture(params=["url_safety", "brave.tools", "serper.tools", "infoquest.infoquest_client"])
def screen(request):
    module = importlib.import_module(f"deerflow.community.{request.param}")
    return module.safe_public_result_url if request.param == "url_safety" else module._safe_public_url


@pytest.mark.parametrize(
    "url",
    [
        "http://metadata.google.internal/image",
        "http://[64:ff9b::7f00:1]/image",
        "http://[::ffff:127.0.0.1]/image",
        "http://[2002:7f00:1::]/image",
        "http://[::10.0.0.1]/image",
        "http://224.0.0.1/image",
        "http://3758096385/image",
        "http://[ff02::1]/image",
        "http://[2002:e000:1::]/image",
        "http://240.0.0.1/image",
        "http://127.0.0.1/image",
        "http://0x7f000001/image",
        "http://0177.0.0.1/image",
        "http://localhost./image",
        "file:///etc/passwd",
    ],
)
def test_image_providers_reject_non_public_results(screen, url):
    assert screen(url) == ""


@pytest.mark.parametrize(
    "url",
    ["https://images.example/image", "http://8.8.8.8/image", "http://134744072/image", "http://[2606:4700:4700::1111]/image"],
)
def test_image_providers_keep_public_results_without_dns(screen, url):
    with patch("socket.getaddrinfo", side_effect=AssertionError("Result screening must not perform DNS")):
        assert screen(url) == url
