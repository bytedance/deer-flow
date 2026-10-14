# 多租户实施接续记录 — 2026-10-14

用户要求保存当前进度，明天继续。本次暂停不缩小“完成统一计划”的范围；M0–M11完整验收仍未完成。

## 工作位置和已验证提交

- 功能 worktree：`/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2`。
- 分支：`codex/tenant-workspaces-plan`。不要修改环境默认的 `1d28/deerflow2` 上游 worktree。
- `1596886f`：原生 Run 查询按可信空间、原用户、兼容私有 ThreadMeta 父记录过滤；分页/游标/再生成来源/批量/用量均在 SQL 过滤后处理。
- `4c0ea948`：非 Run 的 reject 预约保存 workspace；workspace→actor→thread→clock→Run 锁序；释放匹配捕获空间、用户和 worker，不删除普通 Run；撤权和空间切换不妨碍清理。
- Jenkins `deerflow-tenant-m1-postgres` #42 RED（两数据库跨空间读取），#43 GREEN（8 passed, 21.74s）；#44 RED（预约 workspace NULL），#45 GREEN（7 passed, 21.58s）。
- #42–#45 的每个专属容器/网络 ownership label 已独立查空；最后观察到的 #45 为 SUCCESS。没有为本次未验证草稿启动新构建。
- 证据/源码与归档哈希：`docs/tenant-workspaces-progress.json`；完整设计与计划仍是 `docs/superpowers/specs/2026-10-13-tenant-workspaces-design.md` 和 `docs/superpowers/plans/2026-10-13-tenant-workspaces.md`。

## 暂停时新增草稿，尚未运行

仅修改 `backend/tests/test_workspace_http.py`，扩展已有两数据库真实认证主干，没有新增生产代码：

1. 配置真实 required-scope RunRepository 和原生 RunManager。
2. 新 UUID 会话通过 PUT goal 创建团队私有 ThreadMeta/checkpoint，预约最终清空。
3. 已有团队会话 POST state 更新 title，并同步原生会话标题；个人空间状态不变。
4. 外空间 PUT goal / POST state / DELETE goal 返回404。
5. DELETE goal 清空并可再次读取。
6. 实际 SQL incarnation 在 checkpoint 准备读取时轮换，拒绝旧实例写入，checkpoint ID 不变。
7. 真实 owner admission 后撤销 policy，拒绝写入，checkpoint ID 不变。

草稿只通过本地 Ruff check；未执行 pytest，也未取得 RED/GREEN。已准备本地公开源码归档 `/private/tmp/deerflow-tenant-m3-checkpoint-write-red.tar.gz`，SHA256 `976ec90433e69f4ff8b98f25d404a5ee86937f864703d219c40f7b0fbf4072fb`；尚未上传或触发任务。恢复时以当前源码重新打包，不能依赖临时文件永远存在。

## 明天按此顺序继续

1. 查真实 Git 状态、当前源码和 Jenkins 状态；前一构建已终止，不因观察超时重启运行中的构建。
2. 从现有 PG Jenkins 模板派生 `m3-checkpoint-write-red`，仅运行 `tests/test_workspace_http.py`，确认真正业务失败后再实现。模板位于 `/private/tmp/deerflow-tenant-m3-reservation-red-job.py`；打包脚本 `/private/tmp/prepare-tenant-gate.py` 会生成非PG模板，应在打包后替换成 PG 模板。
3. 为 PUT/DELETE goal 与 POST state 绑定可信 scope，先于 native owner-check；ScopeDenied/HTTPException 必须穿透宽泛异常处理，不能变500。
4. 保留 `/chats/new` 先设置 goal 的原生行为：scoped模式先只建立 SQL ThreadMeta，再取得持久预约，最后受控写 checkpoint；不在预约前写 checkpoint。现有 `_ensure_thread_for_goal` 同时创建 metadata/checkpoint，需拆开或增加明确 metadata-only 路径。
5. 图/schema构建及状态准备在 SQL 锁外进行；捕获私有会话 incarnation，在短提交前重验 live workspace/actor/thread/incarnation。使用专门的 checkpoint 提交边界，不把现有“只用于短文件操作”的 publish_under_live_lock 偷换成模型/图构建锁。回调只允许已准备的原生 checkpoint IO，排除模型/工具/网络业务执行；明确 cancellation drain 和跨库锁序。
6. 重跑相同 HTTP 主干，加入受影响的原生 goal/state 回归；保留失败历史、实际源码哈希及清理证据，更新文档再提交。
7. 继续 M3 生命周期、API/feed/客户端切换，随后依次 M4–M11。不得把已验证的 SQL 预约当作完整后台 Run/租户激活。

## 持续约束

- 所有 pytest、真实后端/模型/Docker 测试在上海 Jenkins/ECS；不启动本地 Docker Desktop或本地 pytest。
- Jenkins 地址 `106.14.210.163`，仅管理 DeerFlow 专属任务。认证只在 Jenkins 本机内存读取已有0600私有文件，不输出/复制凭据；不处理 assetforge 发布审批。
- 测试容器与 PG 使用内部网络、现有测试镜像、CPU/内存限制和专属 label 清理；不挂生产数据库、NAS或Docker socket。
- 已停用的 compiled tenant activation 保持 false；当前 schema0038/e0002。原部署及迁移/恢复/公开注册门禁仍待 M10–M11。当前分支没有新增远程推送或部署。
- 顺序实施，先主干，后必要边界；不派生并行智能体。邮件/域名配置在后续邮件验收阶段处理。

## 恢复后进展

目标已恢复为 active。上述未验证草稿现已跑通：#46–#48失败历史和 #49的双数据库 HTTP 成功均记录在 progress JSON；goal/state生产写入实现与六项未变源码的原生回归已验证。接下来处理 M3 的完整会话生命周期、Run/activity/API和前端空间切换，仍未部署或开启多租户。暂停时记录的源码归档是历史输入，后续以进度文件中的最新哈希为准。

补充：#50发现 owner-check 期间替换会话仍能提交目标，现已按最初准入身份绑定修复。#51完整定向检查8项通过（34.31s），覆盖真实 SQL 替换下 goal/state/clear 不修改 checkpoint。完整生命周期、Run/feed和前端仍是下一工作，不得把这次验收当作整个 M3 完成。

下一轮生命周期准入还需检查：只有 legacy checkpoint、没有 ThreadMeta 的同名 ID，不能因新建元数据而被接管；同时审计原生 POST thread 和 goal 新建路径。当前未验证这一边界，多租户激活继续关闭。

当前接续更新：上一条所列 checkpoint-only ID guard 已由 #52 RED/#53 GREEN 验证，另有真实原生目标交错初始化保护。下次直接从 M3 分支/删除/压缩生命周期及 Run/feed/客户端切换继续；多租户仍未激活或部署。

分支接续更新：#54 RED/#55 GREEN 已验证私有原生分支主干和六项原生回归。源码通过后以当前提交/进度文件哈希为准；接下来处理删除/压缩、Run/feed与前端。失败分支的私有未发布文件/跨库 checkpoint 需要故障回收证据，不得猜测回滚后删除可能已提交的数据；仍未开启多租户部署。

压缩接续更新：#56 RED/#57 GREEN 已完成原生压缩的空间入口/模型前复核/最终 checkpoint fence 主干（8项，36.66s）。实际摘要中间件保留，只有模型响应确定化；租户记忆/归档和真实模型仍未验收。接下来处理删除生命周期、Run/feed和前端空间切换，M4–M11继续保持完整范围，未部署多租户。

## 本次暂停检查点：私有会话删除（用户要求明天继续）

状态：暂停；最后已验证提交 `b8dae318`（压缩）。本次 DELETE 实现和测试以 WIP 保存，尚未通过 GREEN，不代表 M3 完成。

- Jenkins `deerflow-tenant-m1-postgres` #58：RED，2 failed，34.13s；归档 SHA256 `9e352861b80bc6d7cb753b53894e4c2aa337b8dc34cba55f95cafc2e7f734159`。原入口缺可信空间上下文。该构建已观察到终态，尚未独立复核其 ownership label 清理。
- 当前草稿增加删除 tombstone、捕获 incarnation/token 的清理凭据、精确 SQL 子记录清理、原生预约和受控物理清理；失败后保留 tombstone，拒绝盲目重试。legacy 删除入口保留。
- 双数据库 HTTP 主干草稿覆盖私有/个人数据隔离、准入后撤权、删除中禁止读写和重建、失败后保留及拒绝重试。仅本地 Ruff 检查通过；未运行 GREEN，未部署、未推送远程。
- 草稿仅允许 local sandbox 且无 remote admission host，任何持久 MCP task 都拒绝清理；远端 STOP、崩溃恢复、其他执行器清理仍须 M4/M8/M10/M11 完整验收，不能视为已支持。

明天优先：

1. 检查 Git 和 Jenkins 实际状态。不要重复启动运行中的任务。
2. 审查旧上传/转存请求在删除后同 ID 重建时的 generation 隔离：`publish_under_live_lock` 目前没有 expected incarnation 参数。先检查 ingestion/项目文件转存闭包是否已捕获原 incarnation；如缺失，修正最终发布校验，补一条有意义的旧请求跨代拒绝验证。不要直接宣称当前 DELETE 安全完成。
3. 重新打包当前源码，从 `/private/tmp/deerflow-tenant-m3-delete-red-job.py` PG 模板派生 GREEN，仅在上海运行主干及必要原生回归。临时 GREEN 包 `709c3302162ec955b05947dca84c05bfaf7755f013831ddd3aa58b5c6afeddf3` 尚未上传/触发，任何源码变化后作废。
4. 终态后独立检查 #58 和新构建专属容器/网络清理，对照归档源码哈希，更新证据再提交正式实现。
5. 继续 M3 Run/feed/前端切换，然后顺序 M4–M11。全功能范围不变，租户 compiled activation 仍关闭。

本次不启动新测试，不执行云部署或远程推送。所有 pytest/模型/Docker 仍在上海；不运行本地 Docker Desktop。临时打包/实施脚本可能丢失，优先以已提交的源码与本记录恢复，勿重复执行字符串修改脚本。
