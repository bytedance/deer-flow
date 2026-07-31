# 飞书 MCP 接入（lark-cli 方式）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 deer-flow agent 能通过飞书官方 `lark-cli` 调用飞书能力（发消息/@、多维表 CRUD），作为后续 C/D/E 子项目的基础，零自写 Python 代码。

**Architecture:** lark-cli（npm `@larksuite/cli`）装在宿主机，凭据用 OS keychain 存；lark-cli 官方 27 个 skill 包通过 git submodule 放到 `skills/public/lark/`，格式兼容 deer-flow 技能系统（已验证 `parse_skill_file` 只提取 `name`/`description` 等字段，忽略 `metadata.requires.bins`/`version` 等）；agent 通过 bash 工具调 lark-cli 命令 + read_file 读 skill 文档。

**Tech Stack:** lark-cli（npm `@larksuite/cli`）、deer-flow 技能系统（`backend/packages/harness/deerflow/skills/`）、git submodule、pytest（兼容性回归测试）。

## Global Constraints

- **不写飞书 MCP Server**：复用 lark-cli，不自建（与 `governance/kb_mcp/` 模式不同）。
- **对话在 deer-flow 前端**，不在飞书（用户已明确）。
- **sandbox 模式**：当前 `config.yaml` 是 `LocalSandboxProvider` + `allow_host_bash: true`，agent bash 跑宿主机，lark-cli 装宿主机即可访问。
- **挂载到 `skills/public/` 而非 `skills/custom/`**：deer-flow 在有 `user_id`（已登录用户）时使用 `UserScopedSkillStorage`，其 shadow-mount 语义会导致全局 `skills/custom/` 下的 skill 在用户创建自己的 custom skill 后消失。`skills/public/` 对所有用户始终可见，不受 shadow-mount 影响。lark-cli 是官方维护的只读技能包，语义上等同 built-in。
- **D1 阻塞**：飞书应用凭据（app_id/app_secret + scope）尚未申请。Task 3–6 依赖凭据到位；Task 1、2、7 可先做。
- **git submodule 锁版本**：lark-cli submodule pin 到具体 commit，不跟 main。
- **Python 3.12+**，测试用 `PYTHONPATH=.` 跑（backend 目录）。

---

## File Structure

| 文件 | 责任 | 创建/修改 |
|---|---|---|
| `.gitmodules` | 登记 lark-cli submodule | 修改（新增条目） |
| `skills/public/lark/` | lark-cli 仓库 submodule 挂载点（含 27 个 skill） | 创建（submodule add） |
| `extensions_config.json` | 启用 lark-shared/lark-im/lark-base 三个 skill | 修改 |
| `backend/tests/test_lark_skill_compatibility.py` | 回归测试：lark-cli SKILL.md 格式兼容 deer-flow parser | 创建 |
| `AGENTS.md` | 加一段说明 lark-cli 接入方式 | 修改 |
| `backend/docs/FEISHU_MCP_INTEGRATION.md` | 面向运维的接入手册（安装/配置/授权/排障） | 创建 |

---

### Task 1: lark-cli skills git submodule 接入 + 兼容性回归测试

**Files:**
- Create: `backend/tests/test_lark_skill_compatibility.py`
- Create: `.gitmodules`（若不存在）或修改（新增 lark-cli 条目）
- Create: `skills/public/lark/`（submodule 挂载点）

**Interfaces:**
- Consumes: `deerflow.skills.parser.parse_skill_file`、`deerflow.skills.types.Skill`、`deerflow.skills.types.SkillCategory`
- Produces: `skills/public/lark/` 下 27 个 lark skill 目录（供 Task 2 启用、Task 4–5 调用）；回归测试 pin 住格式兼容性（upstream 升级时 CI 会发现破坏）

**为什么这个 task 先做**：不依赖 D1 凭据，先把"技能包能被 deer-flow 加载"这个事实用测试锁住，避免后续 upstream 升级悄悄打破兼容。

- [ ] **Step 1: 写失败测试（TDD）**

创建 `backend/tests/test_lark_skill_compatibility.py`：

```python
"""lark-cli 官方 skill 包与 deer-flow 技能系统的格式兼容性回归测试。

锁住四件事：
1. 我们依赖的 lark skill（lark-shared/lark-im/lark-base）的 SKILL.md 都能被
   deerflow.skills.parser.parse_skill_file 成功解析。
2. 解析出的 name/description 符合 deer-flow 技能系统的非空要求。
3. lark-cli 特有的 frontmatter 字段（metadata.requires.bins、version 等）被 parser
   安全忽略，不会导致解析失败。同时覆盖“有 metadata”（lark-im/lark-base）和
   “无 metadata”（lark-shared）两种情况。
4. lark-cli 的 version 字段不被误解析为 deer-flow 认识的字段。

upstream lark-cli 升级（git submodule bump）时，CI 会发现任何打破兼容的
frontmatter 变更。
"""

from pathlib import Path

from deerflow.skills.parser import parse_skill_file
from deerflow.skills.types import SkillCategory

REPO_ROOT = Path(__file__).resolve().parents[2]
LARK_SKILLS_DIR = REPO_ROOT / "skills" / "public" / "lark" / "skills"

# 我们 A 阶段启用的 3 个 skill + 它们依赖的 lark-shared
REQUIRED_LARK_SKILLS = ["lark-shared", "lark-im", "lark-base"]


def _skill_dir(name: str) -> Path:
    return LARK_SKILLS_DIR / name


def _skill_md(name: str) -> Path:
    return _skill_dir(name) / "SKILL.md"


def test_lark_skills_dir_exists():
    """submodule 必须已 add，skills/public/lark/skills 目录存在。"""
    assert LARK_SKILLS_DIR.exists(), (
        f"lark-cli skills 目录不存在：{LARK_SKILLS_DIR}\n"
        "先跑：git submodule add https://github.com/larksuite/cli.git skills/public/lark"
    )


def test_required_lark_skills_present():
    """我们依赖的 3 个 skill 的 SKILL.md 都在。"""
    missing = [n for n in REQUIRED_LARK_SKILLS if not _skill_md(n).exists()]
    assert not missing, f"缺 lark skill：{missing}"


def test_lark_skills_parse_with_deerflow_parser():
    """每个 lark SKILL.md 都能被 deer-flow parser 解析成 Skill 对象。"""
    for name in REQUIRED_LARK_SKILLS:
        skill = parse_skill_file(
            _skill_md(name),
            category=SkillCategory.PUBLIC,
        )
        assert skill is not None, f"解析 {name}/SKILL.md 返回 None（frontmatter 不合规）"
        assert skill.name == name, f"{name}: name 字段不符，得到 {skill.name!r}"
        assert skill.description and skill.description.strip(), (
            f"{name}: description 为空"
        )


def test_lark_metadata_fields_ignored():
    """lark-cli 的 metadata.requires.bins 等字段被 parser 安全忽略，不报错。

    这是兼容性的关键：deer-flow parser 只提取自己认识的字段，其余通过
    metadata.get(...) 忽略。如果 upstream lark-cli 加了 deer-flow 认识的
    字段名（如 allowed-tools）但语义不同，这个测试会暴露。

    同时覆盖两种情况：
    - lark-im：有 metadata 字段（metadata.requires.bins: ["lark-cli"]）
    - lark-shared：无 metadata 字段
    """
    for name in REQUIRED_LARK_SKILLS:
        skill = parse_skill_file(
            _skill_md(name),
            category=SkillCategory.PUBLIC,
        )
        assert skill is not None
        # lark-im/lark-base 的 frontmatter 有 metadata.requires.bins
        # deer-flow 不应该把这个误解析成 allowed_tools 或 required_secrets
        assert skill.allowed_tools is None, (
            f"{name}: lark-cli 的 metadata 字段不该被 deer-flow 误识别成 allowed-tools"
        )
        assert skill.required_secrets == (), (
            f"{name}: lark-cli 的 metadata 字段不该被 deer-flow 误识别成 required-secrets"
        )


def test_lark_version_field_ignored():
    """lark-cli 的 version 字段被 parser 安全忽略。

    lark-cli 的 SKILL.md 都有 version 字段（如 version: 1.0.0）。
    deer-flow 不提取这个字段，但需确认它不会导致解析失败或被误解析。
    """
    skill = parse_skill_file(
        _skill_md("lark-im"),
        category=SkillCategory.PUBLIC,
    )
    assert skill is not None
    # version 不在 deer-flow Skill dataclass 的字段中，parser 不会提取它
    # 这里主要确认解析成功且不报错
    assert skill.name == "lark-im"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `PYTHONPATH=. uv run pytest tests/test_lark_skill_compatibility.py -v`（在 `backend/` 目录下）
Expected: FAIL，`test_lark_skills_dir_exists` 报 "lark-cli skills 目录不存在"（因为 submodule 还没 add）

- [ ] **Step 3: add lark-cli submodule**

在 deer-flow 仓库根目录跑：

```bash
# pin 到一个稳定的 release tag/commit（这里先用 main，plan 阶段执行时
# 应换成最新的稳定 tag；执行时跑 git tag -l 看 lark-cli 有没有 release tag）
git submodule add https://github.com/larksuite/cli.git skills/public/lark
# 锁版本：执行时把 <PIN> 换成具体 commit（建议最新 tag 的 commit）
git -C skills/public/lark checkout <PIN>
git -C skills/public/lark fetch --tags 2>/dev/null || true
```

执行者注意：
- 若 `git submodule add` 报 "already exists in the index"，先跑 `git rm --cached skills/public/lark` 再 add。
- `<PIN>` 必须是具体 commit SHA 或 tag，不能是 `main`（避免 upstream 变更打破兼容）。执行时跑 `git -C skills/public/lark tag -l` 看有无 release tag；若无，pin 到当前 main 最新 commit。
- 挂载到 `skills/public/` 而非 `skills/custom/` 是因为 `UserScopedSkillStorage` 的 shadow-mount 语义：全局 `skills/custom/` 下的 skill 会在用户创建自己的 custom skill 后消失（见 Global Constraints）。
- lark-cli 是完整仓库（含 src/、docs/ 等），但 `os.walk` 只匹配 `SKILL.md` 文件，其他目录会被跳过。

- [ ] **Step 4: 跑测试验证通过**

Run: `PYTHONPATH=. uv run pytest tests/test_lark_skill_compatibility.py -v`（在 `backend/` 目录下）
Expected: PASS，5 个 test 全过

- [ ] **Step 5: 验证 deer-flow 能发现这些 skill**

启动 Gateway（或用现成进程），调技能列表 API：

```bash
# 假设 Gateway 跑在 8001
curl -s http://localhost:8001/api/skills | python3 -c "
import sys, json
data = json.load(sys.stdin)
skills = data.get('skills', [])
lark = [s for s in skills if s.get('name', '').startswith('lark-')]
print(f'lark skills found: {len(lark)}')
for s in lark[:5]:
    print(f'  - {s[\"name\"]}: enabled={s.get(\"enabled\")}')
assert len(lark) >= 27, f'期望 >=27 个 lark skill，实际 {len(lark)}'
"
```

Expected: 输出 `lark skills found: 27`（或更多），且至少包含 lark-shared/lark-im/lark-base（PUBLIC skills 默认 enabled=true，无需 Task 2 改）。

> 注：若 Gateway 没跑，可跳过这步，Task 2 会一起验证。

- [ ] **Step 6: commit**

```bash
git add .gitmodules skills/public/lark backend/tests/test_lark_skill_compatibility.py
git commit -m "feat(feishu): add lark-cli skill submodule + compatibility regression tests

- git submodule add lark-cli at skills/public/lark (pinned to <PIN>)
- add backend/tests/test_lark_skill_compatibility.py pinning frontmatter
  compatibility between lark-cli SKILL.md and deer-flow skill parser
- verified lark-shared/lark-im/lark-base parse correctly; metadata.requires.bins
  and version safely ignored
- mounted under skills/public/ to avoid UserScopedSkillStorage shadow-mount"
```

---

### Task 2: extensions_config.json 显式声明 3 个 lark skill

> **注意**：deer-flow 的 `is_skill_enabled` 方法在 `extensions_config.json` 中没有某 skill 的条目时**默认返回 enabled**（对所有 category 均如此）。因此 lark skills 在 Task 1 完成后就已经是 enabled 状态。本 task 的目的是**显式声明**这 3 个 skill 的启用状态，使其可审计、可后续 disable，而非功能必需。

**Files:**
- Modify: `extensions_config.json`（`skills` 段加 3 个 enabled 条目）

**Interfaces:**
- Consumes: Task 1 产出的 `skills/public/lark/skills/{lark-shared,lark-im,lark-base}/SKILL.md`
- Produces: 启用状态显式写进 `extensions_config.json`，便于审计和管理

- [ ] **Step 1: 修改 extensions_config.json**

在 `skills` 段加 3 个条目（保持现有条目不动）：

```json
{
  "skills": {
    "skill-reviewer": { "enabled": false },
    "injection-example": { "enabled": false },
    "example-safe-skill": { "enabled": false },
    "lark-shared": { "enabled": true },
    "lark-im": { "enabled": true },
    "lark-base": { "enabled": true }
  }
}
```

> 注：保持其他 skill 状态不动，只新增 3 行。

- [ ] **Step 2: 触发 deer-flow 重载配置**

deer-flow 的 MCP 配置和技能配置会检测 `extensions_config.json` 变化自动 reload（按 mtime+size+sha256 签名）。若已跑 `make dev`，等几秒或调：

```bash
curl -s -X GET http://localhost:8001/api/skills | python3 -m json.tool | head -40
```

若没自动 reload，调 MCP config PUT 触发：

```bash
curl -s -X PUT http://localhost:8001/api/mcp/config \
  -H "Content-Type: application/json" \
  -d @extensions_config.json | python3 -m json.tool
```

- [ ] **Step 3: 验证 3 个 skill enabled=true**

```bash
curl -s http://localhost:8001/api/skills | python3 -c "
import sys, json
data = json.load(sys.stdin)
skills = {s['name']: s for s in data.get('skills', [])}
for name in ['lark-shared', 'lark-im', 'lark-base']:
    s = skills.get(name)
    assert s is not None, f'{name} 不在技能列表里'
    assert s.get('enabled') is True, f'{name} enabled 应为 true，实际 {s.get(\"enabled\")}'
    print(f'  {name}: enabled={s.get(\"enabled\")} ✓')
print('全部启用成功')
"
```

Expected: 输出 3 行 `✓` + `全部启用成功`

- [ ] **Step 4: commit**

```bash
git add extensions_config.json
git commit -m "feat(feishu): enable lark-shared/lark-im/lark-base skills

A 子项目（飞书 MCP 接入）第二步：显式声明 lark-cli 的 3 个核心 skill 启用状态。
其余 24 个 lark skill 虽默认 enabled，但未显式声明，后续按需开。"
```

---

### Task 3: 安装 + 配置 lark-cli（D1 阻塞：凭据到位后执行）

> **前置条件**：飞书应用凭据已申请（app_id/app_secret 到手 + scope 已授：`im:message`/`bitable:app`/`im:resource` 等）。spec 第 3 节列了完整 scope 清单。凭据没到位前这个 task 跑不动，跳过。

**Files:** 无代码改动，纯运维操作（lark-cli 装在宿主机，凭据存 OS keychain）

**Interfaces:**
- Consumes: 飞书应用凭据（app_id/app_secret）
- Produces: 宿主机上 lark-cli 已登录，bash 调用无需再认证

- [ ] **Step 1: 装 lark-cli**

> **执行前先查阅 lark-cli README**（https://github.com/larksuite/cli）确认安装命令。下方命令基于 lark-shared SKILL.md 的用法推断，但官方 README 可能有更准确的安装方式（如 `npm install -g @larksuite/cli` 或 `npx @larksuite/cli` 直接运行）。

```bash
# 方式 A：全局安装（推荐，bash 工具可直接调 lark-cli）
npm install -g @larksuite/cli
# 方式 B：npx 运行（每次调用需加 npx 前缀，不适合 agent bash 调用）
# npx @larksuite/cli@latest <command>
```

Expected: 安装成功，`lark-cli --version` 输出版本号

验证：
```bash
lark-cli --version
which lark-cli
```

Expected: `lark-cli` 路径在 PATH 里（`/usr/local/bin/lark-cli` 或 `~/.npm-global/bin/lark-cli`）

- [ ] **Step 2: 配置应用凭据**

```bash
lark-cli config init --new
```

这会输出一个授权 URL。在浏览器里完成应用配置（输入 app_id/app_secret 或让 lark-cli 自动创建新应用）。

Expected: 命令退出后 `lark-cli auth status` 能看到应用信息

- [ ] **Step 3: OAuth 登录授权**

```bash
lark-cli auth login --recommend
```

`--recommend` 自动选常用 scope。命令输出授权 URL，浏览器里确认。

Expected: 登录成功

- [ ] **Step 4: 验证登录 + scope**

```bash
lark-cli auth status
lark-cli auth check im:message
lark-cli auth check bitable:app
```

Expected:
- `auth status` 显示已登录 + 应用信息
- `auth check im:message` 退出码 0
- `auth check bitable:app` 退出码 0

若 `auth check` 报 scope 不全，补登录：
```bash
lark-cli auth login --scope "im:message,bitable:app,im:resource"
```

- [ ] **Step 5: 跑第一个 API 调用冒烟测试**

```bash
# 列出当前用户身份，验证凭据能调通飞书 API
lark-cli auth list
# 或发一条测试消息到自己的机器人私聊（chat_id 用自己的 p2p chat_id）
lark-cli im +messages-send --as bot --chat-id "oc_xxx" --text "hello from lark-cli" --dry-run
```

Expected: `--dry-run` 预览请求成功，输出 `{"ok": true, ...}`

- [ ] **Step 6: 无需 commit**

这是运维操作，不产生代码改动。但建议在 `backend/docs/FEISHU_MCP_INTEGRATION.md`（Task 7）记录执行结果（登录用户、scope 清单）备查。

---

### Task 4: 端到端推送验证（D1 阻塞：依赖 Task 3）

> **前置条件**：Task 3 完成（lark-cli 已登录），且有一个测试用的飞书群 chat_id（oc_xxx）。

**Files:** 无代码改动，验证 deer-flow 前端对话能调 lark-cli 发消息

- [ ] **Step 1: 在 deer-flow 前端发起对话**

打开 deer-flow 前端（http://localhost:2026），新建一个 thread，发消息：

```
用 lark-cli 给我发条测试消息到 oc_xxx 群（chat_id: oc_xxx），内容 "hello from deerflow agent"
```

Expected: agent 识别意图 → 调 `lark-im` skill 文档（read_file 读 SKILL.md）→ bash 跑 `lark-cli im +messages-send --as bot --chat-id oc_xxx --text "hello from deerflow agent"` → 返回 `{"ok": true, ...}`

- [ ] **Step 2: 验证飞书群收到消息**

打开飞书，进 oc_xxx 群，确认收到 "hello from deerflow agent" 文本消息。

Expected: 消息已到达，发送者是机器人

- [ ] **Step 3: 验证跨 skill 引用路径**

lark-im 的 SKILL.md 开头写了 `CRITICAL — 开始前 MUST 先用 Read 工具读取 ../lark-shared/SKILL.md`。验证 agent 能正确解析这个相对路径：

在对话里问：
```
读取 lark-im skill 的 SKILL.md，然后按它的指引读取 lark-shared 的 SKILL.md
```

Expected: agent 能从 `/mnt/skills/public/lark/skills/lark-im/SKILL.md` 解析出 `../lark-shared/SKILL.md` → `/mnt/skills/public/lark/skills/lark-shared/SKILL.md`，成功读取两个文件。

> 若失败，检查 sandbox 是否把整个 `skills/public/` 目录挂载到 `/mnt/skills/public/`（而非只挂单个 skill 目录）。

- [ ] **Step 4: 失败排查（若 agent 没调 lark-cli）**

若 agent 不知道怎么调，检查：
1. `lark-im` 技能是否 enabled（`GET /api/skills`）
2. agent 是否用了 slash 激活：在对话里改用 `/lark-im 给我发条测试消息到 oc_xxx 群，内容 "hello from deerflow agent"`
3. bash 工具是否能访问 lark-cli：在对话里问 "跑一下 `which lark-cli` 看看在不在 PATH"
4. lark-cli 凭据是否还在：`lark-cli auth status`

Expected: 排查后 agent 能正确调用

- [ ] **Step 5: 无需 commit**

验证步骤，不产生代码。

---

### Task 5: 端到端多维表验证（D1 阻塞：依赖 Task 3）

> **前置条件**：Task 3 完成，且有一个测试用的多维表 app_token + table_id（可先在飞书里手动建一个测试表，拿 app_token 和 table_id）。

- [ ] **Step 1: 在 deer-flow 前端发起对话**

```
用 lark-cli 在多维表里创建一条记录：app_token=xxx, table_id=yyy，记录内容 {字段A: 值1, 字段B: 值2}
```

Expected: agent 调 `lark-base` skill 文档 → bash 跑 `lark-cli base +records-create --app-token xxx --table-id yyy --records '[{"fields": {"字段A": "值1", "字段B": "值2"}}]'` → 返回 `{"ok": true, ...}`

- [ ] **Step 2: 验证多维表出现新记录**

打开飞书多维表，确认 table_id=yyy 的表里新增了一条记录，字段值对。

Expected: 记录已创建

- [ ] **Step 3: 失败排查（若 agent 没调 lark-base）**

同 Task 4 Step 3，把 `lark-im` 换成 `lark-base`。

- [ ] **Step 4: 无需 commit**

---

### Task 6: 降级验证（D1 阻塞：依赖 Task 3）

> **前置条件**：Task 3 完成。

- [ ] **Step 1: 模拟凭据失效**

```bash
lark-cli auth logout
```

Expected: 凭据清除，`lark-cli auth status` 显示未登录

- [ ] **Step 2: 在 deer-flow 前端发起对话**

```
用 lark-cli 给我发条消息到 oc_xxx 群，内容 "should fail"
```

Expected: agent bash 跑 `lark-cli im +messages-send ...` 得到非零退出码 + stderr JSON `{"ok": false, "error": {"type": "auth", ...}}`，agent 识别错误并提示用户重新登录（如 "lark-cli 凭据失效了，请跑 `lark-cli auth login --recommend` 重新授权"），不崩溃。

- [ ] **Step 3: 重新登录恢复**

```bash
lark-cli auth login --recommend
```

Expected: 凭据恢复，Task 4 的推送对话能再次成功

- [ ] **Step 4: 无需 commit**

---

### Task 7: 文档更新

**Files:**
- Create: `backend/docs/FEISHU_MCP_INTEGRATION.md`
- Modify: `AGENTS.md`（加一段 lark-cli 接入说明，指向详细文档）

**Interfaces:**
- Consumes: Task 1–6 的执行结果
- Produces: 面向运维的接入手册 + 面向开发者的架构说明

- [ ] **Step 1: 写 backend/docs/FEISHU_MCP_INTEGRATION.md**

```markdown
# 飞书 MCP 接入（lark-cli 方式）

DeerFlow 通过飞书官方 `lark-cli`（npm `@larksuite/cli`）调用飞书能力（发消息、多维表 CRUD 等），不自建飞书 MCP Server。

## 架构

- lark-cli 装在宿主机，凭据用 OS keychain 存
- lark-cli 官方 27 个 skill 包通过 git submodule 放在 `skills/public/lark/`，格式兼容 deer-flow 技能系统
- agent 通过 bash 工具调 lark-cli 命令 + read_file 读 skill 文档
- 当前显式启用 3 个 skill：`lark-shared`（认证基础）、`lark-im`（消息推送）、`lark-base`（多维表 CRUD）
- 挂载在 `skills/public/` 而非 `skills/custom/`：避免 `UserScopedSkillStorage` 的 shadow-mount 语义导致 lark skills 在用户创建自己的 custom skill 后消失

详见 `docs/superpowers/specs/2026-07-24-feishu-mcp-integration-design.md`。

## 前置条件

1. 飞书自建应用凭据（app_id/app_secret）—— 在飞书开放平台创建
2. scope 授权：`im:message`、`bitable:app`、`im:resource` 等
3. Linux 服务器需 OS keychain（secret-service/D-Bus）；若无，测试 lark-cli fallback

## 安装与配置

```bash
# 全局安装 lark-cli（查阅 https://github.com/larksuite/cli README 确认）
npm install -g @larksuite/cli
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

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
```

- [ ] **Step 2: 在 AGENTS.md 加一段说明**

在 `AGENTS.md` 的 "Cross-Cutting Conventions" 段后（或合适位置）加：

```markdown
## 飞书能力接入（lark-cli）

DeerFlow 通过飞书官方 `lark-cli`（npm `@larksuite/cli`）调用飞书能力（发消息、多维表 CRUD 等），不自建飞书 MCP Server。lark-cli 官方 27 个 skill 包通过 git submodule 放在 `skills/public/lark/`，格式兼容 deer-flow 技能系统（`parse_skill_file` 只提取 `name`/`description`，忽略 `metadata.requires.bins`/`version` 等）。挂载在 `skills/public/` 而非 `skills/custom/`，避免 `UserScopedSkillStorage` 的 shadow-mount 语义导致 lark skills 在用户创建自己的 custom skill 后消失。当前显式声明 `lark-shared`、`lark-im`、`lark-base` 三个 skill 启用。详见 [backend/docs/FEISHU_MCP_INTEGRATION.md](backend/docs/FEISHU_MCP_INTEGRATION.md)。
```

- [ ] **Step 3: commit**

```bash
git add backend/docs/FEISHU_MCP_INTEGRATION.md AGENTS.md
git commit -m "docs(feishu): add lark-cli integration guide and AGENTS.md note

A 子项目（飞书 MCP 接入）最后一步：运维接入手册 + 架构说明。"
```

---

## Self-Review

**1. Spec coverage（spec 各节是否都有 task 覆盖）：**
- spec 第 1 节目标 → Task 1–7 整体覆盖 ✓
- spec 第 2 节架构 → Task 1（submodule）+ Task 3（lark-cli 装+授权）✓
- spec 第 3 节 D1 前置 → Task 3 前置条件标注 ✓
- spec 第 4 节安装步骤 → Task 3 Step 1–4 ✓
- spec 第 5 节技能接入（含兼容性分析、submodule 放置、启用配置）→ Task 1 + Task 2 + Task 1 的回归测试 ✓
- spec 第 6 节验证标准（6 项）→ Task 3 Step 4–5（自检）、Task 4（端到端推送 + 跨 skill 引用）、Task 5（端到端多维表）、Task 6（降级）、Task 1 Step 5（技能加载）✓ —— 验证标准 6 项全覆盖
- spec 第 7 节边界 → plan Global Constraints + 各 task 非目标说明 ✓
- spec 第 8 节风险 → Task 3 排障覆盖 keychain/scope，Task 7 排障表覆盖其余 ✓

**2. Placeholder scan：**
- Task 1 Step 3 `<PIN>` 是占位符，但已明确说明执行时跑 `git tag -l` 换成具体 commit/tag —— 这是合理的执行时变量，不是 plan placeholder
- Task 4/5 的 `oc_xxx`/`app_token=xxx` 是测试输入占位，执行者填真实值 —— 合理
- 无 "TBD"/"implement later"/"add error handling" 等红旗 ✓

**3. Type consistency：**
- Task 1 测试用 `parse_skill_file`、`SkillCategory.PUBLIC` —— 与 `parser.py` 实际签名一致 ✓（改为 PUBLIC 因挂载在 `skills/public/` 下，避免 `UserScopedSkillStorage` shadow-mount 问题）
- Task 1 测试访问 `skill.name`/`skill.description`/`skill.allowed_tools`/`skill.required_secrets` —— 与 `Skill` dataclass 字段一致 ✓
- Task 2 改 `extensions_config.json` 的 `skills` 段 —— 与现有结构一致 ✓

**4. 架构审查修订记录：**
- **shadow-mount 问题**：原 plan 将 submodule 挂在 `skills/custom/lark/`，审查发现 `UserScopedSkillStorage` 的 shadow-mount 语义会导致已登录用户创建自己的 custom skill 后 lark skills 消失。改为挂载到 `skills/public/lark/`，PUBLIC category 对所有用户始终可见 ✓
- **skill 数量**：原 plan 写 26 个，实际 GitHub API 确认为 27 个，已全文修正 ✓
- **默认 enabled**：原 plan Task 2 暗示需显式启用才能用，审查发现 `is_skill_enabled` 在无条目时默认返回 enabled，Task 2 改为“显式声明”语义 ✓
- **lark-shared 无 metadata**：原 plan 测试只检查 lark-im，审查发现 lark-shared 无 metadata 字段，测试改为覆盖全部 3 个 skill ✓
- **version 字段**：原 plan 未提及 version 字段，审查发现 lark-cli SKILL.md 都有 version 字段，新增 `test_lark_version_field_ignored` 测试 ✓
- **跨 skill 引用**：原 plan 未验证 lark-im → lark-shared 的相对路径引用，审查新增 Task 4 Step 3 ✓
- **安装命令**：原 plan 用 `npx @larksuite/cli@latest install`，审查加注“查阅 README 确认”并提供全局安装替代方案 ✓
- **安全审查**：审查新增文档说明（Task 7）：目录遍历发现的 skills 不经过 installer 安全扫描，submodule bump 需人工审查 ✓

无问题，plan 可用。
