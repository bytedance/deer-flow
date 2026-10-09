"""Tests for the canonical resource placeholder formatter and location gate."""

from deerflow.tools.resource_placeholder import model_visible_location, resource_placeholder_text


def test_full_shape_with_name_mime_and_url():
    assert resource_placeholder_text(name="doc", mime_type="application/pdf", url="/mnt/user-data/outputs/doc.pdf") == "[Resource: doc (application/pdf) available at /mnt/user-data/outputs/doc.pdf]"


def test_name_falls_back_to_unnamed_at_call_site_contract():
    # Call sites that have a ResourceLink pass `item.name or "unnamed"`.
    assert resource_placeholder_text(name="unnamed", mime_type=None, url="ui://ads/card") == "[Resource: unnamed (unknown type) available at ui://ads/card]"


def test_nameless_shape_matches_persisted_block_rewrite():
    assert resource_placeholder_text(mime_type="text/html;profile=mcp-app", url="ui://ads/card") == "[Resource (text/html;profile=mcp-app) available at ui://ads/card]"


def test_empty_and_none_url_omit_location_segment():
    assert resource_placeholder_text(name="doc", mime_type="application/pdf", url="") == "[Resource: doc (application/pdf)]"
    assert resource_placeholder_text(mime_type=None, url=None) == "[Resource (unknown type)]"


def test_gate_keeps_virtual_paths_and_remote_schemes():
    assert model_visible_location("/mnt/user-data/outputs/notes.txt") == "/mnt/user-data/outputs/notes.txt"
    assert model_visible_location("https://example.com/report.pdf") == "https://example.com/report.pdf"
    assert model_visible_location("ui://app/card.html") == "ui://app/card.html"
    assert model_visible_location("s3://bucket/report.pdf") == "s3://bucket/report.pdf"


def test_gate_withholds_host_paths():
    assert model_visible_location("file:///Users/ops/secret.pdf") is None
    assert model_visible_location("/srv/deploy-internal/secret.pdf") is None
    assert model_visible_location("C:\\Users\\ops\\creds.txt") is None


def test_gate_withholds_inline_payloads():
    # A `data:` URI embeds its whole base64 payload; a `blob:` URI names a
    # browser-local object nothing else can dereference.
    assert model_visible_location("data:application/pdf;base64,QUFB") is None
    assert model_visible_location("blob:https://example.com/550e8400") is None


def test_gate_maps_falsy_to_none():
    assert model_visible_location(None) is None
    assert model_visible_location("") is None
