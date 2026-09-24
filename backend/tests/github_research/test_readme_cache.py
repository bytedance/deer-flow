from deerflow.community.github_research.cache import ReadmeCache


def test_cache_hit_and_miss():
    cache = ReadmeCache()

    assert cache.get("repo-a") is None

    cache.set("repo-a", {"content": "README 正文"})
    assert cache.get("repo-a") == {"content": "README 正文"}


def test_cache_expires_without_sleeping():
    # 模拟时间，不需要真的等待五分钟。
    now = [0.0]
    cache = ReadmeCache(
        ttl_seconds=300,
        clock=lambda: now[0],
    )
    cache.set("repo-a", {"content": "正文"})

    now[0] = 299.0
    assert cache.get("repo-a") is not None

    # 读取不会延长有效期。
    now[0] = 300.0
    assert cache.get("repo-a") is None


def test_least_recently_used_is_removed():
    cache = ReadmeCache(max_entries=2)
    cache.set("a", {"content": "A"})
    cache.set("b", {"content": "B"})

    # 访问 a，因此 b 变成最久没有使用的条目。
    cache.get("a")
    cache.set("c", {"content": "C"})

    assert cache.get("a") is not None
    assert cache.get("b") is None
    assert cache.get("c") is not None


def test_caller_cannot_modify_cached_data():
    cache = ReadmeCache()
    original = {"content": "原始正文"}

    cache.set("a", original)
    original["content"] = "外部修改"

    result = cache.get("a")
    assert result["content"] == "原始正文"

    result["content"] = "再次修改"
    assert cache.get("a")["content"] == "原始正文"


def test_different_keys_are_separate():
    cache = ReadmeCache()
    cache.set("a", {"content": "A"})
    cache.set("b", {"content": "B"})

    assert cache.get("a")["content"] == "A"
    assert cache.get("b")["content"] == "B"


def test_clear():
    cache = ReadmeCache()
    cache.set("a", {"content": "A"})
    cache.clear()

    assert cache.get("a") is None