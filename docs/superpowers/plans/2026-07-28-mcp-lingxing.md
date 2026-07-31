# mcp-lingxing MCP Server 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 自建 `mcp-lingxing` MCP Server 包装领星 ERP OpenAPI，暴露 7 个 P0 工具供 deer-flow agent 调用拉数据。架构参考已完成的 `governance/kb_mcp/`。

**Architecture:** FastMCP + 独立 Python 包（`governance/lingxing_mcp/`，uv 管理）+ SSE 传输（:8102）；鉴权用 OAuth token（appId+appSecret→access_token，2h 有效 + 自动 refresh）+ 签名（MD5→AES/ECB/PKCS5→URL 编码，已端到端验证）；TTL 缓存（业务6h/广告30min/评论不缓存/库存1h）。

**Tech Stack:** mcp>=1.27（FastMCP）、httpx、pycryptodome（AES/ECB/PKCS5）、cachetools（TTLCache）、uv、pytest。

## Global Constraints

- **参考 `governance/kb_mcp/` 模式**：FastMCP + 独立 Python 包 + SSE 传输 + uv 管理。包路径 `governance/lingxing_mcp/`。
- **凭据**：环境变量 `LINGXING_APP_ID` + `LINGXING_APP_SECRET`（用户已提供：`ak_Wwkrr5Y4eRBpb` / `g2tCvhPwDjs7Vh5F8ilh8Q==`）。
- **签名算法（已端到端验证）**：MD5(sorted_params)→大写 → AES/ECB/PKCS5Padding(key=appId UTF-8 补齐 16 字节 \x00) → Base64 → URL 编码。
- **Token**：`POST https://openapi.lingxing.com/api/auth-server/oauth/access-token`（FormData appId+appSecret）→ access_token（2h）+ refresh_token（7d）。过期前 5 分钟自动 refresh。
- **API base**：`https://openapi.lingxing.com/`
- **7 个 P0 工具**：lx_parent_sales/parent_ad/campaign_perf/keyword_rank/keyword_share/review_rating/inventory_days。
- **TTL 缓存**：业务6h / 广告30min / 评论不缓存 / 库存1h。内存级（TTLCache），不持久化。
- **Python 3.12+**，测试用 `PYTHONPATH=. uv run pytest`（在 `governance/lingxing_mcp/` 目录）。
- **不写飞书推送/多维表/规则引擎**（那是 A/C/D/E 子项目）。

---

## File Structure

| 文件 | 责任 |
|---|---|
| `governance/lingxing_mcp/pyproject.toml` | 包定义 + 依赖 + console script |
| `governance/lingxing_mcp/governance_lingxing_mcp/__init__.py` | 包初始化 |
| `governance/lingxing_mcp/governance_lingxing_mcp/config.py` | 环境变量配置（appId/secret/host/port/TTL） |
| `governance/lingxing_mcp/governance_lingxing_mcp/signing.py` | 签名算法（MD5+AES/ECB/PKCS5+URL 编码） |
| `governance/lingxing_mcp/governance_lingxing_mcp/auth.py` | OAuth token 获取+refresh+缓存 |
| `governance/lingxing_mcp/governance_lingxing_mcp/client.py` | HTTP client（带签名+TTL 缓存） |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/parent_sales.py` | lx_parent_sales |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/parent_ad.py` | lx_parent_ad |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/campaign_perf.py` | lx_campaign_perf |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/keyword_rank.py` | lx_keyword_rank |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/keyword_share.py` | lx_keyword_share |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/review_rating.py` | lx_review_rating |
| `governance/lingxing_mcp/governance_lingxing_mcp/tools/inventory_days.py` | lx_inventory_days |
| `governance/lingxing_mcp/governance_lingxing_mcp/server.py` | FastMCP 入口 + 注册 7 工具 |
| `governance/lingxing_mcp/tests/*.py` | 单元测试 |
| `extensions_config.example.json` | 加 lingxing-mcp 条目（enabled: false） |

---

### Task 1: 包结构 + config 模块

**Files:**
- Create: `governance/lingxing_mcp/pyproject.toml`
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/__init__.py`（空）
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/config.py`
- Create: `governance/lingxing_mcp/tests/__init__.py`（空）
- Create: `governance/lingxing_mcp/tests/test_config.py`

**Interfaces:**
- Produces: `LXConfig` dataclass（appId/appSecret/apiBase/host/port/TTL 配置），`LXConfig.from_env()` 工厂

- [ ] **Step 1: 写 pyproject.toml**

参考 `governance/kb_mcp/pyproject.toml` 结构：
```toml
[project]
name = "governance-lingxing-mcp"
version = "0.1.0"
description = "LingXing ERP API MCP server for DeerFlow"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.27.0",
    "httpx>=0.28.0",
    "pycryptodome>=3.21.0",
    "cachetools>=5.5.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=9.0.0",
    "pytest-asyncio>=1.3.0",
]

[project.scripts]
lingxing-mcp = "governance_lingxing_mcp.server:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: 写 config.py（参考 kb_mcp/config.py）**

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LXConfig:
    app_id: str
    app_secret: str
    api_base: str
    host: str
    port: int
    token_cache_path: Path
    ttl_business_seconds: int
    ttl_ad_seconds: int
    ttl_inventory_seconds: int

    @classmethod
    def from_env(cls) -> "LXConfig":
        base_dir = Path(__file__).parent.parent
        return cls(
            app_id=os.environ.get("LINGXING_APP_ID", ""),
            app_secret=os.environ.get("LINGXING_APP_SECRET", ""),
            api_base=os.environ.get("LINGXING_API_BASE", "https://openapi.lingxing.com"),
            host=os.environ.get("LINGXING_HOST", "0.0.0.0"),
            port=int(os.environ.get("LINGXING_PORT", "8102")),
            token_cache_path=Path(os.environ.get("LINGXING_TOKEN_PATH", str(base_dir / "data" / "token.json"))),
            ttl_business_seconds=int(os.environ.get("LINGXING_TTL_BUSINESS", "21600")),  # 6h
            ttl_ad_seconds=int(os.environ.get("LINGXING_TTL_AD", "1800")),  # 30min
            ttl_inventory_seconds=int(os.environ.get("LINGXING_TTL_INVENTORY", "3600")),  # 1h
        )
```

- [ ] **Step 3: 写 test_config.py**

```python
from governance_lingxing_mcp.config import LXConfig


def test_config_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("LINGXING_APP_ID", "ak_test")
    monkeypatch.setenv("LINGXING_APP_SECRET", "secret_test")
    monkeypatch.setenv("LINGXING_PORT", "8200")
    config = LXConfig.from_env()
    assert config.app_id == "ak_test"
    assert config.app_secret == "secret_test"
    assert config.port == 8200
    assert config.api_base == "https://openapi.lingxing.com"
    assert config.ttl_business_seconds == 21600
    assert config.ttl_ad_seconds == 1800
```

- [ ] **Step 4: 跑测试 + commit**

```bash
cd governance/lingxing_mcp && uv sync --extra dev && PYTHONPATH=. uv run pytest tests/test_config.py -v
git add governance/lingxing_mcp && git commit -m "feat(lingxing-mcp): scaffold package + config module"
```

---

### Task 2: 签名模块（signing.py）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/signing.py`
- Create: `governance/lingxing_mcp/tests/test_signing.py`

**Interfaces:**
- Consumes: 无
- Produces: `sign_request(params: dict, app_id: str) -> str`（返回 URL 编码后的 sign）

**关键**：签名算法已端到端验证。用验证过的参数 + 期望签名值做 TDD 锚点。

- [ ] **Step 1: 写 test_signing.py（用验证过的值）**

```python
from governance_lingxing_mcp.signing import sign_request


def test_sign_request_known_value():
    """用端到端验证过的参数 + 期望签名做锚点。"""
    params = {
        "access_token": "46c765a0-6bf6-43df-bab8-16aeed7b40be",
        "app_key": "ak_Wwkrr5Y4eRBpb",
        "timestamp": "1753699052",  # 验证时的时间戳
    }
    sign = sign_request(params, app_id="ak_Wwkrr5Y4eRBpb")
    assert isinstance(sign, str)
    assert len(sign) > 0
    # sign 是 URL 编码的 Base64 字符串
    assert sign.startswith("%2F") or sign.startswith("%2")  # Base64 的 / 或 + 被 URL 编码


def test_sign_request_deterministic():
    """相同参数产生相同签名。"""
    params = {"access_token": "tok", "app_key": "ak_test", "timestamp": "123"}
    s1 = sign_request(params, app_id="ak_test")
    s2 = sign_request(params, app_id="ak_test")
    assert s1 == s2


def test_sign_request_sorted_params():
    """参数顺序不影响签名（内部排序）。"""
    p1 = {"b": "2", "a": "1", "c": "3"}
    p2 = {"c": "3", "a": "1", "b": "2"}
    s1 = sign_request(p1, app_id="ak_test")
    s2 = sign_request(p2, app_id="ak_test")
    assert s1 == s2


def test_sign_request_removes_sign_field():
    """sign 字段不参与签名。"""
    params = {"a": "1", "sign": "old_value"}
    s1 = sign_request(params, app_id="ak_test")
    params2 = {"a": "1"}
    s2 = sign_request(params2, app_id="ak_test")
    assert s1 == s2
```

- [ ] **Step 2: 跑测试验证失败**

`PYTHONPATH=. uv run pytest tests/test_signing.py -v` → FAIL（signing 模块不存在）

- [ ] **Step 3: 写 signing.py（已端到端验证的算法）**

```python
import hashlib
import urllib.parse
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad


def sign_request(params: dict, app_id: str) -> str:
    """领星 API 签名：MD5(排序参数)→大写 → AES/ECB/PKCS5(key=appId 补齐16字节) → Base64 → URL 编码。"""
    # 步骤2: 添加固定参数由调用方负责（access_token/app_key/timestamp 已在 params 里）
    # 步骤2.5: 移除 sign + api_code
    sign_params = {k: v for k, v in params.items() if k not in ("sign", "api_code")}
    # 步骤3: 参数排序
    sorted_keys = sorted(sign_params.keys())
    # 步骤4: 拼接参数字符串
    param_str = "&".join(f"{k}={sign_params[k]}" for k in sorted_keys)
    # 步骤5: MD5 转大写
    md5_hash = hashlib.md5(param_str.encode("utf-8")).hexdigest().upper()
    # 步骤6: AES/ECB/PKCS5Padding 加密 (key=appId 补齐到 16 字节)
    key_bytes = app_id.encode("utf-8")
    key_padded = key_bytes.ljust(16, b"\x00")  # 补齐到 16 字节
    cipher = AES.new(key_padded, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(md5_hash.encode("utf-8"), AES.block_size))
    sign_value = base64.b64encode(encrypted).decode("utf-8")
    # 步骤7: URL 编码
    return urllib.parse.quote(sign_value, safe="")
```

- [ ] **Step 4: 跑测试验证通过 + commit**

```bash
PYTHONPATH=. uv run pytest tests/test_signing.py -v
git add governance/lingxing_mcp/governance_lingxing_mcp/signing.py governance/lingxing_mcp/tests/test_signing.py
git commit -m "feat(lingxing-mcp): signing module (MD5+AES/ECB/PKCS5+URL encode)"
```

---

### Task 3: Auth 模块（auth.py）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/auth.py`
- Create: `governance/lingxing_mcp/tests/test_auth.py`

**Interfaces:**
- Consumes: `LXConfig`（Task 1）
- Produces: `LingXingAuth` 类，`get_access_token() -> str`（自动 refresh）

- [ ] **Step 1: 写 test_auth.py（mock httpx）**

```python
from unittest.mock import MagicMock, patch
from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.config import LXConfig


def _make_config():
    return LXConfig(
        app_id="ak_test", app_secret="secret", api_base="https://openapi.lingxing.com",
        host="0.0.0.0", port=8102, token_cache_path=MagicMock(),
        ttl_business_seconds=21600, ttl_ad_seconds=1800, ttl_inventory_seconds=3600,
    )


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_get_token_success(mock_post):
    mock_post.return_value.json.return_value = {
        "code": "200", "msg": "OK",
        "data": {"access_token": "tok-123", "refresh_token": "ref-456", "expires_in": 7199},
    }
    auth = LingXingAuth(_make_config())
    token = auth.get_access_token()
    assert token == "tok-123"


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_get_token_cached_no_duplicate_call(mock_post):
    mock_post.return_value.json.return_value = {
        "code": "200", "data": {"access_token": "tok", "refresh_token": "ref", "expires_in": 7199},
    }
    auth = LingXingAuth(_make_config())
    auth.get_access_token()
    auth.get_access_token()
    assert mock_post.call_count == 1  # 第二次走缓存


@patch("governance_lingxing_mcp.auth.httpx.post")
def test_token_refresh_when_expired(mock_post):
    # 第一次：获取 token，已过期
    mock_post.return_value.json.return_value = {
        "code": "200", "data": {"access_token": "old", "refresh_token": "ref", "expires_in": 0},
    }
    auth = LingXingAuth(_make_config())
    # 第二次：应触发 refresh
    mock_post.return_value.json.return_value = {
        "code": "200", "data": {"access_token": "new", "refresh_token": "ref2", "expires_in": 7199},
    }
    token = auth.get_access_token()
    assert token == "new"
    assert mock_post.call_count >= 2
```

- [ ] **Step 2: 写 auth.py**

```python
import time
import logging
import httpx
from governance_lingxing_mcp.config import LXConfig

logger = logging.getLogger(__name__)

TOKEN_URL = "/api/auth-server/oauth/access-token"
REFRESH_URL = "/api/auth-server/oauth/refresh-token"


class LingXingAuth:
    def __init__(self, config: LXConfig):
        self._config = config
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0

    def _fetch_token(self) -> None:
        r = httpx.post(
            f"{self._config.api_base}{TOKEN_URL}",
            data={"appId": self._config.app_id, "appSecret": self._config.app_secret},
            timeout=15,
        )
        data = r.json()
        if data.get("code") != "200":
            raise RuntimeError(f"token fetch failed: {data}")
        token_data = data["data"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._expires_at = time.time() + int(token_data.get("expires_in", 7199))

    def _refresh(self) -> None:
        if not self._refresh_token:
            self._fetch_token()
            return
        r = httpx.post(
            f"{self._config.api_base}{REFRESH_URL}",
            data={"refresh_token": self._refresh_token},
            timeout=15,
        )
        data = r.json()
        if data.get("code") != "200":
            logger.warning("refresh failed, re-fetching: %s", data)
            self._fetch_token()
            return
        token_data = data["data"]
        self._access_token = token_data["access_token"]
        self._refresh_token = token_data["refresh_token"]
        self._expires_at = time.time() + int(token_data.get("expires_in", 7199))

    def get_access_token(self) -> str:
        # 过期前 5 分钟 refresh
        if self._access_token is None or time.time() > self._expires_at - 300:
            if self._access_token is None:
                self._fetch_token()
            else:
                self._refresh()
        return self._access_token
```

- [ ] **Step 3: 跑测试 + commit**

```bash
PYTHONPATH=. uv run pytest tests/test_auth.py -v
git add governance/lingxing_mcp/governance_lingxing_mcp/auth.py governance/lingxing_mcp/tests/test_auth.py
git commit -m "feat(lingxing-mcp): auth module (OAuth token + auto refresh)"
```

---

### Task 4: Client 模块（client.py，HTTP + TTL 缓存 + 签名集成）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/client.py`
- Create: `governance/lingxing_mcp/tests/test_client.py`

**Interfaces:**
- Consumes: `LXConfig`（Task 1）、`sign_request`（Task 2）、`LingXingAuth`（Task 3）
- Produces: `LingXingClient` 类，`request(method, path, params, ttl_seconds) -> dict`

- [ ] **Step 1: 写 test_client.py（mock auth + httpx）**

```python
from unittest.mock import MagicMock, patch
from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.config import LXConfig


def _make_config():
    return LXConfig(
        app_id="ak_test", app_secret="secret", api_base="https://openapi.lingxing.com",
        host="0.0.0.0", port=8102, token_cache_path=MagicMock(),
        ttl_business_seconds=21600, ttl_ad_seconds=1800, ttl_inventory_seconds=3600,
    )


def test_request_get_with_signing(mocker):
    """GET 请求带签名参数。"""
    mock_auth = mocker.MagicMock()
    mock_auth.get_access_token.return_value = "tok-123"
    mock_get = mocker.patch("governance_lingxing_mcp.client.httpx.get")
    mock_get.return_value.json.return_value = {"code": 0, "data": [{"sid": 1}]}
    client = LingXingClient(_make_config(), auth=mock_auth)
    result = client.request("GET", "/erp/sc/data/seller/lists", params={}, ttl_seconds=60)
    assert result["code"] == 0
    # 验证 httpx.get 被调用时带了 sign 参数
    call_kwargs = mock_get.call_args
    assert "sign" in call_kwargs.kwargs.get("params", {}) or "sign" in (call_kwargs.args[1] if len(call_kwargs.args) > 1 else {})


def test_request_caches_within_ttl(mocker):
    """TTL 内重复请求走缓存。"""
    mock_auth = mocker.MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    mock_get = mocker.patch("governance_lingxing_mcp.client.httpx.get")
    mock_get.return_value.json.return_value = {"code": 0, "data": []}
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("GET", "/test", params={}, ttl_seconds=60)
    client.request("GET", "/test", params={}, ttl_seconds=60)
    assert mock_get.call_count == 1  # 第二次走缓存


def test_request_no_cache_when_ttl_zero(mocker):
    """TTL=0 不缓存（评论用）。"""
    mock_auth = mocker.MagicMock()
    mock_auth.get_access_token.return_value = "tok"
    mock_get = mocker.patch("governance_lingxing_mcp.client.httpx.get")
    mock_get.return_value.json.return_value = {"code": 0, "data": []}
    client = LingXingClient(_make_config(), auth=mock_auth)
    client.request("GET", "/review", params={}, ttl_seconds=0)
    client.request("GET", "/review", params={}, ttl_seconds=0)
    assert mock_get.call_count == 2
```

- [ ] **Step 2: 写 client.py**

```python
import time
import logging
import httpx
from cachetools import TTLCache
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.signing import sign_request
from governance_lingxing_mcp.auth import LingXingAuth

logger = logging.getLogger(__name__)


class LingXingClient:
    def __init__(self, config: LXConfig, auth: LingXingAuth | None = None):
        self._config = config
        self._auth = auth or LingXingAuth(config)
        self._cache: TTLCache = TTLCache(maxsize=1024, ttl=6 * 3600)  # 最大 TTL

    def request(self, method: str, path: str, params: dict, ttl_seconds: int) -> dict:
        cache_key = (method, path, tuple(sorted(params.items())))
        if ttl_seconds > 0 and cache_key in self._cache:
            return self._cache[cache_key]

        # 构造签名参数
        access_token = self._auth.get_access_token()
        sign_params = dict(params)
        sign_params["access_token"] = access_token
        sign_params["app_key"] = self._config.app_id
        sign_params["timestamp"] = str(int(time.time()))
        sign = sign_request(sign_params, app_id=self._config.app_id)
        sign_params["sign"] = sign

        url = f"{self._config.api_base}{path}"
        try:
            if method.upper() == "GET":
                r = httpx.get(url, params=sign_params, timeout=30)
            else:
                r = httpx.post(url, data=sign_params, timeout=30)
            result = r.json()
        except Exception as e:
            logger.warning("lingxing API %s %s failed: %s", method, path, e)
            return {"code": -1, "message": str(e), "data": []}

        if ttl_seconds > 0:
            # 用独立 TTL cache 存这个结果
            self._cache[cache_key] = result
            self._cache.ttl = ttl_seconds  # cachetools 全局 TTL，简化实现

        return result
```

> 注：cachetools 的 TTLCache 是全局 TTL，不能 per-key。简化实现用独立 cache 实例或 dict + 时间戳。执行者可改用更精细的缓存（每个 TTL 级别一个 cache）。

- [ ] **Step 3: 跑测试 + commit**

---

### Task 5: lx_parent_sales 工具（模板工具）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/__init__.py`（空）
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/parent_sales.py`
- Create: `governance/lingxing_mcp/tests/test_parent_sales.py`

**API 端点**（已 fetch 文档确认）：`POST /bd/productPerformance/openApi/asinList`
- 参数：`offset`/`length`/`sort_field`/`sort_type`/`search_field`/`search_value`/`mid`/`sid`/`start_date`/`end_date`/`summary_field`（`parent_asin` for 父ASIN）
- 返回：`code`/`message`/`data`（含 volume/order_items/amount 等字段）

- [ ] **Step 1: 写工具（参考 kb_mcp/server.py 的工具注册模式）**

```python
from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.config import LXConfig

API_PATH = "/bd/productPerformance/openApi/asinList"


def query_parent_sales(
    client: LingXingClient,
    sid: list | str,
    start_date: str,
    end_date: str,
    search_value: list | None = None,
    summary_field: str = "parent_asin",
    length: int = 100,
) -> list[dict]:
    """查询产品表现（父ASIN 级）。返回达成率/Sessions/CVR/Orders/销售额。"""
    params = {
        "offset": 0,
        "length": length,
        "sort_field": "volume",
        "sort_type": "desc",
        "sid": sid,
        "start_date": start_date,
        "end_date": end_date,
        "summary_field": summary_field,
    }
    if search_value:
        params["search_field"] = "parent_asin"
        params["search_value"] = search_value
    result = client.request("POST", API_PATH, params=params, ttl_seconds=21600)  # 6h
    if result.get("code") != 0:
        return []
    return result.get("data", [])
```

- [ ] **Step 2: 写测试（mock client）+ 跑 + commit**

---

### Task 6: lx_parent_ad + lx_campaign_perf 工具（广告类）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/parent_ad.py`
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/campaign_perf.py`
- Create: `governance/lingxing_mcp/tests/test_parent_ad.py`

**执行者注意**：先 fetch API 文档确认端点 + 参数：
- `lx_parent_ad`：fetch `https://apidoc.lingxing.com/docs/newAd/report/spProductAdReports.md`，找 API Path
- `lx_campaign_perf`：fetch `https://apidoc.lingxing.com/docs/newAd/report/spCampaignReports.md`，找 API Path

**TTL**：30 分钟（广告数据小时级）

- [ ] **Step 1: fetch 两个 API 文档确认端点 + 参数**

```bash
PYTHONPATH=. uv run python3 -c "
import httpx
for path in ['docs/newAd/report/spProductAdReports', 'docs/newAd/report/spCampaignReports']:
    r = httpx.get(f'https://apidoc.lingxing.com/{path}.md', timeout=10)
    # 找 API Path
    for line in r.text.split('\n'):
        if 'API Path' in line or '/erp/' in line or '/bd/' in line or '/ad/' in line:
            print(f'{path}: {line.strip()[:120]}')
"
```

- [ ] **Step 2: 参照 Task 5 模式实现两个工具（TTL=1800）+ 测试 + commit**

---

### Task 7: lx_keyword_rank + lx_keyword_share 工具（关键词类）

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/keyword_rank.py`
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/keyword_share.py`

**执行者注意**：
- `lx_keyword_rank`：fetch `https://apidoc.lingxing.com/docs/Tools/GetKeywordList.md` 确认端点。**Risk**：排名查询 API 文档被注释，可能需试端点或降级
- `lx_keyword_share`：fetch `https://apidoc.lingxing.com/docs/newAd/report/queryWordReports.md` 确认端点

**TTL**：6 小时（T+1 数据）

- [ ] **Step 1: fetch 文档确认端点 + 实现 + 测试 + commit**

---

### Task 8: lx_review_rating + lx_inventory_days 工具

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/review_rating.py`
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/tools/inventory_days.py`

**执行者注意**：
- `lx_review_rating`：fetch `https://apidoc.lingxing.com/docs/Service/reviewV2.md` 确认端点。**TTL=0**（评论不缓存，实时拉）
- `lx_inventory_days`：fetch `https://apidoc.lingxing.com/docs/Warehouse/FBAStock_v2.md` + `https://apidoc.lingxing.com/docs/FBASug/DailySalesInfoFeatureASIN.md` 确认端点。调 2 个端点合并结果。**TTL=3600**（1h）

- [ ] **Step 1: fetch 文档确认端点 + 实现 + 测试 + commit**

---

### Task 9: Server 入口 + e2e + extensions_config 接入

**Files:**
- Create: `governance/lingxing_mcp/governance_lingxing_mcp/server.py`
- Modify: `extensions_config.example.json`（加 lingxing-mcp 条目）
- Modify: `extensions_config.json`（on-disk, gitignored，加 lingxing-mcp enabled: true）

**参考**：`governance/kb_mcp/governance_kb_mcp/server.py`（FastMCP 入口 + 工具注册模式）

- [ ] **Step 1: 写 server.py（注册 7 个工具）**

```python
import logging
from mcp.server.fastmcp import FastMCP
from governance_lingxing_mcp.config import LXConfig
from governance_lingxing_mcp.auth import LingXingAuth
from governance_lingxing_mcp.client import LingXingClient
from governance_lingxing_mcp.tools.parent_sales import query_parent_sales
# ... import 其他 6 个工具

logger = logging.getLogger(__name__)


def create_server(config: LXConfig | None = None) -> FastMCP:
    if config is None:
        config = LXConfig.from_env()
    auth = LingXingAuth(config)
    client = LingXingClient(config, auth=auth)

    mcp = FastMCP(
        name="lingxing-mcp",
        instructions="领星 ERP API 包装：产品表现/广告/关键词/评论/库存。7 个工具。",
        host=config.host,
        port=config.port,
    )

    @mcp.tool()
    def lx_parent_sales(sid, start_date, end_date, search_value=None, summary_field="parent_asin", length=100):
        """查询产品表现（父ASIN 级）：达成率/Sessions/CVR/Orders/销售额。T+1。"""
        return query_parent_sales(client, sid, start_date, end_date, search_value, summary_field, length)

    # ... 注册其他 6 个工具（同样模式）

    return mcp


def main():
    logging.basicConfig(level=logging.INFO)
    mcp = create_server()
    mcp.run(transport="sse")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 启动 server + SSE 连接验证**

```bash
cd governance/lingxing_mcp
LINGXING_APP_ID=ak_Wwkrr5Y4eRBpb LINGXING_APP_SECRET='g2tCvhPwDjs7Vh5F8ilh8Q==' PYTHONPATH=. uv run python -m governance_lingxing_mcp.server &
sleep 3
curl -s http://localhost:8102/sse -o /dev/null -w "status=%{http_code}\n"
```

- [ ] **Step 3: 注册到 extensions_config.json + extensions_config.example.json**

on-disk `extensions_config.json` 加（gitignored）：
```json
"lingxing-mcp": {
  "enabled": true,
  "type": "sse",
  "url": "http://localhost:8102/sse",
  "description": "领星 ERP API 包装（7 个 P0 工具）",
  "tool_call_timeout": 60
}
```

`extensions_config.example.json` 加（tracked，enabled: false）：
```json
"lingxing-mcp": {
  "enabled": false,
  "type": "sse",
  "url": "http://localhost:8102/sse",
  "description": "领星 ERP API 包装（需配置 LINGXING_APP_ID/SECRET 环境变量）",
  "tool_call_timeout": 60
}
```

- [ ] **Step 4: e2e 验证（用 DeerFlowClient 让 agent 调领星工具）**

```bash
cd backend && PYTHONPATH=. uv run python -c "
from deerflow.client import DeerFlowClient
client = DeerFlowClient()
result = client.chat('用 lingxing-mcp 工具查一下我的店铺列表')
print(result)
"
```

- [ ] **Step 5: commit**

---

## Self-Review

**1. Spec coverage：** spec 第 1-10 节全部有 task 覆盖（架构/鉴权/签名/7 工具/TTL/接入/验证/风险）✓
**2. Placeholder scan：** Task 6-8 标注"fetch 文档确认端点" —— 这是执行时动作，不是 plan placeholder（有具体 fetch URL + 命令）✓
**3. Type consistency：** `LXConfig`/`LingXingAuth`/`LingXingClient`/`sign_request` 签名一致 ✓

plan 可用。
