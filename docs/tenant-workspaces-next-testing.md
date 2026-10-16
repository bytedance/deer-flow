# 原生 Next 集成验证

状态：上海 `deerflow-tenant-frontend #126` 完整 Next 构建及两条 HTTP 主干已通过；`#127` 已恢复同一产物并通过四项必要边界。仓库最终 #128 九项相关检查、格式和完整 lint／类型检查通过。精确回执见 progress JSON 的 frontend_ssr_return。开始本轮的代码基线是 `680cc59c`，完整 M0–M11 目标保持未完成。

## 验证范围

`scripts/tenant_next_ssr_probe.py` 在上海专属 Linux 容器内执行完整仓库的 `next build --webpack`，随后启动生产模式的原生 Next 服务并发送 HTTP 文档请求。未登录的团队会话地址必须保留在登录链接的 `next` 中；已经登录后访问该登录链接必须回到同一资源地址。

该流程使用 Next 原生 [Proxy 请求头接口](https://nextjs.org/docs/app/api-reference/file-conventions/proxy) 记录实际请求地址。Proxy 覆盖客户端提供的同名头，头部只用于返回地址，不作为账号、成员资格或空间授权来源。Gateway 认证与空间授权仍必须独立执行。

驱动内的 Gateway **是确定性的认证测试服务**，只提供 setup-status、me 和关闭空间能力的 features 响应；Cookie 也是固定的测试值。本检查不证明真实 JWT、成员资格、数据库、文件挂载、模型调用或业务任务已经贯通。

## 上海执行方式

仅由 DeerFlow 专属 Jenkins 任务运行；不要在本机或 Docker Desktop 执行。源代码包采用已有流程从 Git 受控文件及未忽略的新文件生成，校验 SHA-256 后上传；真实 `.env`、模型配置和密钥不能进入包。

编译容器使用已经缓存的 CI 工具镜像，不拉新镜像：

- 镜像：`deerflow-native:final-ci-tools-52ce`，固定 ID `sha256:4f269f6b0e50f9579e099e91a23df868ff1b1a49c03cc9b138beac02dafb3f01`。
- 账号：`999:987`，专属 evidence 目录 `0700`。
- 资源：1 CPU、4 GiB 内存、内存加 swap 上限 4 GiB；Node heap 2048 MiB。
- 网络：`--network none`，不发布端口。8001 和 3000 都仅在该容器的 loopback 内使用。
- 输入：源码包、已有 pnpm cache 与 node_modules；依赖卷只读。
- 标记：`org.deerflow.tenant.owned=deerflow-tenant-frontend-<build>`，只清理同一精确标记的容器。

容器内先解包到 `/tmp/tenant-source`，把 `frontend/node_modules` 链接到既有 `/deps/node_modules`，通过 `/cache/pnpm-tool/bin` 提供锁定版本 pnpm，再执行：

```bash
DEERFLOW_CLOUD_FIXTURE=1 CI=true NODE_OPTIONS=--max-old-space-size=2048 \
  python3 /tmp/tenant-source/scripts/tenant_next_ssr_probe.py \
  --root /tmp/tenant-source --evidence-dir /evidence
```

驱动统一通过 `scripts/pnpm.py` 调用 pnpm；生产构建明确关闭静态演示和 auth-disabled，内部 Gateway 地址指向本容器的测试服务，不读取真实模型 key。构建超时 20 分钟，Jenkins 整体上限 30 分钟。Next 与测试服务在退出时停止。

## 回执与判断

专属 evidence 目录保留：

- `build.log`：完整 Next 构建日志。
- `server.log`：生产模式 Next 服务日志。
- `result.json`：Next/Node 版本、生产输入摘要、BUILD_ID、构建退出码、HTTP 跳转与失败信息。
- `next-output.tar.gz`：排除 webpack cache 的编译产物，以及 JSON 中对应的 SHA-256。

此编译产物的 Gateway 目的地是测试服务，**不能作为部署或发布产物**。#127 已验证恢复：生产输入摘要、Node／Next 版本、固定测试端口、产物 SHA 和 BUILD_ID 全部匹配才允许复用。输入不符或包含越界／链接条目的归档直接失败，不悄悄重新编译。

后续相同生产输入可在上述容器命令上增加：

```bash
--compiled-archive /run/compiled-next.tar.gz \
--compiled-receipt /run/compiled-next.json --check-boundaries
```

两份输入应从 #126 的 `next-output.tar.gz` 和 `result.json` 只读挂载。#127 的 `build_reused=true`、`build_seconds=0`，BUILD_ID 与归档 SHA 均与 #126 相同。生成路由也须保留请求相关的登录返回地址，不能从构建摘要里的 SSG 标记推断授权行为。

只有 Jenkins 成功、驱动 `main_passed`、两条 HTTP 主干目标正确，且源码与输入包相符，才记录该范围通过。`NextResponse` 可能以 HTTP Location 或原生流式 meta redirect 交付跳转；驱动检验最终本地目标，不把任意 200 当成功。

首次编译可出现缺少构建 cache、Nextra 的 i18n 和无 Git 配置诊断。出现警告不等于失败，也不等于可以忽略错误：以真实退出码、日志和 HTTP 结果判断。任何观察超时都先重查同一构建与容器状态，不自动重启。

## 完整交付仍需验证

请求头伪造、不安全 next、预生成路由和响应头不泄漏已在 #127 的原生 HTTP 中验证。仍须验证真实浏览器导航／水合／回退／多标签，以及真实 Gateway 的账号、资料、任务与下载。当前租户运行总门禁仍关闭；完整业务运行还依赖 M4 的 Run/MCP/Scheduler/B/C 空间归属与后续工作包。保留 M0–M11 总范围，不以本检查代替发布验收。
