# 飞书 MCP 接入（lark-cli 方式）

DeerFlow 通过飞书官方 `lark-cli`（npm `@larksuite/cli`）调用飞书能力（发消息、多维表 CRUD 等），不自建飞书 MCP Server。

## 架构

- lark-cli 装在宿主机，凭据用 OS keychain 存
- lark-cli 官方 27 个 skill 包通过 git submodule 放在 `skills/public/lark/`，格式兼容 deer-flow 技能系统
- agent 通过 bash 工具调 lark-cli 命令 + read_file 读 skill 文档
- 当前显式启用 3 个 skill：`lark-shared`（认证基础）、`lark-im`（消息推送）、`lark-base`（多维表 CRUD）；其余 24 个未在 `extensions_config.json` 显式声明（代码默认 enabled，显式声明便于审计和后续 disable）
- 挂载在 `skills/public/` 而非 `skills/custom/`：避免 `UserScopedSkillStorage` 的 shadow-mount 语义导致 lark skills 在用户创建自己的 custom skill 后消失

详见 `docs/superpowers/specs/2026-07-24-feishu-mcp-integration-design.md`。

## 前置条件

1. 飞书自建应用凭据（app_id/app_secret）—— 在飞书开放平台创建
2. scope 授权：`im:message`、`bitable:app`、`im:resource` 等
3. Linux 服务器需 OS keychain（secret-service/D-Bus）；若无，测试 lark-cli fallback

## 安装与配置

```bash
# 安装 lark-cli（与官方 README 一致，查阅 https://github.com/larksuite/cli）
npx @larksuite/cli@latest install
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

复制 `extensions_config.example.json` 为 `extensions_config.json` 后，如需启用 lark skill，将 `lark-shared`/`lark-im`/`lark-base` 的 `enabled` 改为 `true`（或依赖 public category 默认 enabled 行为，显式声明便于审计）。

## 排障

| 现象 | 排查 |
|---|---|
| agent 不调 lark-cli | 检查 `lark-im`/`lark-base` 是否 enabled（`GET /api/skills`）；用 `/lark-im ...` slash 激活 |
| bash 找不到 lark-cli | `which lark-cli`；若不在 PATH，检查 npm 全局目录 |
| 凭据失效 | `lark-cli auth status`；跑 `lark-cli auth login --recommend` 重登 |
| scope 不足 | `lark-cli auth check <scope>`；跑 `lark-cli auth login --scope "..."` 补 |
| Linux keychain 不可用 | 装 `dbus-x11` + `gnome-keyring`；或封装一层把凭据从 env 注入 lark-cli 配置目录 |
| 跨 skill 引用失败 | 检查 sandbox 是否把整个 `skills/public/` 挂载到 `/mnt/skills/public/`（而非只挂单个 skill 目录） |

## 维护

- lark-cli submodule pin 在 `skills/public/lark`，锁到具体 commit
- 升级 lark-cli：`git -C skills/public/lark fetch && git -C skills/public/lark checkout <new-pin>`，跑 `backend/tests/test_lark_skill_compatibility.py` 确认兼容，再 commit submodule bump
- **安全审查**：通过目录遍历发现的 skills（非 `.skill` 安装）不经过 installer 的安全扫描。lark-cli 是官方仓库风险低，但 submodule bump 时应人工审查新 skill 的 SKILL.md 内容
- 启用更多 lark skill：在 `extensions_config.json` 的 `skills` 段加 `"lark-<name>": {"enabled": true}`，reload（注：不显式声明也默认 enabled，显式声明便于审计和后续 disable）
