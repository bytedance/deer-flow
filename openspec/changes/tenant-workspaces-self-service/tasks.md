# Implementation tasks

Status: partial M0/M1/M2/M3 foundations verified, including member controls, credential-reset/ownership-transfer serialization, production router registration, startup fencing and actual private-project CRUD SQL scoping and private project upload/list/download/trash with before-send revocation, explicit shared project/document ACLs and private-default legacy migration; no complete work-package acceptance yet. See docs/tenant-workspaces-progress.json for exact scope and Jenkins evidence.

- [ ] 1. M0 — 冻结入口清单与空间合同。验收：缺少/伪造空间上下文被拒绝；单用户模式保持原有行为；入口清单无未指定处理方式的运行路径。
- [ ] 2. M1 — 租户与成员模型、增量迁移及个人空间回填。验收：空库及0035/e0001隔离副本升级成功；8 runs/4 mcp_tasks/12 execution jobs等既有实际记录按清单校验保留而非硬编码业务数量；重复回填幂等，冲突记录不开放。
- [ ] 3. M2 — 统一空间授权、成员与管理员开通API。验收：管理员开通空间后指定owner可登录使用；owner/admin/member遵循权限表；并发转让/退出不会失去owner；跨空间ID请求404。
- [ ] 4. M3 — 原生资源、文件及客户端空间切换贯通。验收：同一用户在个人空间和团队空间各上传/提问/下载一份文件成功；切换后无旧数据闪现；未授权空间无法列举或直接读取。
- [ ] 5. M4 — B/C、Scheduler、通知和撤权贯通。验收：一个空间的一次确定性C→B→C仍使用原生任务权威；切换UI空间不改变运行归属；移除成员阻止queued启动与后续发布，物理STOP未确认不释放容量。
- [ ] 6. M5 — 记忆、知识检索与工具凭据隔离。验收：A/B各含唯一哨兵文本，直接读取、检索、prompt构建及跨线程引用均不串用；成员可用空间连接但无法读密钥；全局插件安装仍拒绝租户admin。
- [ ] 7. M6 — 自助注册、邮箱验证、邀请接受和密码恢复。验收：用户真实收信验证后获得个人空间，接受团队邀请；重复/过期/错邮箱拒绝；GET预取不消费；重置后旧session/PAT失效；正常管理员开通仍可用。
- [ ] 8. M7 — 团队管理、注册与共享资料界面。验收：浏览器完成管理员开通和客户自注册两条主干，各可建立团队邀请成员；第二标签页切换不会改写第一标签页运行归属；错误不暴露内部堆栈。
- [ ] 9. M8 — 配额、用量、审计和空间生命周期。验收：A达到并发/任务/存储额度不影响B；同一结果重复回报不重计；停用无新启动、恢复无自动重放；最后owner无法直接销号；保留期与清理回执可查。
- [ ] 10. M9 — 个人研究与定期跟进业务主干。验收：报告来源指向该空间真实文档及版本；更新说明新增信息；用户可以暂停；另一空间无法访问来源、报告或定时结果。
- [ ] 11. M10 — 隔离副本迁移、恢复与Jenkins交付。验收：断在metadata升级后仍不放行，重入读取回执并安全继续；成套备份能恢复原镜像与数据；跨schema仅镜像回滚被拒绝；新源码/镜像/数据库版本一致。
- [ ] 12. M11 — 集中边界验收、文档与发布结论。验收：两种开户入口及同一业务能力均通过，没有未覆盖的租户入口；失败历史保留；具备邮件配置、隔离和迁移证据后才允许公开注册。

Detailed steps: `../../../docs/superpowers/plans/2026-10-13-tenant-workspaces.md`.

M3 thread repository checkpoint: #25 RED (NULL scope, both databases), #26 GREEN (7 passed, 29.58s). Owner-private thread SQL and shared-project association are verified. HTTP admission, checkpoint/run/files and frontend remain incomplete; parent M3 stays unchecked.
