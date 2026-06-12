# UV_EXTRAS 单点配置设计

## 问题描述

当前 `UV_EXTRAS` 默认值 `postgres,pymupdf` 同时出现在两个文件：

| 文件 | 位置 | 默认值 |
|------|------|--------|
| `docker/docker-compose.yaml:72` | `${UV_EXTRAS:-postgres,pymupdf}` | 内联 |
| `backend/Dockerfile:50` | `ARG UV_EXTRAS` 无默认值，shell 展开 `${UV_EXTRAS:-postgres,pymupdf}` | 内联 |

添加新 extra（如 `duckdb`）需要同步修改两处，容易遗漏或不一致。

## 约束条件

- docker compose build 时需要通过 `--build-arg UV_EXTRAS` 传入值（Dockerfile 的 ARG 无法从 docker-compose 的 env 自动读取）
- 最终效果：`uv sync --extra postgres --extra pymupdf`，多个 extra 需要多个 `--extra` 标志
- 添加新 extra 时应该只修改一个文件

## 方案分析

### 方案 A（推荐）：Dockerfile 为唯一真实来源

**改动：**
- `docker-compose.yaml:72` → `UV_EXTRAS: ${UV_EXTRAS}`（移除默认值，透传环境变量）
- Dockerfile 保留 `${UV_EXTRAS:-postgres,pymupdf}` 作为默认值

**效果：**
| 操作 | 修改文件 |
|------|---------|
| 添加新默认 extra | 只改 `backend/Dockerfile:50` |
| 用户覆盖全部 extras | `UV_EXTRAS=postgres,pymupdf,duckdb docker compose build` |

**优点：**
1. 语义清晰 — Dockerfile 是实际执行 `uv sync` 的地方，应该声明默认值
2. docker-compose 只负责传参，不定义业务默认值
3. 单点修改即可扩展默认 extras

### 方案 B：docker-compose.yaml 为唯一真实来源

**改动：**
- `Dockerfile:18` → `ARG UV_EXTRAS=postgres,pymupdf`（声明默认值）
- `docker-compose.yaml:72` → `UV_EXTRAS: ${UV_EXTRAS}`（透传）
- shell 展开改为直接引用 `$_extras="${UV_EXTRAS}"`（ARG 有默认值则无需 fallback）

**问题：**
ARG 声明和 shell 展开仍是两处引用，本质上只是把"默认值"从 shell 移到了 ARG，仍有同步风险。

### 方案 C：自动化展开脚本

**改动：**
在 Dockerfile 中用 shell 动态生成 `--extra` 标志链。

**问题：** 过度设计，增加维护成本。

## 推荐方案

**方案 A** — Dockerfile 作为单一真实来源。

```
添加 duckdb 流程：
1. 修改 backend/Dockerfile 第50行：
   _extras="${UV_EXTRAS:-postgres,pymupdf,duckdb}"
2. docker compose build gateway
```

docker-compose.yaml 不定义业务默认值，只透传环境变量。用户可以随时通过环境变量覆盖。

## 遗留说明

当前修改已经解决了两个实际问题：
1. `--extra` 标志展开（`postgres,pymupdf` → `--extra postgres --extra pymupdf`）
2. 运行时 libpq5 安装（PostgreSQL 客户端库依赖）

这两个修改与单点配置的设计是正交的，可以在后续实施。