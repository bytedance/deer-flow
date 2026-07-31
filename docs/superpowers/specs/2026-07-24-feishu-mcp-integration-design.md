# 飞书 MCP 接入设计文档（A 子项目：lark-cli 方式）

**日期：** 2026-07-24
**状态：** 已确认，待实现
**来源文档：** `爆品打造专家agent/爆品打造专家Agent_设计文档_v1.md`（第 3.4 节 mcp-ops、第 6 节飞书触达）
**父项目拆分：** 爆品打造专家 Agent v1 拆为 5 个子项目（A–E），本 spec 只覆盖 A。其余 B/C/D/E 各自单独 spec。

---

## 1. 目标

让 deer-flow agent 能通过飞书官方 `lark-cli` 调用飞书能力（发消息/@、多维表 CRUD 等），作为后续子项目的基础：
- **C（多维表 schema 搭建）** 通过 lark-cli 的 `lark-base` skill 写表/字段/记录/视图
- **D（规则+归因 Skill）** 推送告警时通过 `lark-im` skill 发消息
- **E（每日 9:00 定时任务）** 触发推送 + 写表都走 lark-cli

**零自写 Python 代码**：不自己写飞书 MCP Server（不像 `governance/kb_mcp/` 那样自建）。直接复用飞书官方 lark-cli + 官方 26 个 skill 包。

**非目标**：
- 不做多维表具体 schema 设计（3 张表字段 + 视图）—— C 子项目
- 不做推送内容格式（🔴 紧急/🟡 警告/🔵 信息卡片）—— D/E 子项目
- 不做定时任务编排 —— E 子项目
- 不在飞书对话里触发 agent —— 对话在 deer-flow 前端进行（用户已明确）

---

## 2. 架构

```
deer-flow agent（对话在 deer-flow 前端，不在飞书）
  │
  ├─ bash 工具（LocalSandbox，宿主机 bash）
  │     └─ 调 lark-cli 命令
  │          · lark-cli im +messages-send --chat-id oc_xxx --text "..."
  │          · lark-cli base +records-create --app-token xxx --table-id xxx --records '[...]'
  │          · lark-cli base +fields-create / +views-create / ...
  │          ↓
  │        lark-cli（npm @larksuite/cli，装在宿主机）
  │          · 凭据用 OS-native keychain 存（macOS Keychain / Linux secret-service）
  │          · 用 user_access_token（--as user）或 tenant_access_token（--as bot）调飞书 OpenAPI
  │          ↓
  │        飞书开放平台 API
  │
  └─ read_file 工具
        └─ 读 skills/custom/lark/*/SKILL.md + references/*.md
           （lark-cli 官方 26 个 skill 包，格式兼容 deer-flow 技能系统）
```

**关键设计决策：lark-cli 是 CLI 工具不是 MCP Server**。飞书官方推荐用 "CLI SKILL" 方式集成到 AI agent（TRAE/Cursor/Codex/Claude Code 等），deer-flow 复用同一套机制：lark-cli 的 skill 包格式与 deer-flow 技能系统兼容（见第 5 节兼容性分析），直接把官方 skill 放进 `skills/custom/lark/` 即可，agent 通过 bash 调命令 + read_file 读 skill 文档。

---

## 3. 前置任务（D1 阻塞，凭据尚未申请）

这是 A 能跑通的硬前置，必须先解决：

1. **飞书应用创建**：在飞书开放平台（https://open.feishu.cn）创建自建应用 → 拿 `app_id` + `app_secret`
2. **scope 授权**：应用至少授以下 scope（`lark-cli auth login --recommend` 会自动申请常用 scope，但需在开发者后台预先开通）：
   - `im:message`（发消息）
   - `im:message:send_as_bot`（以机器人身份发消息）
   - `im:resource`（消息资源下载）
   - `bitable:app`（多维表读写）
   - `im:message:p2p:readonly_as_user`（以用户身份读私聊消息，按需）
3. **部署环境检查**：Linux 服务器确认有 `secret-service`（D-Bus）给 OS keychain；若无，测试 lark-cli 是否 fallback 到文件存凭据（必要时见第 8 节风险应对）

**凭据到位后**，lark-cli 文档承诺 3 步、3 分钟可跑通第一个 API 调用。

---

## 4. 安装 + 配置 + 授权步骤（凭据到位后执行）

```bash
# 1. 装 lark-cli（一次性，宿主机）
npx @larksuite/cli@latest install

# 2. 配置应用凭据（交互式，浏览器完成）
#    输出授权 URL，用户在浏览器确认
lark-cli config init --new

# 3. OAuth 登录授权（--recommend 自动选常用 scope）
#    同样输出授权 URL，浏览器确认
lark-cli auth login --recommend

# 4. 验证登录 + scope 齐全
lark-cli auth status
lark-cli auth check im:message
lark-cli auth check bitable:app
```

完成后 lark-cli 凭据持久化在 OS keychain，deer-flow agent 后续 bash 调用无需再登录。

---

## 5. 技能接入

### 5.1 兼容性分析（已验证）

lark-cli 官方 skill 包格式与 deer-flow 技能系统兼容：

| 项 | lark-cli skill | deer-flow 技能 | 兼容 |
|---|---|---|---|
| 文件名 | `SKILL.md` | `SKILL.md` | ✅ |
| frontmatter 必填字段 | `name` + `description` | `name` + `description` | ✅ |
| frontmatter 其他字段 | `version`、`metadata.requires.bins` | `license`、`allowed-tools`、`required-secrets`、`secrets-autonomous` | ✅（deer-flow parser 只提取自己认识的字段，其余忽略，不会解析失败） |
| 正文 | Markdown + 命令清单 + 相对路径引用 `../lark-shared/SKILL.md`、`references/*.md` | Markdown | ✅（agent 用 read_file 读引用文件） |
| 加载位置 | — | `skills/custom/` 递归扫描 | ✅ |

**验证依据**：`backend/packages/harness/deerflow/skills/parser.py::parse_skill_file` 只提取 `name`/`description`/`license`/`allowed-tools`/`required-secrets`/`secrets-autonomous`，其余 YAML 字段通过 `metadata.get(...)` 忽略；`name` 和 `description` 都是非空字符串即通过。

### 5.2 skill 包放置

把 `github.com/larksuite/cli` 仓库的 `skills/` 目录放到 `skills/custom/lark/` 下。**建议用 git submodule**（锁到具体 commit），便于跟上游同步评估：

```bash
# 在 deer-flow 仓库根目录：把 lark-cli 仓库作为 submodule 挂到 skills/custom/lark
# （submodule 路径直接是最终技能目录，避免 symlink 相对路径歧义）
git submodule add https://github.com/larksuite/cli.git skills/custom/lark
git -C skills/custom/lark checkout <pinned-commit>
```

submodule 挂载后，deer-flow 递归扫描 `skills/custom/lark/lark-im/SKILL.md` 等即发现全部 26 个 skill。**只启用 3 个**（见 5.3），未启用的不会被注入 agent 提示词但会在技能列表里显示 disabled。

> 注：若不希望把整个 lark-cli 仓库（含 Go 源码）作为 submodule 进来，备选方案是只复制 `skills/` 子目录到 `skills/custom/lark/`（牺牲上游同步便利性）。最终选哪种在 plan 阶段定。

放置后目录结构：
```
skills/custom/lark/
├── lark-shared/      # 认证基础（所有其他 lark skill 依赖）
│   └── SKILL.md
├── lark-im/          # 消息推送 + @ + 卡片
│   ├── SKILL.md
│   └── references/
├── lark-base/        # 多维表 CRUD（表/字段/记录/视图/仪表盘）
│   ├── SKILL.md
│   └── references/
├── lark-calendar/   # 默认不启用
├── lark-doc/        # 默认不启用
└── ...（共 26 个 skill）
```

### 5.3 启用配置

在 `extensions_config.json` 的 `skills` 段加（只启用 A 阶段需要的 3 个，其余 23 个默认不启用）：

```json
{
  "skills": {
    "lark-shared": { "enabled": true },
    "lark-im": { "enabled": true },
    "lark-base": { "enabled": true }
  }
}
```

deer-flow 重启（或 `/api/mcp/config` 触发 reload）后，`GET /api/skills` 应列出这 3 个 skill 且 `enabled=true`。

---

## 6. 验证标准（凭据到位后逐项检查）

1. **lark-cli 自检**：
   - `lark-cli auth status` 显示已登录
   - `lark-cli auth check im:message` 退出码 0
   - `lark-cli auth check bitable:app` 退出码 0

2. **技能加载**：
   - `GET /api/skills` 返回列表包含 `lark-shared`、`lark-im`、`lark-base`，且 `enabled=true`
   - deer-flow 前端技能列表里可见

3. **端到端推送验证**：deer-flow 前端对话里问 agent：
   > "用 lark-cli 给我发条测试消息到 oc_xxx 群，内容 'hello from deerflow'"
   - agent 应：识别意图 → 调 `lark-im` skill 文档 → bash 跑 `lark-cli im +messages-send --chat-id oc_xxx --text "hello from deerflow"` → 飞书群里收到消息

4. **端到端多维表验证**：deer-flow 前端对话里问 agent：
   > "用 lark-cli 在多维表 app_token=xxx table_id=yyy 里创建一条记录 {字段A: 值1, 字段B: 值2}"
   - agent 应：识别意图 → 调 `lark-base` skill 文档 → bash 跑 `lark-cli base +records-create ...` → 多维表里出现新记录

5. **降级验证**：lark-cli 凭据失效时（模拟 `lark-cli auth logout`），agent bash 调用应得到非零退出码 + stderr JSON `{"ok": false, "error": ...}`，agent 能识别错误并提示用户重新登录，不崩溃。

---

## 7. 边界与非目标

| 不做 | 由谁做 |
|---|---|
| 多维表 schema 设计（异常告警表/波动留痕表/影子建议表的字段 + 视图） | C 子项目 |
| 推送内容格式（🔴 紧急卡片 @负责人 / 🟡 警告卡片 / 🔵 信息日报） | D/E 子项目 |
| 每日 9:00 定时扫描编排 | E 子项目（用 deer-flow 现成 `ScheduledTaskService`，`scheduler.enabled` 改 true） |
| 飞书对话触发 agent | 不做（对话在 deer-flow 前端，用户已明确） |
| mcp-lingxing 数据工具 | B 子项目（独立自建 MCP Server，参考 `governance/kb_mcp/` 模式） |

---

## 8. 风险与应对

| 风险 | 概率 | 应对 |
|---|---|---|
| lark-cli OS keychain 在 Linux 服务器不可用（无 secret-service/D-Bus） | 中 | 先测 `lark-cli auth login` 是否 fallback 到文件存凭据；若不 fallback，装 `dbus-x11` + `gnome-keyring`，或封装一层把凭据从 env 注入 lark-cli 配置目录 |
| lark-cli SKILL.md 用相对路径 `../lark-shared/SKILL.md`，agent 用 read_file 解析不了 | 中 | 测试 agent 能否从当前 skill 虚拟路径推断；若不行，在 SKILL.md 里改绝对虚拟路径 `/mnt/skills/custom/lark/lark-shared/SKILL.md`（或用 symlink 规整路径） |
| lark-cli upstream skill 变更打破兼容 | 低 | git submodule 锁版本（pin 到具体 commit），定期同步评估 |
| `metadata.requires.bins: ["lark-cli"]` 字段 deer-flow 不解析 | 无影响 | deer-flow parser 忽略该字段；只需确保宿主机 PATH 里有 `lark-cli`（LocalSandbox bash 能访问） |
| Docker sandbox 模式下 lark-cli 配置访问不到 | — | 当前 `config.yaml` 是 `LocalSandboxProvider` + `allow_host_bash: true`，不受影响；若未来切 Docker，需把 lark-cli 配置目录 mount 进容器 |
| 凭据申请阻塞（D1） | 高 | spec 先行，凭据并行申请；凭据到位前不能跑端到端验证，但技能接入（第 5 节）可先做 |

---

## 9. 后续子项目衔接

本 spec 只覆盖 A。后续子项目（各自单独 spec）：

- **B** `mcp-lingxing` P0 工具：自建 MCP Server 包装领星 OpenAPI（参考 `governance/kb_mcp/` 模式），9 个 P0 工具 + 签名鉴权 + TTL 缓存。D1 阻塞：领星 AppID/Secret + IP 白名单。
- **C** 多维表 schema 搭建：3 张表（异常告警表/波动留痕表/影子建议表）字段 + 视图，通过 A 接入的 `lark-base` skill 写入飞书。依赖 A。
- **D** 规则引擎 + LLM 归因 Skill：包装成 deer-flow 技能，含三级阈值判定 + 波动留痕 + LLM 归因 + 影子 Top3。依赖 B（返回形状，可先 stub）+ 阈值签字。
- **E** 每日 9:00 定时任务：用 deer-flow 现成 `ScheduledTaskService`（`/api/scheduled-tasks`），建 cron 任务，prompt 触发 D 技能跑数据 + 写多维表 + 推送。依赖 A/B/C/D。
