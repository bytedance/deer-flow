# 2026-10-15 暂停与恢复检查点

状态更新：用户已于 2026-10-15 明确要求继续，当前已恢复；最新验证见文末 #35。下面暂停段保留为历史记录。

用户此前要求今天到这里，保存进度并允许本地提交。此检查点是 WIP，不能声称功能验收完成；不要自动继续开发、启动构建、部署或推送。用户再次要求继续后再恢复。

## 代码与已验证范围

- 工作树：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`；分支：`codex/tenant-workspaces-plan`。
- 之前已提交：`0e56c0ac` 上传 hooks；`f17a317c` 普通聊天读写、附件及 SDK 重连存储。最近完整通过的前端构建仍是 `deerflow-tenant-frontend #32`。
- 本次 WIP：侧栏 SDK/归档 REST 搜索、Run 详情、分支/置顶/归档/移动/重命名/删除 hooks 捕获已确认空间客户端；异步缓存操作之后和通知之前检查旧 lifetime。迟到的 sidecar 查询不能继续删除，旧 mutation 不能改投新空间。
- 空间模式删除每个正常枚举的线程直接使用原生 Gateway DELETE，不再先 SDK DELETE 后对同一 ID 再发新 DELETE；未启用空间的原有兼容路径保留。
- 新增三条真实 React/StrictMode 主干，使用真实 Context、REST/SDK/查询/操作 hooks 与网络替身。没有实际浏览器、真实业务后端或物理资源隔离验收证明。

## 最后一轮结果（不能写成通过）

- Jenkins `deerflow-tenant-frontend #33`：RED，三条主干失败，复现缺空间选择器、切换后继续删除、旧归档成功回调。
- `#34`：**FAILURE**。三条新增主干 + 47 条原有回归均通过，共 **50 项**；四文件 Prettier、定向 ESLint 和全库 ESLint 通过；完整 `pnpm check` 的 TypeScript 阶段失败。
- 精确错误：`frontend/tests/unit/core/threads/workspace-actions.dom.test.tsx(275,9): TS2533 Object is possibly 'null' or 'undefined'`。
- 位置：`archived.data?.pages[0]?.[0]?.metadata.deerflow_archived`，`metadata` 的可空类型尚未处理。下次先核实并修正该测试的空值访问，再按现有上海 Jenkins 流程验证；不要把已有行为测试绿色当作完整检查通过。
- `#33/#34` 均终止，独立检查其专属容器和网络为空；`frontend-actions-format` 探针资源为空。依赖缓存保留。没有运行中的本轮构建，不需要明天盲目重启旧句柄。

## 下次顺序

1. 用户明确继续后，先检查工作树、该 WIP 提交及当前 Jenkins 状态。
2. 修正上述测试类型问题，在上海运行相关主干/回归及完整前端检查，记录新的独立源码包和构建号。所有应用运行测试继续仅在上海；不要启动本地 Docker Desktop。
3. 继续绑定 replay prepare、手动 compact、项目内创建线程及页面调用方 await 后的 toast/router/callback；ChatPage 分支、删除对话框和 sidecar 等调用方还需审查。
4. 接项目/产物/预览/下载等剩余资源客户端，按 actor/workspace/reset 生命周期处理 artifact/sessionStorage、线程 UI 状态等。
5. 再接服务端 capability bootstrap、原生样式空间入口和真实浏览器双标签页验收。跨标签页凭据/principal 一致性与主动撤权等仍是必要门槛。

## 不变的总范围

M0–M11 原计划全部保留；当前仍 partial M3，各父验收未完成。M4–M11 的后台执行协议、工具/存储隔离、自助开户团队、配额审计、资料研究报告跟进、迁移恢复和最终验收均不能省略。`_WORKSPACE_RUNTIME_INTEGRATED=False` 保持关闭。此次仅本地 WIP 保存，没有推送、部署或模型调用。

更早的连续记录见 `docs/tenant-workspaces-resume-2026-10-14.md`，详细证据见 `docs/tenant-workspaces-progress.json` 的 `frontend_thread_actions_wip`。


2026-10-15 resumed at explicit user request. M3 thread-action checkpoint:
frontend #33 RED reproduced missing Run selector, old sidecar lookup continuing
to delete, and archive publication after a delayed cache cancellation. #34 passed
50 tests but full check failed on nullable test metadata (TS2533). #35 SUCCESS
reruns the same three mains and 47 native/chat regressions, four-file formatting,
zero-warning target lint and full pnpm check. Optional metadata access still
requires the archive flag to be true; no type assertion bypass. Runtime/test
bytes match its archive; exact #33-#35 and formatter resources independently empty.

Actual SDK/REST sidebar search, Run detail and branch/pin/archive/move/rename/
delete hooks capture the confirmed clients. Post-decode and post-cache-await
checks stop stale mutation publication and callbacks; lookup cancellation cannot
fall through to best-effort deletion. Scoped deletes use the native canonical
Gateway endpoint, avoiding the previous SDK-plus-fresh-REST double request for
each normally enumerated thread. Native unscoped compatibility and its cleanup
retry regressions remain. These are real hooks with network doubles, not actual
browser/backend or physical STOP proof.

Continue with replay prepare, compact and project-thread creation, then UI
callers' await/toast/router fences (ChatPage branch, delete dialog and sidecar).
The native sidecar API's global inFlightCreates map currently keys only parent
thread ID; scope this by confirmed client/lifetime before activation. Other
resource clients, artifact/thread UI storage, actual shell/selector and backend
browser two-tab acceptance still remain. M3 and all M4-M11 gates remain open;
activation stays closed, no deployment/push/local application runtime/model calls.
The earlier user-pause section is historical; the user has explicitly resumed.
