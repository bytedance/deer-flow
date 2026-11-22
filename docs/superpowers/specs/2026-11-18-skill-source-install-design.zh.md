# Skill 来源安装与可配置生命周期权限设计

**日期**：2026-11-18  
**状态**：评审草案 v5（补齐安装器同源规则、provenance 与交付依赖）
**当前代码锚点**：`main @ 340822f2c153a1db0183d6fb00d0203ae8847f0c`；#8393 不构成前置运行时能力。  
**相关事项**：#8342、#8393  
**设计结论**：**PROCEED，带明确部署门槛**。先交付 `skills:manage` 及其完整 per-user 生命周期；来源安装只在具备 Vercel 项目 OIDC 凭据的部署开放。普通自托管部署继续使用文件上传，不显示不可用的来源入口。

---

## 1. 问题与目标

当前安装外部 skill 需要下载、打包并上传；现有 `/api/skills/install` 与 `/api/skills/install/upload` 又硬编码 `require_admin_user()`。如果只把写入路由改成可配置权限，而不迁移同一条生命周期上的读取、编辑、删除、导出和启停，被授权用户会得到一个“能装不能管”的 skill。

本设计接受两个目标：

1. 用一个可配置权限点 **`skills:manage`** 管理调用者自己的 custom skills：安装、查看、编辑、删除、历史、回滚、导出和启停。
2. 在支持的部署上，具有该权限的用户可在 Skills 页面输入 `owner/repo@skill`，预览并安装**通过 DeerFlow 兼容性校验的 skill**，无需本地下载和打包。skills.sh 中仅是合法目录、但 frontmatter 不符合 DeerFlow 规则的候选不属于可安装成功标准。

### 部署能力边界

skills.sh 官方 API 需要 Vercel 项目 OIDC token。`VERCEL_OIDC_TOKEN` 不是普通自托管部署可以自行编造的通用 API key。第一版因此明确为：

- 具有有效 Vercel 项目 OIDC 环境的部署：可以开放 From source；
- 普通自托管部署：保留文件上传和生命周期管理，**不显示 From source**；
- 缺少凭据不是“管理员再配置一个环境变量就能获得能力”的通用降级路径；
- 若未来需要自托管来源安装，必须另提一个可自托管 resolver 的设计，不能声称本版已覆盖。

## 2. 明确非目标

1. 不让未配置角色自动获得安装或管理能力。
2. 不新增 per-user 数据库字段或角色编辑 UI；复用现有授权 provider 和 route permissions。
3. 不新增 PAT scope；PAT 继续不能调用安装或管理路由。
4. 不把 skill 安装到 public/global 目录。
5. 不执行 `npx`、下载脚本、安装脚本或生命周期命令。
6. 第一版只接受 `owner/repo@skill`，不接受任意 URL、Git 地址、本地路径或私有仓库。
7. 不用第三方 audit 替代本地扫描。
8. skills.sh 文本快照不可用时回退 `.skill` 上传；不补抓二进制文件，不实现 GitHub resolver。
9. 不开放公共/集成 skill 的全局启停、全局诊断或其他用户 custom skills 的管理。
10. 不在聊天结果中自动安装；后续预填链接也必须进入同一确认对话框。
11. 不添加“要求已有 thread”的所有权迁移。现有路径已按有效 user id 隔离，本设计不修复一个不存在的跨用户读取漏洞。

## 3. 当前系统事实

- 两个安装路由都由 `require_admin_user()` 保护；custom skill 的内容、编辑、删除、历史、回滚、导出以及启停也主要使用 admin 判断。
- `_install_skill_archive()` 已复用 per-user storage、安全扫描、缓存刷新、跨实例 reset 和“取消也不丢安装”的 drain 包装；该包装不表示全局串行化。
- `resolve_thread_virtual_path()` 使用 `get_effective_user_id()` 解析到 `users/<uid>/threads/<tid>/user-data/...`。传入他人 thread id 不会跨用户寻址；缺失 thread 归档按现有路径语义失败。路由不返回文件内容，安装也写入调用者自己的 storage。
- legacy/unregistered thread 的现有 read/access 语义不能被本功能顺手改成 `require_existing=True`。
- `resolve_route_permissions()` 在授权关闭时返回 `_ALL_PERMISSIONS`；新增权限必须单独保持 admin-only 默认。
- 内置 RBAC 使用 `resource="route"`、`target=<permission>`；无 routes policy 为 unrestricted，`allow: "*"` 包含新 target。
- 自定义授权 provider 也会收到新 target。其默认 allow 行为可能在升级后开放管理能力，不只有内置 RBAC 需要升级审计。
- PAT 有独立 default-deny 路由边界；`is_admin_user()` 对 PAT 恒 false。权限层仅看到 `User.system_role` 时，不能把 PAT 拒绝误归因于权限计算。
- 前端 Skills 和 artifact 入口使用 `system_role == "admin"`；`hasPermission()` 对 unresolved permissions 的宽松回退服务于混合版本兼容，不能直接改成严格数组判断。
- skill 列表的 `filter_resources(principal, "skill", ...)` 可见性策略与 route 管理权限是两个独立维度。
- skills.sh 详情 API 返回 `id/source/slug/hash/files`；`files` 和 `hash` 可能为 null，文件内容是文本快照，API 凭据来自 Vercel OIDC。

官方参考：https://skills.sh/docs/api 、https://skills.sh/docs/cli 。

## 4. 单一生命周期权限：`skills:manage`

### 4.1 为什么不叫 `skills:install`

安装后必须能查看、启停、导出和删除。若继续使用 `skills:install` 同时表达这些动作，名称会误导配置者和审计者。本版只新增 **`skills:manage`**，其语义是：

> 管理调用者自己 per-user custom skill 空间中的 skill，包括安装来源和完整生命周期；不授予公共、集成或其他用户 skill 的管理权。

custom skill 默认安装即启用并进入该用户后续 agent prompt，因此自有 disable/delete 与安装必须在同一切片交付；这不是可选 UI 打磨。确认对话框提示安装后立即生效，安装成功页面必须能直接启停或删除。

不新增第二个安装权限，也不制造 install/manage 的组合矩阵。

授权开启时，自定义 provider 收到的准确请求形状为：

```python
AuthzRequest(resource="route", action="manage", target="skills:manage")
```

其中 `skills:manage` 是一个 route permission 字符串，不等于 `filter_resources(principal, "skill", ...)` 的 singular `skill` 资源。每个认证请求的有效权限解析会增加这一 `route/manage` 评估；未知 target 默认 allow 的 provider 会向所有角色开放它。

### 4.2 路由与消费者

| 表面 | `skills:manage` 后的行为 |
| --- | --- |
| `POST /api/skills/install` | 安装调用者有效 user id 下的 thread `.skill`；保持现有 legacy 路径语义，不加 `require_existing` |
| `POST /api/skills/install/upload` | 上传并安装到自己的空间 |
| `POST /api/skills/install/source[/inspect]` | 预览/安装到自己的空间；另受部署能力门槛 |
| custom skill content/history | 只能读取自己的 custom skill |
| custom skill update/delete/rollback | 只能修改自己的 custom skill |
| custom skill export/manifest | 只能导出自己的 custom skill |
| `PUT /api/skills/{name}` enable/disable | 仅当目标是自己的 custom skill 时可由 `skills:manage` 授权；public/integration/其他目标仍需 admin |
| Skills/artifact 前端安装、内容、开关、导出、删除入口 | 按有效权限与目标类别显示 |
| 全局 diagnostics、公共/集成 skill 管理 | 保持 admin-only |

现有 Create skill 入口和 agent 内 `skill_manage` 工具不属于本权限迁移；它们的行为不在本 spec 顺手改变。

### 4.3 默认与升级语义

- **授权关闭**：用显式集合 `_DISABLED_AUTHORIZATION_ADMIN_ONLY = frozenset({Permissions.SKILLS_MANAGE})` 声明 admin-only 权限；默认权限计算从 `_ALL_PERMISSIONS` 中对该集合按 admin 身份过滤。不得写成散落各处的内联 permission remove，测试必须枚举该集合并与文档矩阵一致。
- **授权开启**：所有角色（包括 admin）由 provider 评估；显式 deny 对 admin 同样有效。
- **内置 RBAC**：deny 优先；allow `*` 包含新权限；无 routes policy 为 unrestricted。
- **provider 故障**：遵循 `authorization.fail_closed`。安全边界部署必须保持 true。
- **PAT**：不加入 PAT scopes/routes。权限层可能根据 `system_role` 计算权限，但最终拒绝依赖 PAT middleware/default-deny；两层分别测试，不能互相冒充。
- **auth-disabled 单用户模式**：保持当前默认用户/admin 体验。

当前没有 internal caller 调用 skill 安装路由，因此授权关闭时 internal 失去 manage 是可接受的显式行为；测试必须固定它，而不是为了保持旧全量列表把安装权限授予 internal。

配置只展示 admin/user 的完整策略和授权增量，不提供会锁死自定义角色其他 route 权限的可复制片段：

```yaml
roles:
  admin:
    routes: {allow: "*"}
  user:
    routes: {allow: "*", deny: ["skills:manage"]}
```

若要给自定义角色授权，把 `skills:manage` **追加到该角色现有 routes.allow 列表**，或在现有 deny 列表中移除它；不得用只有 `skills:manage` 的 allow 列表覆盖原配置。

角色授予能力还受现有用户管理边界限制：内置 RBAC 的 declared roles 可通过既有 admin API 分配；自定义 provider 在 DeerFlow 内仍只有 admin/user 可分配，角色由外部系统管理。`system_role` 最长 16 字符，新角色名必须满足该限制。内置 RBAC 自定义角色若追求最小权限，必须显式配置所有相关资源类型；未列出的 tools/models/skills/sandbox 等仍是 unrestricted，本 spec 不提供不完整的自定义角色复制示例。

`config.example.yaml` 的 user 示例显式 deny `skills:manage`。发布说明必须说明：

- 所有 provider 都会收到新的 route target；
- allow `*`、no-policy/unrestricted 或自定义 provider 的默认 allow 可能在升级后授予它；
- 希望保持 admin-only 的部署必须显式 deny；
- `routes` 管理权限与 `skills` 资源可见性策略独立，安装成功不会绕过列表过滤。

首次允许新 target 时增加一次性诊断日志，按 `(provider config signature, role, target)` 去重，提示升级后审计策略；不得每次请求刷日志。内置 RBAC 的 `rbac:unrestricted` 必须覆盖，自定义 provider 的普通 allow 也必须有审计提示。

### 4.4 可见性不是管理权

`roles.<role>.skills` 仍控制列表/详情可见性，`roles.<role>.routes` 控制生命周期动作。配置文档必须展示二者区别。安装后不修改可见性策略；若目标 skill 被过滤，UI 显示“已安装，但当前可见性策略可能隐藏它”，不能假装安装失败或自动放宽策略。

## 5. 来源解析、限额与错误契约

### 5.1 输入与 id 映射

```json
{"source":"vercel-labs/skills@find-skills"}
```

映射必须固定为：

```text
source  = vercel-labs/skills
slug    = find-skills
id      = vercel-labs/skills/find-skills
GET     https://skills.sh/api/v1/skills/vercel-labs/skills/find-skills
```

只接受一个 `owner/repo@skill`，不支持 well-known source。输入限制与归一化：

- source 总长最多 256 字符，只使用 ASCII；拒绝 scheme、query、fragment、反斜杠、额外 `@`、`..`、控制字符和空白变形。
- owner 为 1–39 个字母/数字/连字符，不能以连字符开头或结尾；repo 为 1–100 个字母/数字/`.`/`_`/`-`；skill 为 1–64 个字母/数字/连字符。
- 三段在请求前统一 lowercase；skill 归一化后必须满足 DeerFlow 的 `^[a-z0-9-]+$`。响应的 owner/repo 使用 casefold 等价比较，slug 与归一化请求精确比较，避免 GitHub 大小写造成假 mismatch。
- 路径段分别编码；固定上游、不重定向、不允许请求方覆盖 base URL。

HTTP client 必须显式使用 `httpx.AsyncClient(trust_env=False)`，避免 `HTTPS_PROXY` 等环境变量把 OIDC token 转发给代理。响应使用 `client.stream()` 分块读取并累计字节，达到 12 MiB 立即中止；禁止先 `response.json()` 再检查大小，因为那时完整 body 已进入内存。

凭据**每次请求重新读取** `VERCEL_OIDC_TOKEN`，不得在启动时读取后永久缓存。`/api/features` 每次重新评估来源能力。官方 token 约 12 小时轮换；轮换后旧 token 应得到 `skill_source_auth_failed`，由 Vercel 运行环境刷新凭据，运维文档不得建议长期缓存。普通自托管部署没有此能力时：

- `/api/features` 返回 `source_install_available=false`；
- 前端隐藏 From source；
- 直接 API 返回 503 `skill_source_not_configured`，文案为 “This deployment does not have skills.sh credentials.”。

固定验收常量（第一版不开放配置）：

| 项目 | 上限 |
| --- | --- |
| connect / total timeout | 3 秒 / 15 秒 |
| 每进程每用户上游读取 | 20 次/分钟，超限 429 |
| 每进程来源请求并发 | 4，超出立即 429，不排队 |
| 文件数 | 256 |
| 单文件 UTF-8 内容 | 1 MiB |
| 全部文件 UTF-8 内容 | 8 MiB |
| 上游 JSON 响应 | 12 MiB |
| 生成的 `.skill` 归档 | 10 MiB |

这些来源专属上限刻意低于上传的 100 MiB，避免 files JSON、文本、ZIP 与后续解包副本在同一请求中造成数百 MiB 内存放大。inspect 与 install 都计入配额；本地 429 和上游 429 均返回 `skill_source_rate_limited`，合法 `Retry-After` 必须透传。该实例级限额不冒充全部署精确配额，不新增 Redis/持久缓存；安装始终重取并校验摘要。

### 5.3 错误码

| code | HTTP | 含义/UI 分支 |
| --- | --- | --- |
| `skill_source_invalid` | 400 | source 格式错误，保留输入供修改 |
| `skill_source_not_configured` | 503 | 当前部署无 skills.sh 凭据；自托管保持文件上传 |
| `skill_source_auth_failed` | 503 | 已配置 OIDC 但上游 401/403；提示部署维护者检查凭据来源/有效期 |
| `skill_source_unavailable` | 503 | 上游 5xx、网络或 timeout，可稍后重试 |
| `skill_source_rate_limited` | 429 | 本地或上游限额；显示 Retry-After |
| `skill_source_not_found` | 404 | 来源不存在 |
| `skill_source_snapshot_unusable` | 422 | files 为 null、路径/大小/frontmatter 不合法；引导上传 |
| `skill_source_changed` | 409 | 安装快照与预览不同；丢弃 preview，重新 inspect |

上游 401/403 不得映射成普通 unavailable，也不得把响应正文或 token 透传到日志/UI。

所有来源获取与预检错误使用结构化 envelope，前端不得匹配 message；进入现有安装器后的扫描/写入错误保留现有安装错误结构，同时扩展 code/findings 解析：

```json
{"detail":{"code":"skill_source_changed","message":"The source changed; inspect it again."}}
```

`readErrorDetail` 同时兼容现有字符串 detail 和新 `{code,message,findings?}` detail；`SkillRequestError` 增加可空 `code`、`retryAfter` 与 findings。旧字符串错误归一为 `code=null`。429 从响应头读取 Retry-After，UI 按 code 分支。

## 6. 快照、预览与安装

### 6.1 快照验证

响应先满足来源身份、文件结构与 §5.2 数值上限，再进入**安装同源的确定性校验**。实现必须与 `safe_extract_skill_archive`、`resolve_skill_dir_from_archive`、`validate_skill_frontmatter_text` 提取或复用单一规则入口，source 路由不得维护近似副本。预检至少覆盖：

- `id/source/slug` 与归一化请求一致，files 非空且根目录存在 `SKILL.md`；
- 除根目录外不得再出现嵌套 `SKILL.md`，由 resolve_skill_dir_from_archive 同源规则拒绝；
- frontmatter 的 name、description、未知 key 和大小限制，直接复用 validate_skill_frontmatter_text；
- Windows 保留设备名、尾随点/空格、成员名冒号（Windows ADS）及各平台路径可移植性；
- 成员路径总字节、目录深度、单段长度、绝对路径、`..`、NUL 和重复归一化路径；
- `a` 与 `a/b` 这类文件—目录冲突；
- 可执行二进制成员拒绝及其他 archive preflight 确定性规则；
- 条目数与解压总量遵循 safe_extract_skill_archive：本设计 256 文件低于其 4096 上限，8 MiB 内容低于其 512 MiB 上限，且两层都必须测试；
- 启用时的本地静态扫描策略，复用 enforce_static_scan，相关计算/IO off-loop。

任一确定性 gate 失败时返回 422 `skill_source_snapshot_unusable`，detail.message 给出具体原因；静态扫描 findings 随结构化错误返回，不进入 Install。不得静默改写 name、删除未知 key、清洗 description、重命名冲突路径或降级二进制检查。

可能慢、失败或产生模型调用的内容扫描留在安装期；`skill_scan_enabled` 部署开关和静态 CRITICAL 策略也可能在安装前变化。预览只承诺“当前确定性规则通过”，不承诺扫描或安装一定成功。安装仍重新执行全部确定性和内容扫描。

### 6.2 可复算摘要

路径归一化为 POSIX，内容编码为 UTF-8；按 path bytes 升序。所有整数为无符号 64 位大端。伪代码：

```text
h = SHA256()
h.update(b"deerflow-skill-snapshot-v1\0")
h.update(u64be(file_count))
for file in sorted(files, key=lambda f: f.path_utf8):
    h.update(u64be(len(file.path_utf8)))
    h.update(file.path_utf8)
    h.update(u64be(len(file.content_utf8)))
    h.update(file.content_utf8)
snapshot_digest = lowercase_hex(h.digest())
```

版本标签、文件数和长度前缀都是格式的一部分；不允许直接拼接 `(path, content)`。上游 hash 只作元数据。

### 6.3 预览

```http
POST /api/skills/install/source/inspect
```

权限：`skills:manage`。返回 source/source_url、skill_name、description、snapshot_digest、upstream_hash、file_count、total_bytes；不返回文件全文，不写持久状态。inspect 必须通过 §6.1 的全部安装同源确定性校验；例如 `name: Next.js Development`、Windows 设备名或 `a`/`a/b` 冲突应在预览时 422，而不是等 Install 才失败。

预览只证明来源通过确定性兼容与静态策略预检，不承诺内容扫描、重复名检查或最终安装一定成功。UI 标注最终内容扫描在 Install 时执行；`SkillSecurityScanError.findings` 必须复用现有上传对话框的 findings 展示，不得只显示笼统 400。

### 6.4 安装

```http
POST /api/skills/install/source

{"source":"owner/repo@skill", "expected_snapshot_digest":"<64 hex>"}
```

1. 重新获取、验证并计算摘要；不同则 409 `skill_source_changed`，不得调用安装器。
2. 在临时目录构造单根目录 ZIP；临时文件名必须以 **`.skill`** 结尾，因为现有安装器硬性检查后缀。
3. 调用 `_install_skill_archive()`；沿用其扫描、写入、缓存和 reset 语义。
4. `finally` 清理临时文件。

快照文件写入、ZIP 构建、文件读取和摘要计算等同步 IO/重计算必须经 `asyncio.to_thread` 或现有等量 offload；不得在 async handler 内直接执行。安装器内部再次解包沿用其现有 offload，本设计不重复修改。

不新增 source 表、后台任务或安装历史字段。

**Provenance 边界**：第一版不提供可查询、持久化的来源记录，不在安装目录写元数据文件。`SkillInstallResponse` 仅新增 `enabled`，用于反映重安装后保留的调用方状态，不携带 provenance；source 与 snapshot_digest 可以写入普通进程日志，但日志滚动后不可查询，My skills 不显示来源，重新预览/升级需要重新输入 source。不得把该日志描述成审计设施；若未来需要持久 provenance，另开覆盖摘要、导出和编辑语义的切片。

## 7. 前端与混合版本

### 7.1 能力标记

`/api/features` 新增：

```json
{
  "skill_management": {
    "lifecycle_permissions": true,
    "can_manage": true,
    "source_install_available": false
  }
}
```

- `lifecycle_permissions=true` 是新后端版本标记；
- `can_manage` 由服务端按当前请求有效权限计算；
- `source_install_available` 只表示 Vercel OIDC 来源能力，不表示管理权限。

前端新增本地谓词，**不修改全局 `hasPermission()`**：

```text
canManageSkills =
  false                                      if isStaticWebsiteOnly()
  skill_management.can_manage                if /api/features 返回新字段
  user.system_role == "admin"                otherwise（旧后端回退）
```

- `NEXT_PUBLIC_STATIC_WEBSITE_ONLY` 是独立硬门控；即使旧后端回退为 admin，也绝不显示安装/管理动作。
- 新字段存在时严格使用 can_manage；From source 还要求 source_install_available。
- 旧后端回退仅属于这个新谓词，不改变 chat/sidebar/usage/search 使用的 hasPermission unresolved 放行契约。

### 7.2 菜单和对话框

Skills header 使用 **Install skill ▾**：From source（能力可用时）与 From .skill file；Create skill 独立。community tab 的空态上传入口复用同一个菜单组件和 `canManageSkills`，不得保留第二套 isAdmin 判断；静态站点两处都不渲染。

对话框状态：

```text
closed → input → inspecting → preview → installing → success
                    │           │           │
                    └────────── error ──────┘
```

- preview 展示不可信文本为纯文本；不使用 `dangerouslySetInnerHTML`。
- changed 清除旧 preview；rate_limited 展示 Retry-After；auth_failed 指向部署维护者；not_configured 不指导自托管用户伪造凭据。
- installing 禁止重复提交；关闭对话框不伪造服务端取消。fetch 阶段可能直接取消；进入 `_install_skill_archive` 后 `await_drained` 会让安装完成再传播取消，因此关闭后必须重新拉取列表，且结果可能是“已安装”。
- success 刷新列表；若可见性策略过滤目标，显示已安装但可能不可见。

custom skill 的查看、编辑、删除、导出和启停入口同步迁移，不能出现“安装后没有管理按钮”。公共/集成 skill 开关和全局 diagnostics 仍按 admin。

错误 UI 通过 `SkillRequestError.code/retryAfter` 分支，不匹配 message。`en-US.ts`、`zh-CN.ts` 和 `types.ts` 同步增加菜单、对话框、生命周期动作和全部错误码文案；现有 `installAdminRequired` 不再承担“非 admin 但角色被 deny”的语义，新增准确的 `skillManageRequired` 文案。

新增 inspect/install-source 客户端必须复用 `@/core/api/fetcher` 的 fetch 包装，使 POST 自动携带 CSRF token；禁止改用 globalThis.fetch。静态导出没有这些新端点的 mock，也是静态硬门控必须保留的原因。

## 8. 安全与运维边界

- 固定上游、无重定向、无请求方 base URL；不开放 SSRF 通道。
- Gateway 不执行 npx/Node/下载代码。
- 本地下载生成的 `.skill` 必须经过现有全部扫描和安全解包。
- 管理权限仅作用于自己的 custom 空间，不提升为 public/global。
- 不因不存在的跨用户路径漏洞新增 legacy 回归；跨用户 thread id 仍按有效 user id 路径隔离。
- token 不进入前端、日志、响应或 skill 文件。
- 网络、文件、响应、并发、用户窗口与临时目录有界；429 透传合法 Retry-After。
- 所有同步文件/ZIP/摘要工作 off-loop，并有 blocking-IO 回归。

## 9. 验收与测试

### 9.1 权限矩阵

| 场景 | 期望 |
| --- | --- |
| 授权关闭，admin session | 自有 custom 全生命周期可用 |
| 授权关闭，非 admin session | 管理路由 403，前端隐藏 |
| 授权开启，角色显式 allow | 自有 custom 全生命周期可用 |
| 授权开启，角色**有 routes policy**且 deny/未包含 manage | 403，前端隐藏 |
| 授权开启，角色未配置 routes policy | 按 unrestricted 获得权限，并产生升级审计诊断 |
| 授权开启，admin 显式 deny | 403，前端隐藏 |
| provider 故障且 fail_closed=true | 403，前端隐藏 |
| provider 故障且 fail_closed=false | 按既有 fail-open 返回全部权限，非 admin/internal 也会获得 manage；必须有升级告警，安全部署不得使用该组合 |
| 授权关闭，internal caller | 非 admin，不获得 manage；更新 blocking-IO 权限集合期望 |
| auth-disabled 单用户合成 admin | 可用，保持本地零配置路径 |
| admin PAT | 权限计算与 PAT 最终拒绝分别验证；路由始终 default-deny |
| 有管理权限，尝试公共/集成 skill 全局启停 | 仍要求 admin |
| 有管理权限，尝试其他用户 custom skill | 无法访问他人 per-user storage |
| 无权限 inspect | 403，零上游请求 |

### 9.2 测试基座

- 改造 `backend/tests/_router_auth_helpers.py`：stub 必须 role-aware，不能给所有角色全量权限；补齐当前 Permissions（包括 PROJECTS_*）和 `skills:manage`。
- `test_skills_router_authz.py` 的非 admin 403 必须证明没有被全量 stub 静默放行。
- 权限集合断言统一从 `_ALL_PERMISSIONS` 加显式角色/default 过滤派生，删除重复镜像列表。明确更新 `test_auth_me_permissions.py` 的 admin、deny、auth-disabled admin、middleware-less non-admin 断言，`blocking_io/test_auth_middleware_route_permissions.py` 的 internal disabled 断言，以及 `test_authorization_route_permissions.py` 的 fail-open 全量断言。
- `_DISABLED_AUTHORIZATION_ADMIN_ONLY` 有独立集合测试；internal 和 middleware-less non-admin 都由同一过滤规则覆盖。
- auth/me、fail-open/fail-closed、自定义 provider 新 target 和一次性诊断日志均有测试。
- custom 内容/编辑/删除/历史/回滚/导出/自有启停均覆盖 admin、授权非 admin、拒绝角色。

### 9.3 来源与生命周期回归

- owner/repo@skill → 三段 id 映射、大小写归一、非法字符、OIDC header 和每次请求重新读取 token。
- 自定义 provider 收到精确的 `resource=route/action=manage/target=skills:manage`；它与 skill 可见性资源分开测试。
- client 强制 trust_env=false；流式读取在第 12 MiB+1 字节中止，response.json 后检查不算有效实现。
- 完整错误 envelope/code/findings、Retry-After、数值上限、本地限额、token 轮换与无 token 能力门控。
- 摘要测试包含 `("a","bc")` 与 `("ab","c")` 不碰撞、文件顺序不影响、文件数/长度变化会改变摘要。
- frontmatter、Windows 设备名/尾点尾空格、路径字节/深度/段长、`a` 与 `a/b` 冲突、可执行二进制和静态扫描都在 inspect 拒绝，Install 不可达；每项证明预览与安装使用同一确定性入口。
- 嵌套 `SKILL.md` 和成员名冒号由同源规则在 inspect 拒绝。来源测试覆盖 256/8 MiB 上限先于安装器上限生效；安装器既有套件分别覆盖 4096 条目/512 MiB 解压上限，并断言两组常量保持本设计的更小约束。
- 合法 preview 后内容扫描失败仍返回安装错误并渲染 findings，证明 preview 没有虚假承诺；Gateway 不改写 frontmatter。
- 预览后内容变化返回 changed，零持久写入。
- 临时文件以 `.skill` 结尾；成功、扫描失败、摘要冲突、取消均清理；进入 drained install 后关闭 UI 的最终列表能反映“已安装”结果。
- 扫描真实发生，安装进入调用者存储；内容/编辑/删除/导出/自有启停立即可用。
- 写文件、ZIP、摘要等没有 event-loop blocking IO；token 不出现在日志或响应。

### 9.4 前端与端到端

- 新后端 capability + can_manage 的各角色 UI。
- 旧后端无 capability 时 admin 的旧入口不消失，非 admin 不获得入口。
- 静态站点中 header、community 空态、artifact 和 custom 管理入口全部隐藏，即使 admin/permissions 缺失。
- header 与 community 空态复用同一权限与错误处理；SkillRequestError 按 code/retryAfter 分支，无 message 匹配。
- en-US、zh-CN 和类型键完整，无遗留 admin-only 错误文案。
- 自有 custom 安装后可查看、启停、导出、删除；公共/集成目标仍受 admin 控制。
- source 不可用部署隐藏 From source，只保留文件上传。
- input→preview→install→success 和完整错误分支有 DOM/浏览器证据，**此处 Gateway 由 Playwright page.route mock，不声称真实 skills.sh/真实 Gateway 端到端**。
- 可见性过滤与 route 管理权限的组合不误导用户。

验证命令：

```text
cd backend && make lint && make test
cd backend && make test-blocking-io
cd frontend && pnpm lint && pnpm typecheck && make test
cd frontend && make test-e2e
cd frontend && BETTER_AUTH_SECRET=local-dev-secret pnpm build
```

验证分两层：后端集成测试通过真实 Gateway/handler/storage 与 httpx mock transport 证明 inspect→install；Playwright 只 mock Gateway API，证明 UI 状态机、CSRF 请求和权限可见性。`mockLangGraphAPI` 增加 system_role/permissions 参数以覆盖被授权非 admin；所有旧后端权限回退使用 `== null`，同时覆盖 undefined 与 null。真实来源安装另做一次手工 Gateway 冒烟，不把 Playwright mock 当成上游或持久化证据。

## 10. 交付切片

### Slice A：自有 custom 全生命周期权限

- 注册 `skills:manage`、授权关闭默认、provider 升级诊断和 `/api/features` capability/can_manage。
- 迁移安装及自有 custom 内容、编辑、删除、历史、回滚、导出、启停。
- 公共/集成目标和 diagnostics 保持 admin。
- 改 role-aware 测试基座、Skills/artifact UI 与配置文档。
- **不做 thread owner 修正，不改 require_existing。**

### Slice B：Vercel OIDC 来源后端

- 明确 source_install_available 的部署判定。
- 实现 parser、client、限额、错误码、快照、摘要、inspect/install、`.skill` 临时文件和 offload。
- 普通自托管部署只报告能力不可用，不交付伪通用凭据配置。

### Slice C：Skills 页 UI

- Install skill 菜单与来源对话框。
- 自有 custom 全生命周期按钮使用同一 capability/permission。
- 完成混合版本、浏览器和文档验证。

交付依赖与回滚固定为：

| 切片 | 上线依赖 | 回滚动作 |
| --- | --- | --- |
| A | 无 | 恢复两个旧安装路由的 admin guard 与旧前端行为；若保留 B/C 路由，也必须同时给它们恢复等效 admin guard |
| B | A | 移除 source 路由与能力标记，保留 A 的自有生命周期权限 |
| C | A+B | 移除菜单/对话框，保留 A+B API；不得先于 B 上线 |

因此不是三个可任意独立 cherry-pick 的切片：顺序为 **A→B→C**；单独回滚 C 安全，回滚 B 保留 A 安全，回滚 A 时必须处理仍存在的 B/C 调用面。

## 11. 已定案决策

1. 使用单一 `skills:manage`，覆盖自己的 custom 全生命周期，不接受“能装不能管”。
2. 沿用 RBAC wildcard/no-policy 语义，并对所有 provider 做升级提示和一次性诊断。
3. 来源安装第一版明确依赖 Vercel 项目 OIDC；普通自托管不显示该能力。自托管 resolver 是另一个设计。
4. 删除 thread 所有权“安全修正”；现有路径已按 user id 隔离，legacy 语义不变。
5. 接受文件导入进入 Install skill 菜单后的两次点击。
6. 通过 `/api/features` capability 解决混合版本，不修改 `hasPermission()` 的既有 unresolved 语义。
7. 预览与安装共享 frontmatter 及全部确定性校验；静态扫描可预检，内容扫描留安装并展示 findings，不静默改写 skills.sh 目录。
8. 静态站点开关独立于权限；新谓词不改变 hasPermission，community 空态复用同一入口。
9. Playwright 只提供 mock-Gateway UI 证据，后端 mock transport 与手工 Gateway 冒烟提供真实安装链证据。

除上述内容外，不引入第二套权限系统、通用 resolver 框架、持久化 source 子系统或全局限额服务。
