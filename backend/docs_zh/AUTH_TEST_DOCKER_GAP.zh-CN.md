# Docker 测试缺口（第七节 7.4）

本文件记录了在完整发布验证通过后，`backend/docs/AUTH_TEST_PLAN.md` 中唯一一组**未执行**的测试用例。

## 为什么会有这个缺口

发布验证环境（sg_dev: `10.251.229.92`）**未安装 Docker daemon**。TC-DOCKER 用例属于容器运行时行为测试，需要真实 Docker 引擎来拉起 `docker/docker-compose.yaml` 中的服务。

```bash
$ ssh sg_dev "which docker; docker --version"
# (empty)
# bash: docker: command not found
```

测试计划中的其余章节均已在以下环境执行：
- 本地开发机（Mac，本地运行全部服务），或
- 已部署的 sg_dev 实例（gateway + frontend + nginx，经 SSH 隧道访问）

## 未执行用例

| 用例 | 标题 | 覆盖内容 | 未执行原因 |
|---|---|---|---|
| TC-DOCKER-01 | `deerflow.db` 卷持久化 | 验证 `DEER_FLOW_HOME` 的 bind mount 在容器重启后仍然保留 | 需要 `docker compose up` |
| TC-DOCKER-02 | 容器重启后的会话持久化 | 验证设置 `AUTH_JWT_SECRET` 后，在 `docker compose down && up` 后 cookie 仍有效 | 需要 `docker compose down/up` |
| TC-DOCKER-03 | 按 worker 划分的限速差异 | 确认进程内 `_login_attempts` 字典不会在 `gunicorn` workers（compose 默认 4 个）之间共享；这是已记录的已知限制 | 需要多 worker 容器环境 |
| TC-DOCKER-04 | IM 渠道使用 Gateway 内部认证 | 验证 Feishu/Slack/Telegram 分发器在调用 Gateway 兼容的 LangGraph API 时，会附带进程内内部认证头及 CSRF cookie/header | 需要 `docker logs` |
| TC-DOCKER-05 | reset 凭据暴露路径 | `reset_admin` 会在 `DEER_FLOW_HOME` 写入 0600 凭据文件，而非日志明文输出。文件写入行为已由非 Docker reset 测试覆盖，因此 Docker 特有缺口仅在于验证卷挂载能将该文件映射到宿主机 | 需要容器 + 宿主机卷 |
| TC-DOCKER-06 | Gateway 模式 Docker 部署 | `./scripts/deploy.sh --gateway` 会形成 3 容器拓扑（无 `langgraph` 容器）；认证流程与标准模式一致 | 需要 `docker compose --profile gateway` |

## 已由非 Docker 测试覆盖的内容

每个 Docker 用例中**与认证相关**的行为，已经由在 sg_dev 或本地执行的测试覆盖：

| Docker 用例 | 已覆盖的认证行为 |
|---|---|
| TC-DOCKER-01（卷持久化） | sg_dev 上的 TC-REENT-01（gateway 重启后 admin 记录仍存在）——同一 SQLite 文件，只是中间没有容器层 |
| TC-DOCKER-02（会话持久化） | TC-API-02/03/06（cookie 往返）+ TC-REENT-04（多 cookie）——JWT 校验不依赖进程状态，容器重启等价于 `pkill uvicorn && uv run uvicorn` |
| TC-DOCKER-03（按 worker 限速） | TC-GW-04 + TC-REENT-09（单 worker 限速 + 5 分钟过期）。跨 worker 差异是内存字典的架构属性；认证代码路径并无差异 |
| TC-DOCKER-04（IM 渠道内部认证） | 代码层面：`app/channels/manager.py` 使用 `create_internal_auth_headers()` + CSRF cookie/header 创建 `langgraph_sdk` client，因此渠道 worker 不依赖浏览器 cookie |
| TC-DOCKER-05（凭据暴露路径） | `reset_admin` 会以 0600 权限写入 `.deer-flow/admin_initial_credentials.txt`，日志只输出路径——Docker 特有步骤仅是验证 bind mount 是否把该路径映射到宿主机，这属于 `docker compose` 配置校验，不是运行时行为变化 |
| TC-DOCKER-06（Gateway 模式容器） | 第七节 7.2 的 TC-GW-01..05 + 第二节（sg_dev 的 Gateway 模式认证流程）已覆盖——同一套 Gateway 代码，容器只是打包方式变化 |

## Docker 可用后的复现步骤

任何安装了 `docker` + `docker compose` 的环境，都可以按测试计划原文复现该缺口。执行前准备如下：

```bash
# 宿主机必需
docker --version           # >=24.x
docker compose version     # plugin >=2.x

# 必需环境变量（否则每次容器重启都会导致会话失效）
echo "AUTH_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  >> .env

# 可选：将 DEER_FLOW_HOME 固定到稳定宿主机路径
echo "DEER_FLOW_HOME=$HOME/deer-flow-data" >> .env
```

然后按测试计划原文执行 TC-DOCKER-01..06。

## 决策记录

- **不阻塞发布。** 每个 Docker 用例中的认证相关行为，都有已在裸机环境验证通过的等价覆盖。当前缺口仅涉及*容器打包*细节（bind mount、多 worker、日志采集），不影响认证代码路径正确性。
- **已在 `AUTH_TEST_PLAN.md` 原位更新 TC-DOCKER-05**，以反映当前 reset 流程（`reset_admin` → 0600 凭据文件、无日志泄露）。旧的 “在 docker 日志里 `grep 'Password:'`” 预期会静默失败，并造成覆盖已完成的错误认知。
