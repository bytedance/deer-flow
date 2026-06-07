import pytest
from pathlib import Path

from tg_intel_crawler.filter.keyword_filter import KeywordFilter


@pytest.fixture
def keyword_filter(tmp_path):
    """Create a keyword filter with test keywords file."""
    keywords_file = tmp_path / "keywords.yaml"
    keywords_file.write_text("""
products:
  - "抖音"
  - "douyin"
  - "tiktok"
  - "字节"

actions:
  - "刷粉"
  - "买号"
  - "引流"
  - "泄露"
""", encoding="utf-8")
    return KeywordFilter(str(keywords_file))


def test_match_both_product_and_action(keyword_filter):
    """Should match when both product and action keywords are present."""
    assert keyword_filter.matches("抖音刷粉服务，联系我") is True


def test_no_match_product_only(keyword_filter):
    """Should NOT match when only product keyword is present."""
    assert keyword_filter.matches("抖音今天发布了新功能") is False


def test_no_match_action_only(keyword_filter):
    """Should NOT match when only action keyword is present."""
    assert keyword_filter.matches("刷粉服务便宜卖") is False


def test_no_match_neither(keyword_filter):
    """Should NOT match when neither keyword category is present."""
    assert keyword_filter.matches("今天天气不错") is False


def test_case_insensitive(keyword_filter):
    """Should match case-insensitively for English keywords."""
    assert keyword_filter.matches("TikTok买号找我") is True
    assert keyword_filter.matches("DOUYIN引流") is True


def test_empty_text(keyword_filter):
    """Should NOT match empty or None text."""
    assert keyword_filter.matches("") is False
    assert keyword_filter.matches(None) is False
