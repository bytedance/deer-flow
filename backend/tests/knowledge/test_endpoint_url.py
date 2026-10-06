"""``join_endpoint`` 的三分支（spec 2026-09-26 rag-endpoint-dedup §2 D1）。

服务商文档给的 base 是把 ``/v1`` 算进去的生态形态（OpenAI SDK / Ollama / SiliconFlow /
百炼兼容面 / Jina 皆然），而通用腿的固定段自己也以 ``/v1/`` 开头 —— 拼接时那节不能重复；
整端点形态则原样保留。今天能用的地址（主机名 / 自定义前缀）结果逐字不变。
"""

from deerflow.knowledge.endpoint_url import join_endpoint


def test_ecosystem_base_with_v1_is_not_doubled():
    # 生态 base：照文档填也打得出门。
    assert join_endpoint("https://host", "/v1/embeddings") == "https://host/v1/embeddings"
    assert join_endpoint("https://host/v1", "/v1/embeddings") == "https://host/v1/embeddings"
    # 尾斜杠等价于没有。
    assert join_endpoint("https://host/v1/", "/v1/embeddings") == "https://host/v1/embeddings"
    # 带自定义路径前缀的生态 base（百炼兼容面形态）。
    assert join_endpoint("https://host/compatible-mode/v1", "/v1/embeddings") == "https://host/compatible-mode/v1/embeddings"


def test_whole_endpoint_is_kept_as_is():
    assert join_endpoint("https://host/v1/embeddings", "/v1/embeddings") == "https://host/v1/embeddings"
    assert join_endpoint("https://host/rerank", "/rerank") == "https://host/rerank"


def test_other_prefixes_join_verbatim():
    # 主机名与自定义前缀（今天能用的形态）逐字不变。
    assert join_endpoint("https://host", "/rerank") == "https://host/rerank"
    assert join_endpoint("https://host/api", "/v1/embeddings") == "https://host/api/v1/embeddings"


def test_rerank_path_never_triggers_the_v1_branch():
    # Jina 惯例：base 自带 /v1、路径是 /rerank ⇒ 结果与今天逐字相同。
    assert join_endpoint("https://host/v1", "/rerank") == "https://host/v1/rerank"
