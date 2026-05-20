# DeerFlow 部署模式选择与授权说明

## 一、两种运行模式的区别

| 项目 | Standard mode (`make dev`) | Gateway mode (`make dev-pro`) |
|------|---------------------------|-------------------------------|
| 进程数量 | 4 个独立进程 | 3 个进程 |
| 进程列表 | LangGraph Server + Gateway + Frontend + nginx | Gateway（嵌入 Agent 运行时）+ Frontend + nginx |
| Agent 位置 | 独立 LangGraph Server (port 2024) | 嵌入在 Gateway 进程内 |
| 并发管理 | 独立服务间调度 | 异步任务（asyncio） |
| 生产可用性 | ✅ 成熟稳定 | ⚠️ 实验性（experimental） |
| 推荐场景 | 生产级部署、规模化使用 | 开发调试、小规模验证 |

**架构简图**

Standard mode:
```
nginx(2026) → LangGraph Server(2024) + Gateway(8001) + Frontend(3000)
```

Gateway mode:
```
nginx(2026) → Gateway(8001, 内嵌Agent) + Frontend(3000)
```

## 二、100 并发会话应选择哪种模式

**推荐：Standard mode (`make dev`)**

理由：
- **独立扩展** — LangGraph Server 与 Gateway 可独立扩缩容
- **稳定性** — Gateway 模式标注为实验性，不适合生产级负载
- **资源隔离** — 避免 Gateway 进程内部资源竞争

Gateway 模式仅适用于：
- 开发调试场景
- 20 并发以下的小规模流量
- 临时快速验证

## 三、授权相关

### DeerFlow 本身
DeerFlow 许可证需查看项目根目录 `LICENSE` 文件确认。

### LangGraph Server
- **版本**：开源版（自部署）
- **许可证**：Apache 2.0
- **商业使用**：✅ 允许，无需付费

### 其他依赖组件

| 组件 | 许可证 | 商业使用 |
|------|--------|---------|
| LangGraph | Apache 2.0 | ✅ 无需付费 |
| FastAPI | MIT | ✅ 无需付费 |
| Next.js | MIT | ✅ 无需付费 |
| nginx | BSD | ✅ 无需付费 |

### LangGraph 商业版（仅供参考）
LangGraph Cloud/Platform 是商业版，提供托管、监控等企业功能，但**与你无关**——你部署的是开源版本，不涉及商业授权。

## 四、内网部署安全建议

> ⚠️ 文档原文：Running on LAN/public cloud without IP allowlisting or authentication gateway is a security risk.

建议在内网部署时添加：
- IP 白名单（推荐）
- 认证网关（如 API Key 验证）
