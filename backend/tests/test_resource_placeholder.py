"""Tests for the canonical resource placeholder formatter."""

from deerflow.tools.resource_placeholder import resource_placeholder_text


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
