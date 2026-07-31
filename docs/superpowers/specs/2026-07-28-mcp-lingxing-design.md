# mcp-lingxing MCP Server 设计文档（B 子项目：自建领星 API 包装）

**日期：** 2026-07-28
**状态：** 已确认，待实现
**来源文档：** `爆品打造专家agent/爆品打造专家Agent_设计文档_v1.md`（第 3.2 节 mcp-lingxing 14 工具）
**父项目拆分：** 爆品打造专家 Agent v1 拆为 5 个子项目（A–E），本 spec 覆盖 B。A（飞书 MCP 接入）已完成。

---

## 1. 目标

自建 `mcp-lingxing` MCP Server，包装领星 ERP OpenAPI，暴露 7 个 P0 工具供 deer-flow agent 调用拉数据。架构参考已完成的 `governance/kb_mcp/`（FastMCP + 独立 Python 包 + SSE 传输）。

**已端到端验证可行性：**
- appId/appSecret 调 `/api/auth-server/oauth/access-token` 换 access_token 成功（2h 有效 + refresh_token）
- 签名算法（MD5 → AES/ECB/PKCS5 → URL 编码）调 `/erp/sc/data/seller/lists` 返回真实店铺数据 ✓

**非目标：**
- 不做 P1/P2 工具（msku_ad/keyword_heat/competitor/return_rate/inventory_health 等）—— 第二阶段
- 不做 BMB 利润工具（但 `statisticsOpenParent` 端点已发现，后续可加）
- 不做 Web 面板
- 不在飞书对话（对话在 deer-flow 前端）

---

## 2. 架构

```
governance/lingxing_mcp/              # 自建 MCP Server（独立 Python 包，uv 管理）
├── pyproject.toml                    # 依赖：mcp>=1.27, httpx, pycryptodome, caching
├── governance_lingxing_mcp/
│   ├── __init__.py
│   ├── server.py                     # FastMCP 入口，暴露 7 个 MCP tool
│   ├── config.py                     # 配置（appId/appSecret/host/port/TTL）
│   ├── auth.py                       # OAuth token 获取 + 自动 refresh + 缓存
│   ├── signing.py                    # 签名算法（MD5 + AES/ECB/PKCS5 + URL 编码）
│   ├── client.py                     # 领星 API HTTP client（带签名 + TTL 缓存）
│   └── tools/                        # 7 个 P0 工具实现
│       ├── parent_sales.py           # lx_parent_sales
│       ├── parent_ad.py              # lx_parent_ad
│       ├── campaign_perf.py          # lx_campaign_perf
│       ├── keyword_rank.py           # lx_keyword_rank
│       ├── keyword_share.py          # lx_keyword_share
│       ├── review_rating.py         # lx_review_rating
│       └── inventory_days.py        # lx_inventory_days
├── tests/                            # 单元测试（签名 + auth + 各工具 stub）
└── data/                             # 运行时缓存（gitignored）

extensions_config.json                # 注册 lingxing-mcp 为 MCP Server（on-disk, gitignored）
extensions_config.example.json        # example 模板加 lingxing-mcp 条目（enabled: false）
```

**数据流：**
```
deer-flow agent → DeerFlow MCP Client → lingxing-mcp :8102 (SSE)
  → auth.py (token 缓存/refresh) → signing.py (签名) → client.py (HTTP + TTL 缓存)
  → 领星 OpenAPI (https://openapi.lingxing.com/)
```

lingxing-mcp 作为独立 Python 进程运行在 :8102，通过 SSE 传输与 deer-flow 通信。deer-flow 侧不改任何代码，只在 `extensions_config.json` 加一条 MCP Server 注册。

---

## 3. 鉴权与签名（已验证）

### 3.1 OAuth Token 获取

- **端点**：`POST https://openapi.lingxing.com/api/auth-server/oauth/access-token`
- **参数**（FormData）：`appId` + `appSecret`
- **返回**：`access_token`（2h 有效）+ `refresh_token`（7d 有效）
- **自动 refresh**：token 过期前自动用 refresh_token 续约（调 `/api/auth-server/oauth/refresh-token`）
- **缓存**：access_token 内存缓存，过期前 5 分钟自动 refresh

### 3.2 签名算法（7 步，已端到端验证）

1. 构造 `paramsMap` = 业务参数 + `access_token` + `app_key`(=appId) + `timestamp`
2. 移除 `sign` + `api_code`
3. 参数按 key 字典序排序：`sortedKeys = sorted(paramsMap.keys())`
4. 拼接参数字符串：`paramStr = '&'.join(f'{k}={paramsMap[k]}' for k in sortedKeys)`
5. MD5 加密转大写：`md5Hash = MD5(paramStr).hexdigest().upper()`
6. **AES/ECB/PKCS5Padding 加密**：key = `appId` UTF-8 编码补齐到 16 字节（`\x00` 填充），加密 md5Hash，Base64 编码
7. URL 编码：`sign = urllib.parse.quote(base64_sign, safe='')`

### 3.3 凭据来源

- `LINGXING_APP_ID` + `LINGXING_APP_SECRET` 环境变量
- 用户已提供：appId=`ak_Wwkrr5Y4eRBpb`，appSecret=`g2tCvhPwDjs7Vh5F8ilh8Q==`
- IP 白名单：需确认当前公网 IP 是否在领星后台已配（`https://toolbox.lingxing.com/api/getIp` 查公网 IP）

---

## 4. 7 个 P0 工具

> **P0 数量说明**：设计文档第 3.2 节表格里 P0 标记的有 7 个（lx_parent_sales/parent_ad/campaign_perf/keyword_rank/keyword_share/review_rating/inventory_days），正文说"2 周内 P0 工具 9 个必做"。本 spec 以表格的 7 个 P0 标记为准。

### 4.1 `lx_parent_sales` — 产品表现（父ASIN）

- **领星 API**：`/erp/sc/data/...`（`docs/Statistics/AsinListNew` 查询产品表现）
- **返回字段**：达成率、Sessions、CVR、Orders、销售额（父ASIN 级）
- **实时性**：T+1
- **TTL**：6 小时

### 4.2 `lx_parent_ad` — 广告报表（父ASIN）

- **领星 API**：`/erp/sc/data/...`（`docs/newAd/report/spProductAdReports` SP广告商品报表）
- **返回字段**：父ASIN 曝光/点击/CTR/CPC/花费/ACOS/ROAS/ACOAS
- **实时性**：小时级
- **TTL**：30 分钟

### 4.3 `lx_campaign_perf` — 广告活动报表

- **领星 API**：`/erp/sc/data/...`（`docs/newAd/report/spCampaignReports` SP广告活动报表）
- **返回字段**：活动级 CTR/CVR/ACOS/ROAS/花费
- **实时性**：小时级
- **TTL**：30 分钟

### 4.4 `lx_keyword_rank` — 关键词排名

- **领星 API**：`/erp/sc/data/...`（`docs/Tools/GetKeywordList` 关键词列表）
- **返回字段**：关键词 广告位/自然位排名
- **实时性**：T+1
- **TTL**：6 小时
- **⚠️ Risk**：关键词排名查询 API 文档被注释（`keywordRankingAdd` 等），可能下线/迁移。实现时需试 API 端点或用领星官方 MCP 的 `query_erp_keyword_ranking_keyword` 对照

### 4.5 `lx_keyword_share` — 搜索词流量占比

- **领星 API**：`/erp/sc/data/...`（`docs/newAd/report/queryWordReports` SP用户搜索词报表）
- **返回字段**：搜索词流量占比/订单占比/ACOS
- **实时性**：T+1
- **TTL**：6 小时

### 4.6 `lx_review_rating` — 评论/评分

- **领星 API**：`/erp/sc/data/...`（`docs/Service/reviewV2` 评价管理-Review新）
- **返回字段**：星级、评论数、新增差/好评、差评内容
- **实时性**：近实时
- **TTL**：**不缓存，实时拉**（紧急级）

### 4.7 `lx_inventory_days` — 库存/可售天数

- **领星 API**：`/erp/sc/data/...`（`docs/Warehouse/FBAStock_v2` FBA库存v2 + `docs/FBASug/DailySalesInfoFeatureASIN` 销量预测+库存预测）
- **返回字段**：在库、在途、日均销、可售天数
- **实时性**：日
- **TTL**：1 小时

---

## 5. TTL 缓存策略（内存级，不持久化）

| 数据类 | TTL | 说明 |
|--------|-----|------|
| 业务报告（产品表现/Sessions/CVR） | 6 小时 | T+1 数据，一天变化一次 |
| 广告数据（ACOS/ROAS/活动/关键词） | 30 分钟 | 小时级刷新，防限频 |
| 评论/评分 | **不缓存** | 紧急级 |
| 库存可售天数 | 1 小时 | 断货风险 |

缓存用 `cachetools.TTLCache`（内存级，进程重启清空，不持久化）。

---

## 6. deer-flow 接入

零代码侵入，纯配置接入。

### 6.1 extensions_config.json 注册（on-disk, gitignored）

```json
{
  "mcpServers": {
    "lingxing-mcp": {
      "enabled": true,
      "type": "sse",
      "url": "http://localhost:8102/sse",
      "description": "领星 ERP API 包装（7 个 P0 工具：产品表现/广告/关键词/评论/库存）",
      "tool_call_timeout": 60
    }
  }
}
```

### 6.2 extensions_config.example.json 模板（tracked）

加 `lingxing-mcp` 条目，`enabled: false`（需先配置 LINGXING_APP_ID/SECRET 环境变量 + IP 白名单）。

### 6.3 启动方式

```bash
# 单独启动 lingxing-mcp
cd governance/lingxing_mcp && LINGXING_APP_ID=ak_... LINGXING_APP_SECRET=... uv run python -m governance_lingxing_mcp.server

# 或用 Makefile target（后续加）
# deer-flow 重启后会自动连接 lingxing-mcp
```

---

## 7. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| MCP Server 框架 | `mcp` Python SDK（`FastMCP`） | 官方 SDK，与 kb_mcp 一致 |
| HTTP client | `httpx` | 与 kb_mcp 一致，支持 async |
| 加密 | `pycryptodome` | AES/ECB/PKCS5Padding（已验证可用） |
| 缓存 | `cachetools`（`TTLCache`） | 轻量内存缓存 |
| 传输协议 | SSE（HTTP） | 独立服务，与 kb_mcp 一致 |
| 包管理 | `uv` | 与 deer-flow 后端 + kb_mcp 一致 |

---

## 8. 验证标准

1. lingxing-mcp 能启动并响应 SSE 连接（`curl http://localhost:8102/sse` 返回 200）
2. `lx_parent_sales` 能调通领星 API 返回产品表现数据
3. `lx_parent_ad` 能调通返回广告报表数据
4. `lx_review_rating` 能调通返回评论/评分数据
5. TTL 缓存生效（同参数 30 分钟内重复调用走缓存）
6. token 自动 refresh（模拟 token 过期，自动续约）
7. deer-flow agent 对话中能自动调用 lingxing-mcp 工具拉数据
8. 降级：领星 API 超时/错误时返回空结果 + 日志告警，不崩溃 agent

---

## 9. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| 关键词排名 API 文档被注释，端点可能下线 | 中 | 实现时试 API 端点；不行则用领星官方 MCP 的 `query_erp_keyword_ranking_keyword` 对照端点；或降级为"暂不可用" |
| IP 白名单未配置 → API 返回 IP 不在白名单 | 中 | 实现时检查 response，提示用户配置 IP 白名单 |
| access_token 过期未及时 refresh | 低 | auth.py 在过期前 5 分钟自动 refresh；refresh_token 也过期则重新 appId/appSecret 换 |
| 领星 API 限频 | 中 | TTL 缓存防限频；client.py 加重试 + 限频保护 |
| AES key 补齐方式不对（ZeroPadding vs PKCS7） | 已解决 | 已端到端验证：`\x00` 补齐到 16 字节 + PKCS7 padding 数据，调通成功 |

---

## 10. 后续子项目衔接

- **C** 多维表 schema 搭建：通过 A 的 lark-base skill 写表。依赖 A（已完成）。
- **D** 规则引擎 + LLM 归因 Skill：调用 B 的工具拉数据 + 规则判定 + 归因。依赖 B（本 spec）。
- **E** 每日 9:00 定时任务：触发 D 技能跑 B 工具 + 写多维表 + 推送。依赖 A/B/C/D。
