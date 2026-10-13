"""Address classification shared by every SSRF-screened web tool."""

import ipaddress

import pytest

from deerflow.community.url_safety import is_blocked_address, validate_public_http_url


@pytest.mark.parametrize(
    "address",
    [
        "100.64.0.0",
        "100.64.1.1",  # CGNAT / Tailscale node
        "100.100.100.200",  # Alibaba Cloud ECS instance metadata
        "100.127.255.255",
        "::ffff:100.100.100.200",  # IPv4-mapped spelling of the same endpoint
    ],
)
def test_shared_address_space_is_blocked(address):
    assert is_blocked_address(ipaddress.ip_address(address))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "fc00::1",
        "::ffff:127.0.0.1",
        # NAT64 spelling of a metadata address reports is_global, so the
        # reserved/private flags must keep applying alongside it.
        "64:ff9b::a9fe:a9fe",
    ],
)
def test_previously_blocked_addresses_stay_blocked(address):
    assert is_blocked_address(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["8.8.8.8", "93.184.215.14", "100.63.255.255", "100.128.0.0", "2606:4700:4700::1111"])
def test_public_addresses_stay_reachable(address):
    assert not is_blocked_address(ipaddress.ip_address(address))


def test_validator_refuses_a_hostname_resolving_into_shared_address_space():
    error = validate_public_http_url("http://metadata.example/latest/meta-data/", resolver=lambda _host: [ipaddress.ip_address("100.100.100.200")])

    assert error == "Error: Refusing to fetch a private, loopback, or metadata address"
