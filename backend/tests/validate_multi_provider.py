"""Simple validation test for multi_provider structure (no dependencies required)."""

import os
import sys

# Add packages/harness to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "harness"))


def test_file_structure():
    """Verify all multi_provider files exist."""
    base_path = os.path.join(os.path.dirname(__file__), "..", "packages", "harness", "deerflow", "community", "multi_provider")

    files = ["__init__.py", "types.py", "adapters.py", "tools.py"]

    for f in files:
        path = os.path.join(base_path, f)
        assert os.path.exists(path), f"Missing file: {f}"

    print("✅ All multi_provider files exist")


def test_types_module():
    """Test types module can be imported and has required classes."""
    from deerflow.community.multi_provider.types import ProviderConfig, SearchResult

    # Test SearchResult
    result = SearchResult(title="Test", url="https://example.com", snippet="Snippet")
    assert result.type == "page"
    assert result.to_dict()["url"] == "https://example.com"

    # Test ProviderConfig
    config = ProviderConfig(name="searxng", enabled=True)
    assert config.name == "searxng"
    assert config.enabled is True

    print("✅ Types module works correctly")


def test_config_structure():
    """Verify config.yaml has multi_provider configuration."""
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")

    with open(config_path) as f:
        content = f.read()

    assert "multi_provider" in content, "config.yaml should reference multi_provider"
    assert "searxng_host" in content, "config.yaml should have searxng_host"
    assert "providers:" in content, "config.yaml should have providers array"

    print("✅ config.yaml has multi_provider configuration")


if __name__ == "__main__":
    print("Running multi_provider structure validation...\n")

    try:
        test_file_structure()
        test_types_module()
        test_config_structure()

        print("\n✅ All structure validation tests passed!")
        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Validation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
