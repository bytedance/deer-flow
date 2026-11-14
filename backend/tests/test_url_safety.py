"""Address classification shared by every SSRF-screened web tool."""

import ipaddress

import pytest

from deerflow.community.url_safety import is_blocked_address, validate_delegated_backend_url, validate_public_http_url


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


@pytest.mark.parametrize(
    "base_url",
    [
        "http://localhost:3032",
        "http://127.0.0.1:3032",
        "http://10.0.0.5:3032",
        "http://169.254.169.254:3032",
        "http://[::1]:3032",
    ],
)
def test_delegated_backend_fails_closed_on_private_addresses(base_url):
    error = validate_delegated_backend_url(base_url)

    assert error is not None
    assert "network_isolation_confirmed" in error


def test_delegated_backend_fails_closed_when_unresolvable():
    error = validate_delegated_backend_url("http://browserless:3000", resolver=lambda _host: [])

    assert error is not None
    assert "network_isolation_confirmed" in error


def test_delegated_backend_allows_public_address():
    error = validate_delegated_backend_url("https://production-sfo.browserless.io", resolver=lambda _host: [ipaddress.ip_address("93.184.216.34")])

    assert error is None


def test_delegated_backend_allows_private_when_isolation_confirmed():
    assert validate_delegated_backend_url("http://10.0.0.5:3032", network_isolation_confirmed=True) is None


def test_delegated_backend_rejects_non_http_scheme():
    assert validate_delegated_backend_url("ftp://example.com") == "Error: Only http:// and https:// backend URLs are supported"


def _must_not_resolve(_host):
    raise AssertionError("a malformed URL must be rejected before DNS resolution")


# A raw bracket in the userinfo slot is malformed per RFC 3986. urlparse()
# rejects some of these forms itself; the others are caught by the userinfo
# check in _parse_url(), which mirrors the SkillScan host parser (#8017).
# One list drives both validators so a newly discovered malformed shape is
# covered by both at once.
_MALFORMED_URLS = [
    "http://[::1/api",  # unmatched IPv6 bracket: urlparse() raises ValueError
    "http://[::1]@Example.COM/api",  # bracketed userinfo: urlparse() raises on some versions
    "http://[]@example.com/api",  # empty bracketed host in userinfo: urlparse() raises
    "http://[@[::1]/",  # raw "[" in userinfo: urlparse() succeeds, userinfo check fires
    "http://u]@[::1]/",  # raw "]" in userinfo: exercises the closing-bracket half
    "http://a@b[c]@[2606:4700:4700::1111]/",  # the last "@" separates userinfo from host
]


@pytest.mark.parametrize("url", _MALFORMED_URLS)
def test_public_validator_returns_error_for_malformed_url(url):
    error = validate_public_http_url(url, resolver=_must_not_resolve)

    assert error == "Error: URL could not be parsed"


@pytest.mark.parametrize("url", _MALFORMED_URLS)
def test_delegated_backend_validator_returns_error_for_malformed_url(url):
    error = validate_delegated_backend_url(url, resolver=_must_not_resolve)

    assert error == "Error: Backend URL could not be parsed"


@pytest.mark.parametrize("value", [b"http://example.com", None, 123, ["http://example.com"]])
def test_public_validator_returns_error_for_non_string_input(value):
    # The signature says str, but these guards must never raise: a non-string
    # value is malformed input, not an exception. Mirrors the isinstance guard
    # in safe_public_result_url().
    error = validate_public_http_url(value, resolver=_must_not_resolve)

    assert error == "Error: URL could not be parsed"


@pytest.mark.parametrize("value", [b"http://example.com", None, 123, ["http://example.com"]])
def test_delegated_backend_validator_returns_error_for_non_string_input(value):
    error = validate_delegated_backend_url(value, resolver=_must_not_resolve)

    assert error == "Error: Backend URL could not be parsed"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # A plain userinfo must still pass through to address classification.
        ("https://user:pass@[2606:4700:4700::1111]/", None),
        # ...and must not hide a private host.
        ("http://user@[::1]/", "Error: Refusing to fetch a private, loopback, or metadata address"),
    ],
)
def test_public_validator_keeps_legitimate_userinfo(url, expected):
    assert validate_public_http_url(url, resolver=_must_not_resolve) == expected


def test_delegated_backend_validator_keeps_legitimate_userinfo():
    assert validate_delegated_backend_url("https://user:pass@[2606:4700:4700::1111]/", resolver=_must_not_resolve) is None

    error = validate_delegated_backend_url("http://user@[::1]/", resolver=_must_not_resolve)

    assert error is not None
    assert "network_isolation_confirmed" in error


@pytest.mark.parametrize("url", ["http://[::1/api", "http://[@[::1]/"])
def test_public_validator_rejects_malformed_url_before_bypassing_private_checks(url):
    # Parsing must happen before the allow_private_addresses escape hatch: a
    # malformed URL is not a usable URL at all.
    assert validate_public_http_url(url, allow_private_addresses=True) == "Error: URL could not be parsed"


@pytest.mark.parametrize("url", ["http://[::1/api", "http://[@[::1]/"])
def test_delegated_backend_validator_rejects_malformed_url_before_isolation_bypass(url):
    assert validate_delegated_backend_url(url, network_isolation_confirmed=True) == "Error: Backend URL could not be parsed"
