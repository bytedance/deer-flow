# 个人工作智能体：多租户与自助团队设计

日期：2026-10-13。基线：main 48d5c3deb983b2fc7c9618b38f5d177be6b410e5。
状态：统一范围已获用户确认；部分合同和迁移基础已实施验证，完整多租户功能尚未交付、未部署。本文描述目标设计，实际进展见 `docs/tenant-workspaces-progress.json`。

## 1. 目标与交付范围

产品主线是“资料 → 研究 → 带来源的报告 → 持续跟进”。管理员开通租户与客户自助注册、团队管理合并为一个交付，内部按依赖顺序开发，所有发布门禁通过才允许外部注册。租户在用户界面称“工作空间”，个人空间与团队空间使用同一隔离模型。

本次包含账号注册/邮箱验证/找回密码、管理员开通、空间切换、成员邀请/退出/移除、owner/admin/member、所有权转让、资料与检索隔离、任务和记忆隔离、个人/空间工具凭据、基础配额/审计/注册防滥用、空间停用/恢复/关闭与账户关闭，以及一条真实研究报告及后续更新流程。

不包含付费计费、企业SSO新集成、自定义角色编辑器、跨空间自动分享、客户上传任意Python插件、独立租户数据库部署、跨区域高可用和新Agent引擎。保留已有OIDC登录能力，须满足同一成员与邮箱验证规则。首版不承诺企业高保障物理隔离。共享Gateway/worker进程属于受信计算边界；租户可执行代码仅在受限沙箱内，租户提供的MCP服务必须外置并受连接权限限制，不加载为宿主插件。

## 2. 核对到的原生能力

| 现有接点 | 事实与复用方式 |
| --- | --- |
| app/gateway/routers/auth.py | 已有POST /api/v1/auth/register、登录、改密码、OIDC、PAT；注册受auth.local.allow_registration控制，当前直接创建普通用户并登录。扩展同一路径，不另造登录系统。 |
| app/gateway/auth/models.py；persistence/user/model.py | 全局账号和system_role已存在；认证仓库虽有sqlite命名，UserRow使用原生共享数据库引擎，不能误判成需要新增独立认证库。 |
| app/gateway/authz.py；deerflow/authz/principal.py | 既有身份、路由权限、工具权限继续使用；增加服务器生成的空间成员上下文，权限取交集。 |
| persistence/thread_meta、run、mcp_tasks、scheduled_tasks | 当前主要按user/thread隔离。原生表增加空间归属，继续是任务权威。 |
| config/paths.py | 当前用户路径为users/{user_id}；新增空间命名空间，保留真实user_id，不把tenant_id伪装成user_id。 |
| agents/memory/backends/deermem | 复用事实、修订和检索；把存储及索引分区纳入空间权限，不另造记忆引擎。 |
| routers/knowledge.py；config.example.yaml | 已有RAGFlow/LightRAG检索接点；复用检索接口，数据集授权由服务端空间绑定限制。 |
| MCP、Skills、plugins | 复用业务连接与研究模板；全局操作者插件管理不能开放给租户管理员。 |
| packages/ecs-executor/ecs_executor | 已验收B/C/续跑；在现有签名、执行账、affinity和发布通道加入空间边界，不新增任务系统。 |
| ecs_native_release.py及release_host.py | 已验收0035/e0001同schema发布；本次有schema变化，必须扩展迁移流程，不能直接套用旧锁。 |

## 3. 统一领域与权限

User是全局自然人账号；Workspace是租户；Membership关联两者。个人空间恰好一个owner，不允许邀请和转让；团队空间恰好一个owner，可有多个admin/member。数据库事务锁workspace行，保证并发移除、降级、转让不会丢失最后owner。转让只允许当前owner交给已激活成员，要求近期重新认证；成功后原owner为admin。

平台管理员属于平台控制面，可开通/暂停空间、设置配额、看脱敏用量和操作记录；平台admin身份不能隐式绕过租户资料ACL。平台管理员若要使用某空间，须作为显式成员加入。平台配置/模型供应商/插件安装依旧仅限平台管理员。

| 操作 | owner | admin | member |
| --- | --- | --- | --- |
| 使用授权资料、创建本人会话/任务 | 是 | 是 | 是 |
| 查看空间公开资料/报告 | 是 | 是 | 是 |
| 查看别人私有会话/私人记忆/个人凭据 | 否 | 否 | 否 |
| 邀请/移除普通成员 | 是 | 是 | 否 |
| 任免admin、转让、关闭空间 | 是 | 否 | 否 |
| 管理空间共享资料、空间连接 | 是 | 是 | 否 |
| 查看空间审计和用量 | 是 | 是 | 仅本人任务用量 |
| 更改平台套餐上限/平台插件 | 否 | 否 | 否 |

admin不能修改owner/admin成员关系或越级邀请admin。邀请默认member，owner可显式邀请admin。所有者权限不包含读取明文凭据。

会话和任务默认创建者私有；团队共享资料与报告须显式发布到空间项目。 项目 visibility 默认为 private，团队 owner/admin 可显式设为 workspace；资料继承所属项目的当前可见性，user_id 保留真实上传作者。共享改回私有后，项目资料仅向项目创建者开放，不开放其他作者的私有线程或记忆。首版不开放多人同时编辑/接管同一个Agent会话，不放宽原生thread owner规则。被移除成员的已共享材料保留在团队；未共享会话不自动转给管理员。团队定时任务仍绑定实际创建者；离队后暂停，由其他成员明确复制为新任务。

## 4. 身份与请求合同

使用不透明workspace UUID。用户可在请求头X-Deerflow-Workspace提供选择值，它只是定位符，不是授权。服务端认证后查询active workspace和active membership，生成不可由模型/客户端注入的WorkspaceContext(workspace_id, actor_user_id, membership_version, policy_version)。禁用多租户时保留原生单用户行为；启用时禁止auth-disabled和匿名任务访问。旧单用户兼容仅限未激活多租户的数据代际；一旦存在团队资源，不能通过关闭开关绕过隔离或退回旧binary。关闭自助注册只停止开户，不关闭已启用的空间授权。

权限为：原生身份/令牌scope ∩ 空间成员权限 ∩ 资源ACL。列举必须在SQL查询/计数/分页前限制workspace；直接ID访问按资源所属空间核验，越界返回404。Cookie/PAT不能凭本地选择的空间扩大权限。旧PAT迁移后仅限原个人空间；新PAT绑定一个空间并取权限交集，切换空间需相应凭据。

缺少空间的旧客户端仅可映射到该用户的个人空间，绝不使用浏览器“最后选择的团队”。团队资源缺少匹配空间选择拒绝；后台任务从持久记录恢复空间，不读取交互式会话的当前选择。未迁移资源或没有可靠owner的记录拒绝访问并进入清点清单。

所有前端请求、SSE重连、WebSocket、文件下载、线程引用、项目文件、MCP轮询、模型/技能选择、缓存与查询key纳入空间维度。浏览器无法附加头的路径，使用URL选择符并执行同一服务器校验，不将凭据放URL。切换空间取消旧请求和订阅，清除旧空间内存缓存，不在进行中的Run上改变归属。

IM及GitHub/webhook入口只有在连接已由用户明确绑定空间时才可创建任务；既有绑定迁至个人空间，不从消息正文猜测租户。无法识别空间的自动化入口在多租户模式关闭。集成清单须逐项标明可用/阻止，禁止未覆盖入口悄悄走全局路径。

## 5. 注册、邮件与团队生命周期

继续使用/api/v1/auth/register。多租户模式下返回统一202响应，建立待验证账号，不自动登录或创建可执行空间；已存在邮箱不返回是否存在。验证后幂等激活账号和个人空间，再由用户正常登录。管理员开通与自助注册调用同一幂等provisioning服务；管理员不能通过开通界面指定普通用户的明文密码。注册关闭时，管理员邀请仍可完成受控入驻。

验证、邀请与重置令牌均用密码学随机值；数据库只保存哈希、purpose、subject、expires_at、used_at。邮件outbox如需重试持有原链接，payload必须加密、发送后清除；日志不得记录链接、令牌、密码和原文邮件。令牌单次消费在数据库事务内串行化。验证默认30分钟，重置20分钟，邀请7天，均可由平台配置。重发撤销同purpose旧令牌。接收端GET不消费令牌（避免邮件预取）；用户确认后的POST消费，随后清除地址栏令牌。

邀请绑定workspace、标准化邮箱及角色；只允许已验证且邮箱匹配的登录账号接受。重复接受只返回既有同一成员关系，不重复创建。邮箱标准化复用原生规则，不额外合并Gmail点号等别名。找回密码统一202；重置成功递增原生token_version，并撤销PAT/相关恢复会话，不绕过原生密码校验。

已有账号不能因为数据库中有email就自动标记已验证。迁移保留其账户和数据，激活多租户前完成验证；平台维护登录与租户任务准入分别校验，避免无法管理待验证用户。OIDC只有来自已配置受信issuer的email_verified声明才可作为验证证明，否则走邮件验证，不以邮箱相同自动合并不同OAuth身份。

限流使用共享Redis原子计数，按可信客户端IP和哈希邮箱双维度执行；验证/注册/邀请/重置有独立额度，默认公开邮件发送5次/邮箱/小时、20次/IP/小时。服务不可用时公开开户与发送拒绝，不能退回进程内无限额度。反向代理来源只使用既有受信转发配置。邮件发送失败保留可重试状态，不将邮件送达标记为成功。

停用先原子禁止新准入并递增policy_version，再通过原生取消/执行器停止现有工作，状态经过suspending到suspended；未确认物理STOP显示处理中且保留资源账。恢复只开放后续显式工作，不自动重放旧任务/定时任务。

团队关闭要求owner重新认证；进入closing、停止工作、撤销邀请/凭据授权、清理物理资源后进入closed。默认保留期30天，由平台配置，之后幂等purge逐项处理DB/NAS/索引/外部连接；保留最少脱敏审计。备份和NAS回收站按各自保留策略到期，不宣称立即抹除。保留期内仅允许平台经审计恢复且重新确认成员与凭据，仍不恢复旧任务。账户关闭先处理其所有团队所有权（转让或关闭），再撤销会话/令牌、关闭个人空间并退出其他团队，不能留下无owner团队。

## 6. 数据与文件设计

新增表使用原生metadata数据库和Alembic；下列名称为实现目标，不表示已存在。

| 表/字段 | 最小合同 |
| --- | --- |
| workspaces | id, kind(personal/team), name, status, personal_user_id(个人唯一), policy_version, created_at, closed_at, purge_after；个人workspace与用户唯一映射。 |
| workspace_memberships | 联合主键workspace_id/user_id，role、status、version、created_at；锁workspace事务保证单owner。 |
| workspace_invitations | id、workspace_id、email_canonical、role、token_hash(唯一)、expires_at、used_at、revoked_at、inviter_user_id。 |
| auth_action_tokens | purpose、user_id、token_hash(唯一)、expires_at、used_at；UserRow增加email_verified_at/account_status。 |
| workspace_connections | workspace_id、owner_user_id(nullable共享)、provider、encrypted_secret_ref、status、version；返回API只含脱敏元数据。 |
| workspace_knowledge_bindings | workspace_id、provider、dataset_id、visibility、connection_id、status；供应商凭据与binding保持同一空间。 |
| workspace_quotas / workspace_usage | 并发、每日Run启动数、存储上限及token用量；用量唯一事件ID，重复上报不重复计数。 |
| workspace_audit_events | workspace、actor、action、resource_id、outcome、request_id、timestamp；只记录最少元数据。 |
| workspace_operation_outbox | 幂等operation_id、workspace、kind、payload_ciphertext/非秘密payload、state、lease、attempt；用于邮件、撤销、清理，不能成为第二套Agent任务。 |
| 原生资源workspace_id | threads_meta、projects、project_documents、runs、mcp_tasks、scheduled_tasks及其occurrence/相关事件增加明确归属与查询索引；所有引用检查父子空间一致。 |
| 执行器workspace_id | 独立执行数据库jobs及affinity加入可索引归属；原用户/线程身份仍保留，签名合同版本升级。 |

LangGraph checkpoint继续由原生系统管理：全局唯一thread_id、incarnation与服务器确认的workspace映射绑定。每次读/恢复先验证映射，不绕过原生迁移去手改第三方checkpoint表。不新增tenant checkpoint引擎。

新资源路径：workspaces/{workspace_id}/users/{user_id}/threads/{thread_id}/…；共享资料位于workspaces/{workspace_id}/projects/{project_id}/…。个人记忆只在对应个人空间使用，团队项目记忆放workspace/project命名空间。跨空间复用个人偏好首版默认关闭，避免连带带入私人事实。索引为每实例本地、可重建，key必须含workspace与可见范围，NAS不承载SQLite WAL。

沙箱只挂载当前空间和被授权任务需要的路径，不挂整个NAS或全部用户目录。浏览器cookies/session、工具缓存、下载临时文件和导出也按空间分区。共享应用+逻辑隔离适用于首版受控试点；外部客户不能提供任意主机插件、Docker镜像或宿主命令。运行时能接触哪些宿主目录、数据库和凭据必须实际验证后才开放自助注册。

不默认引入RLS：先完整实现repository授权与入口覆盖。若后续使用PostgreSQL RLS，另行处理连接池上下文、后台身份与bypass角色，不能把未验证的RLS当作安全承诺。

## 7. 长任务、撤权与配额

B/C签名加入workspace_id及协议版本，Run/MCP/task/affinity/NAS路径归属必须一致；纯worker凭据不能代替用户成员资格。提交、claim/adopt、每次新的工具外部写操作、结果发布、续跑和通知投递前重查有效权限。membership_version/policy_version变化触发重新授权，不能仅相信旧签名。

离队/停用持久记录撤权事件并禁止新工作，再取消有关Run、B任务、定时任务和浏览器会话。正在执行的远端副作用不能承诺回滚；记录已知结果/未知状态。未知物理工作仍占容量，不因租约到期释放或盲目重试；通知和产物不得投递给已撤权成员。取消完成的控制面清理可使用限定的系统操作能力，不能恢复用户业务权限。

空间并发配额在原生准入时原子预留，同一个run_id的C调度/B依赖/续跑有明确记账事件，禁止重复计费。节点CPU/内存预留继续由原执行账承担；空间配额不能替代物理资源账。B等待期间释放原生C动态资源的既有合同保持。每日任务额度按UTC桶记录、UI按时区显示。原生token usage按run/usage-event幂等汇总，用作预算提醒；本版不承诺精确人民币硬上限。存储额度在上传预留+最终落盘校验，失败/取消回收预留，未知状态保留待对账。

## 8. 业务主干

个人空间上传两份有明确日期的资料，提出研究问题，使用原生模型/工具输出带来源定位和不确定项的报告；用户确认后创建定时跟进。新增一份资料后由原生Scheduler触发一次更新报告，说明新增事实和变化。团队空间通过邀请加入的成员可以使用显式共享资料，另一空间不能列举、下载、检索或通过会话引用读取它。共享报告不包含作者私有记忆或凭据。

验收先使用固定小文档和确定性响应验证接线，再用DeepSeek跑一条真实研究+更新流程；不把“销售CSV已通过”当作多租户研究流程已通过。知识来源先用原生项目文件；知识提供方用已有一个检索适配验证授权，不同时接入多个新供应商。无需先搭新向量数据库。

## 9. 迁移与发布

现有上海基线0035/e0001与旧数据必须保留。实现时检查真实migration head，追加新版本，绝不改历史revision父节点。先扩展可空列/新表，显式backfill：每个已知user一个个人空间，原生资源和执行账按真实owner关联。共享node本身不属于租户，不能把整台机器绑定给最后一个用户。无owner/owner冲突资源隔离并输出脱敏清单，不自动归给平台管理员。

迁移前drain、停止写入、确认物理STOP，备份两数据库与必要NAS清单，并在隔离恢复环境验证备份可恢复。两库DDL不具备原子事务：迁移回执分别记录metadata、executor、文件复制清单与验证结果；全部成功才启用新代码准入。数据库回填和NAS拷贝不删源；校验字节摘要与归属后切换映射，保留恢复清单。回滚依赖成套备份/文件映射与匹配旧镜像，不能仅降级镜像或清空workspace字段。

新旧worker不得混跑；启用多租户须验证metadata/executor schema及签名协议版本一致。新发布流程增加独立受控迁移阶段，并更新支持的release manifest版本/验证器；旧同schema脚本继续拒绝未知schema。迁移试跑在隔离数据副本，不直接对现有上海验收库试错。

## 10. 验收与交付门禁

按顺序：单空间主干 → 两种开户入口/团队主干 → 关键隔离与撤权 → 一条真实研究/跟进 → 迁移恢复及完整交付。每次修复只补必要回归，不增加全矩阵、不中途跑本地Docker或本地pytest。

必须覆盖：同一账号跨空间猜ID、另一账号越权；列表/计数/检索/下载/SSE/WSS；邀请重放/错邮箱/最后owner并发；成员移除后queued/running/续跑/通知；注册/重置限流与单次令牌；备份恢复；旧个人数据归属；空间A超额不消耗B配额。先完成主干，再集中跑上述边界，开发函数仍使用小范围RED→GREEN。

运行证据只在上海Jenkins/ECS；源码、镜像、schema、案例结果绑定commit并保留失败记录。需要真实邮件域名/发信服务和可用测试邮箱时再接入，不在聊天索要key。邮件未验证不能开放外部注册。现有2台ECS可做串行试点验收，不代表多租户生产容量。

## 11. 决策与实施纪律

管理员开通与客户自助均是本次必交付，不拆成两个上线承诺。按总计划M0→M11推进，不同时改全部子系统。业务代码优先MCP/Skill/扩展，空间资源授权属于核心合同，必须用可选、显式、可测试接口接入；不能用monkeypatch、全局替换user_id或新增平行Agent来规避改动。

本需求已包含历史授权的实施与定向验证记录；这些记录不等于完整交付。用户确认先整理计划、随后按顺序推进；后续“完成上述计划”目标已继续实施和上海定向验证。完整交付及发布须满足 M0–M11 门禁。

实施库表细化（M3 已读时钟）：新增原生 schema 0038 的
`workspace_thread_read_versions(workspace_id VARCHAR(36), user_id VARCHAR(64),
version BIGINT NOT NULL DEFAULT 0)`，主键为 `(workspace_id,user_id)`。
保留原生 `thread_read_markers(user_id,thread_id)` 主键及单调最大序号规则；
标记的空间权限派生自不可跨空间移动的私有线程，不另造会话或 Run 权威。
空间时钟只随该空间实际标记变化递增，原生用户全局时钟不复制为团队计数。
读取位置只纳入与可信空间及私有父线程一致的 Run；标记写入与撤权共用
workspace→actor→thread 锁顺序。线程删除中的标记清理和活动流仍需后续贯通。
