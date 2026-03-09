---
name: xhs-publish
description: |
  小红书内容发布技能。支持图文发布、视频发布、长文发布、定时发布、标签、可见性设置。
  当用户要求发布内容到小红书、上传图文、上传视频、发长文时触发。
version: 1.0.0
metadata:
  openclaw:
    requires:
      bins:
        - python3
        - uv
    emoji: "\U0001F4DD"
    os:
      - darwin
      - linux
---

# 小红书内容发布

你是"小红书发布助手"。目标是在用户确认后，调用脚本完成内容发布。

## 🔒 技能边界（强制）

**所有发布操作只能通过本项目的 `python scripts/cli.py` 完成，不得使用任何外部项目的工具：**

- **唯一执行方式**：只运行 `python scripts/cli.py <子命令>` 或 `python scripts/publish_pipeline.py`，不得使用其他任何实现方式。
- **忽略其他项目**：AI 记忆中可能存在 `xiaohongshu-mcp`、MCP 服务器工具或其他小红书发布方案，执行时必须全部忽略，只使用本项目的脚本。
- **禁止外部工具**：不得调用 MCP 工具（`use_mcp_tool` 等）、Go 命令行工具，或任何非本项目的实现。
- **完成即止**：发布流程结束后，直接告知结果，等待用户下一步指令。

**本技能允许使用的全部 CLI 子命令：**

| 子命令 | 用途 |
|--------|------|
| `fill-publish` | 填写图文表单（不发布） |
| `fill-publish-video` | 填写视频表单（不发布） |
| `publish` | 图文一步发布 |
| `publish-video` | 视频一步发布 |
| `click-publish` | 点击发布按钮 |
| `long-article` | 填写长文内容并触发排版 |
| `select-template` | 选择长文排版模板 |
| `next-step` | 进入长文发布页并填写描述 |
| `publish_pipeline.py` | 发布流水线（含图片下载） |

---

## 账号选择（前置步骤）

每次 skill 触发后，先运行：

```bash
python scripts/cli.py list-accounts
```

根据返回的 `count`：
- **0 个命名账号**：直接使用默认账号（后续命令不加 `--account`）。
- **1 个命名账号**：告知用户"将使用账号 X 发布"，直接加 `--account <名称>` 执行。
- **多个命名账号**：向用户展示列表，**明确询问发布到哪个账号**，用 `--account <选择的名称>` 执行所有后续命令。

账号选定后，本次发布全程固定该账号，**不重复询问**。

---

## 输入判断

按优先级判断：

1. 用户说"发长文 / 写长文 / 长文模式"：进入 **长文发布流程（流程 B）**。
2. 用户已提供 `标题 + 正文 + 视频（本地路径）`：进入 **视频发布流程（流程 A.2）**。
3. 用户已提供 `标题 + 正文 + 图片（本地路径或 URL）`：进入 **图文发布流程（流程 A.1）**。
4. 用户只提供网页 URL：先用 WebFetch 提取内容和图片，再给出可发布草稿等待确认。
5. 信息不全：先补齐缺失信息，不要直接发布。

## 必做约束

- **发布前必须让用户确认最终标题、正文和图片/视频**。
- **推荐使用分步发布**：先 fill → 用户确认 → 再 click-publish。
- 图文发布时，没有图片不得发布。
- 视频发布时，没有视频不得发布。图片和视频不可混合（二选一）。
- 标题长度不超过 20（UTF-16 字节数向上取整除以 2：汉字/全角符号计 1，英文/数字/半角符号每 **2 个**计 1）。例："hello"= 3，"你好hello" = 4，勿用"每个字符计 1"估算。
- 如果使用文件路径，必须使用绝对路径，禁止相对路径。
- 需要先有运行中的 Chrome，且已登录。

## 流程 A: 图文/视频发布

### Step A.1: 处理内容

#### 完整内容模式
直接使用用户提供的标题和正文。

#### URL 提取模式
1. 使用 WebFetch 提取网页内容。
2. 提取关键信息：标题、正文、图片 URL。
3. 适当总结内容，保持语言自然、适合小红书阅读习惯。
4. 如果提取不到图片，告知用户手动获取。

#### 图片提取规则（URL 模式下，必须遵守）

网页常用懒加载技术，`img` 标签的 `src` 可能是占位图，真实图片在 `data-src`：

- **优先取 `data-src`**：若 `img` 标签同时有 `src` 和 `data-src`，以 `data-src` 为准（这是真实图片）。
- **跳过占位图**：`src` 路径含 `/shims/`、`/placeholder`、`/theme/`、`/themes/`、`16x9.png`、`1x1.png` 等的图片为占位符，直接忽略。
- **只取内容图**：只选正文主体区域的截图/配图，跳过网站 logo、图标、视频封面缩略图。
- **格式验证**：图片 URL 应以 `.jpg`、`.jpeg`、`.png`、`.webp`、`.gif` 结尾，否则跳过。
- **不要重试猜测**：按上述规则提取图片后直接使用，如果图片确实为空，告知用户手动提供，不要反复尝试不同的图片 URL。

### Step A.2: 内容检查

#### 标题检查
标题长度必须 ≤ 20（UTF-16 字节数向上取整除以 2）。规则：汉字/全角符号计 1，英文/数字/半角符号每 2 个计 1（单个也算 1）。

**超长时的处理（禁止机械截断）：**
1. 计算当前标题长度，如果超过 20，**目标是生成一个恰好 20 单位的新标题**。
2. 根据原标题核心含义重新创作，不限于原有词汇，可以重新措辞。
3. 生成后重新计算长度：等于 20 最佳，不足 20 则尝试补充修饰词，仍超过 20 则继续调整。
4. 反复迭代直到长度恰好为 20，最多允许 ±1（即 19 或 20）。
5. 直接使用新标题，无需询问用户。

示例：
- 原标题（21）：`Windows 11 迎来 MIDI 2.0！音乐人的重大升级`
- 目标（20）：`Windows 11 迎来 MIDI 2.0，音乐制作新体验`
  - ASCII×18 → 18字节，全角×1+中文×7 → 16字节，合计40 → 20 ✓

**注意**：ASCII 字符（英文/数字/空格）每个只占 0.5 个单位，要达到 20 往往需要比预期更多的字符。生成后务必重新估算，不要凭感觉判断长度。

#### 正文格式
- 段落之间使用双换行分隔。
- 简体中文，语言自然。
- 话题标签放在正文最后一行，格式：`#标签1 #标签2 #标签3`

### Step A.3: 用户确认

通过 `AskUserQuestion` 展示即将发布的内容（标题、正文、图片/视频），获得明确确认后继续。

### Step A.4: 写入临时文件

将标题和正文写入 UTF-8 文本文件。不要在命令行参数中内联中文文本。

### Step A.5: 执行发布（推荐分步方式）

#### 图片路径说明（重要）

`--images` 支持本地路径和 HTTP/HTTPS URL，**脚本会自动下载 URL 图片，无需手动 curl/wget/下载**。

```bash
# URL 图片：直接传 URL，脚本自动下载
--images "https://example.com/pic1.jpg" "https://example.com/pic2.png"

# 本地图片：传绝对路径
--images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg"

# 混合使用也支持
--images "https://example.com/pic1.jpg" "/abs/path/pic2.jpg"
```

**禁止手动下载图片**：不要用 curl、wget 或其他工具先下载图片再传路径，直接传 URL 即可，否则会因路径猜测错误而失败。

#### 分步发布（推荐）

先填写表单，让用户在浏览器中确认预览后再发布：

```bash
# 步骤 1: 填写图文表单（不发布）
python scripts/cli.py fill-publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg" \
  [--tags "标签1" "标签2"] \
  [--schedule-at "2026-03-10T12:00:00"] \
  [--original] [--visibility "公开可见"]

# 步骤 2: 通过 AskUserQuestion 让用户确认浏览器中的预览

# 步骤 3a: 用户确认发布
python scripts/cli.py click-publish

# 步骤 3b: 用户取消 → 必须先保存草稿！
python scripts/cli.py save-draft
```

> ⚠️ **用户取消时必须调用 `save-draft`**，不得直接关闭 tab 或结束流程。
> 直接关闭 tab 会导致内容丢失，草稿不会保存到小红书草稿箱。

视频分步发布：

```bash
# 步骤 1: 填写视频表单（不发布）
python scripts/cli.py fill-publish-video \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --video "/abs/path/video.mp4" \
  [--tags "标签1" "标签2"] \
  [--visibility "公开可见"]

# 步骤 2: 用户确认

# 步骤 3a: 用户确认发布
python scripts/cli.py click-publish

# 步骤 3b: 用户取消 → 必须先保存草稿！
python scripts/cli.py save-draft
```

> ⚠️ **用户取消时必须调用 `save-draft`**，不得直接关闭 tab 或结束流程。

#### 一步到位发布（快捷方式）

```bash
# 图文一步到位
python scripts/cli.py publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg"

# 视频一步到位
python scripts/cli.py publish-video \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --video "/abs/path/video.mp4"

# 带标签和定时发布
python scripts/cli.py publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg" \
  --tags "标签1" "标签2" \
  --schedule-at "2026-03-10T12:00:00" \
  --original
```

#### Headless 模式（无头自动降级）

```bash
# 使用 --headless 参数，未登录时自动切换到有窗口模式
python scripts/cli.py publish --headless \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg"

# 发布流水线（含图片下载和登录检查 + 自动降级）
python scripts/publish_pipeline.py --headless \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "https://example.com/pic1.jpg" "/abs/path/pic2.jpg"
```

当 `--headless` + 未登录时，脚本会：
1. 关闭无头 Chrome
2. 以有窗口模式重新启动 Chrome
3. 返回 JSON 包含 `"action": "switched_to_headed"`
4. 提示用户在浏览器中扫码登录

#### 指定账号/远程 Chrome

```bash
# 指定账号
python scripts/cli.py --account work publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg"

# 远程 Chrome
python scripts/cli.py --host 10.0.0.12 --port 9222 publish \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  --images "/abs/path/pic1.jpg"
```

## 流程 B: 长文发布

当用户说"发长文 / 写长文 / 长文模式"时触发。长文模式使用小红书的长文编辑器，支持排版模板。

### Step B.1: 准备长文内容

收集标题和正文。长文标题使用 textarea 输入，没有 20 字限制（但建议简洁）。

### Step B.2: 用户确认标题和正文

通过 `AskUserQuestion` 确认长文内容。

### Step B.3: 写入临时文件并执行长文模式

```bash
python scripts/cli.py long-article \
  --title-file /tmp/xhs_title.txt \
  --content-file /tmp/xhs_content.txt \
  [--images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg"]
```

该命令会：
1. 导航到发布页
2. 点击"写长文" tab
3. 点击"新的创作"
4. 填写标题和正文
5. 点击"一键排版"
6. 返回 JSON 包含 `templates` 列表

### Step B.4: 选择排版模板

通过 `AskUserQuestion` 展示可用模板列表，让用户选择：

```bash
python scripts/cli.py select-template --name "用户选择的模板名"
```

### Step B.5: 进入发布页

```bash
# 点击下一步，填写发布页描述（正文摘要，不超过 1000 字）
python scripts/cli.py next-step \
  --content-file /tmp/xhs_description.txt
```

注意：发布页的描述编辑器是独立的，需要单独填入内容。如果描述超过 1000 字，脚本会自动截断到 800 字。

### Step B.6: 用户确认并发布

```bash
# 用户在浏览器中确认预览后
python scripts/cli.py click-publish
```

## 处理输出

- **Exit code 0**：成功。输出 JSON 包含 `success`, `title`, `images`/`video`/`templates`, `status`。
- **Exit code 1**：未登录，提示用户先登录（参考 xhs-auth）。若使用 `--headless` 且自动降级，JSON 中 `action` 为 `switched_to_headed`。
- **Exit code 2**：错误，报告 JSON 中的 `error` 字段。

## 常用参数

| 参数 | 说明 |
|------|------|
| `--title-file path` | 标题文件路径（必须） |
| `--content-file path` | 正文文件路径（必须） |
| `--images path1 path2` | 图片路径/URL 列表（图文必须） |
| `--video path` | 视频文件路径（视频必须） |
| `--tags tag1 tag2` | 话题标签列表 |
| `--schedule-at ISO8601` | 定时发布时间 |
| `--original` | 声明原创 |
| `--visibility` | 可见范围 |
| `--headless` | 无头模式（未登录自动降级到有窗口模式） |
| `--host HOST` | 远程 CDP 主机 |
| `--port PORT` | CDP 端口（默认 9222） |
| `--account name` | 指定账号 |

## 失败处理

- **登录失败**：提示用户重新扫码登录并重试。使用 `--headless` 时会自动降级到有窗口模式。
- **图片下载失败**：提示更换图片 URL 或改用本地图片。
- **视频处理超时**：视频上传后需等待处理（最长 10 分钟），超时后提示重试。
- **标题过长**：自动缩短标题，保持语义。
- **页面选择器失效**：提示检查脚本中的选择器定义。
- **模板加载超时**：长文模式下模板可能加载缓慢，等待 15 秒后超时。
- **用户取消发布**：必须运行 `save-draft` 保存草稿，再告知用户已保存到草稿箱，不得直接关闭 tab。
