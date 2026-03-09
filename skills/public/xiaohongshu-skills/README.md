# xiaohongshu-skills

小红书自动化 Skills，基于 Python CDP 浏览器自动化引擎。

支持 [OpenClaw](https://github.com/anthropics/openclaw) 及所有兼容 `SKILL.md` 格式的 AI Agent 平台（如 Claude Code）。

## 功能概览

| 技能 | 说明 | 核心能力 |
|------|------|----------|
| **xhs-auth** | 认证管理 | 登录检查、扫码登录、多账号切换 |
| **xhs-publish** | 内容发布 | 图文 / 视频 / 长文发布、定时发布、分步预览 |
| **xhs-explore** | 内容发现 | 关键词搜索、笔记详情、用户主页、首页推荐 |
| **xhs-interact** | 社交互动 | 评论、回复、点赞、收藏 |
| **xhs-content-ops** | 复合运营 | 竞品分析、热点追踪、批量互动、内容创作 |

支持**连贯操作** — 你可以用自然语言下达复合指令，Agent 会自动串联多个技能完成任务。例如：

> "搜索刺客信条最火的图文帖子，收藏它，然后告诉我讲了什么"

Agent 会自动执行：搜索 → 筛选图文 → 按点赞排序 → 收藏 → 获取详情 → 总结内容。

## 安装

### 前置条件

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) 包管理器
- Google Chrome 浏览器

### 方法一：下载 ZIP 安装（推荐）

最简单稳妥的方式，适用于 OpenClaw 及所有支持 `SKILL.md` 的 Agent 平台。

1. 在 GitHub 仓库页面点击 **Code → Download ZIP**，下载项目压缩包。
2. 解压到你的 Agent 的 skills 目录下：

```
# OpenClaw 示例
<openclaw-project>/skills/xiaohongshu-skills/

# Claude Code 示例
<your-project>/.claude/skills/xiaohongshu-skills/
```

3. 安装 Python 依赖：

```bash
cd xiaohongshu-skills
uv sync
```

安装完成后，Agent 会自动识别 `SKILL.md` 并加载小红书技能。

### 方法二：Git Clone

```bash
# 进入 skills 目录
cd <your-agent-project>/skills/

# 克隆项目
git clone https://github.com/autoclaw-cc/xiaohongshu-skills.git
cd xiaohongshu-skills

# 安装依赖
uv sync
```

> 其他支持 SKILL.md 格式的 Agent 框架安装方式类似 — 将本项目放入其 skills 目录即可。

## 使用方式

### 作为 AI Agent 技能使用（推荐）

安装到 skills 目录后，直接用自然语言与 Agent 对话即可。Agent 会根据你的意图自动路由到对应技能。

**认证登录：**
> "登录小红书" / "检查登录状态"

**搜索浏览：**
> "搜索关于露营的笔记" / "查看这条笔记的详情"

**发布内容：**
> "帮我发一条图文笔记，标题是…，配图是…"

**社交互动：**
> "给这条笔记点赞" / "收藏这条帖子" / "评论：写得太好了"

**复合操作：**
> "搜索竞品账号最近的爆款笔记，分析他们的选题方向"

### 作为 CLI 工具使用

所有功能也可以通过命令行直接调用，输出 JSON 格式，便于脚本集成。

#### 1. 启动 Chrome

```bash
# 有窗口模式（首次登录必须）
python scripts/chrome_launcher.py

# 无头模式
python scripts/chrome_launcher.py --headless
```

#### 2. 登录

```bash
# 检查登录状态（已登录时返回用户昵称和小红书号）
python scripts/cli.py check-login

# 扫码登录
python scripts/cli.py login
```

#### 3. 搜索笔记

```bash
python scripts/cli.py search-feeds --keyword "关键词"

# 带筛选条件
python scripts/cli.py search-feeds \
  --keyword "关键词" \
  --sort-by "最多点赞" \
  --note-type "图文"
```

#### 4. 查看笔记详情

```bash
python scripts/cli.py get-feed-detail \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN
```

#### 5. 发布内容

```bash
# 图文发布（分步：填写 → 预览 → 确认发布）
python scripts/cli.py fill-publish \
  --title-file title.txt \
  --content-file content.txt \
  --images "/abs/path/pic1.jpg" "/abs/path/pic2.jpg"

# 用户在浏览器中预览确认后
python scripts/cli.py click-publish

# 或保存为草稿
python scripts/cli.py save-draft

# 视频发布
python scripts/cli.py publish-video \
  --title-file title.txt \
  --content-file content.txt \
  --video "/abs/path/video.mp4"

# 长文发布
python scripts/cli.py long-article \
  --title-file title.txt \
  --content-file content.txt
```

#### 6. 社交互动

```bash
# 评论
python scripts/cli.py post-comment \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN \
  --content "评论内容"

# 点赞
python scripts/cli.py like-feed \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN

# 收藏
python scripts/cli.py favorite-feed \
  --feed-id FEED_ID --xsec-token XSEC_TOKEN
```

## CLI 命令参考

全局选项：
- `--host HOST` — Chrome 调试主机（默认 127.0.0.1）
- `--port PORT` — Chrome 调试端口（默认 9222）
- `--account NAME` — 指定账号

| 子命令 | 说明 |
|--------|------|
| `check-login` | 检查登录状态，返回用户昵称和小红书号 |
| `login` | 获取登录二维码，等待扫码，登录后返回用户信息 |
| `delete-cookies` | 清除 cookies（退出/切换账号） |
| `list-feeds` | 获取首页推荐 Feed |
| `search-feeds` | 关键词搜索笔记（支持排序/类型/时间/范围/位置筛选） |
| `get-feed-detail` | 获取笔记完整内容和评论 |
| `user-profile` | 获取用户主页信息和帖子列表 |
| `post-comment` | 对笔记发表评论 |
| `reply-comment` | 回复指定评论 |
| `like-feed` | 点赞 / 取消点赞 |
| `favorite-feed` | 收藏 / 取消收藏 |
| `publish` | 一步发布图文 |
| `publish-video` | 一步发布视频 |
| `fill-publish` | 填写图文表单（不发布，供预览） |
| `fill-publish-video` | 填写视频表单（不发布，供预览） |
| `click-publish` | 确认发布（点击发布按钮） |
| `save-draft` | 保存为草稿 |
| `long-article` | 长文模式：填写 + 一键排版 |
| `select-template` | 选择长文排版模板 |
| `next-step` | 长文下一步 + 填写描述 |

退出码：`0` 成功 · `1` 未登录 · `2` 错误

## 项目结构

```
xiaohongshu-skills/
├── scripts/                        # Python CDP 自动化引擎
│   ├── xhs/                        # 核心自动化包
│   │   ├── cdp.py                  # CDP WebSocket 客户端
│   │   ├── stealth.py              # 反检测保护
│   │   ├── selectors.py            # CSS 选择器（集中管理，改版时只改此文件）
│   │   ├── login.py                # 登录 + 用户信息获取
│   │   ├── feeds.py                # 首页 Feed
│   │   ├── search.py               # 搜索 + 筛选
│   │   ├── feed_detail.py          # 笔记详情 + 评论加载
│   │   ├── user_profile.py         # 用户主页
│   │   ├── comment.py              # 评论、回复
│   │   ├── like_favorite.py        # 点赞、收藏
│   │   ├── publish.py              # 图文发布
│   │   ├── publish_video.py        # 视频发布
│   │   ├── publish_long_article.py # 长文发布
│   │   ├── types.py                # 数据类型
│   │   ├── errors.py               # 异常体系
│   │   ├── urls.py                 # URL 常量
│   │   ├── cookies.py              # Cookie 持久化
│   │   └── human.py                # 人类行为模拟
│   ├── cli.py                      # 统一 CLI 入口（20 个子命令）
│   ├── chrome_launcher.py          # Chrome 进程管理
│   ├── account_manager.py          # 多账号管理
│   ├── image_downloader.py         # 媒体下载（SHA256 缓存）
│   ├── title_utils.py              # UTF-16 标题长度计算
│   ├── run_lock.py                 # 单实例锁
│   └── publish_pipeline.py         # 发布编排器
├── skills/                         # Claude Code Skills 定义
│   ├── xhs-auth/SKILL.md
│   ├── xhs-publish/SKILL.md
│   ├── xhs-explore/SKILL.md
│   ├── xhs-interact/SKILL.md
│   └── xhs-content-ops/SKILL.md
├── SKILL.md                        # 技能统一入口（路由到子技能）
├── CLAUDE.md                       # 项目开发指南
├── pyproject.toml                  # uv 项目配置
└── README.md
```

## 技术架构

### 双层设计

```
用户 ──→ AI Agent ──→ SKILL.md（意图路由）──→ CLI ──→ CDP 引擎 ──→ Chrome ──→ 小红书
```

1. **Skills 层**（`skills/` + `SKILL.md`）— AI Agent 的能力定义，描述何时触发、如何调用、如何处理失败。Agent 读取 SKILL.md 后自动获得小红书操作能力。

2. **引擎层**（`scripts/`）— Python CDP 自动化引擎，通过 Chrome DevTools Protocol 直接控制浏览器。内置反检测保护、人类行为模拟、JSON 结构化输出。

### 关键设计

- **数据提取**：通过 `window.__INITIAL_STATE__` 读取页面数据，与小红书前端框架对齐
- **反检测**：Stealth JS 注入 + CDP 真实输入事件（`isTrusted=true`）+ 随机延迟
- **选择器集中管理**：所有 CSS 选择器在 `xhs/selectors.py` 统一维护，小红书改版时只需改一个文件
- **分步发布**：fill → 预览 → confirm 三步流程，确保用户始终掌控发布内容

## 开发

```bash
uv sync                    # 安装依赖
uv run ruff check .        # Lint 检查
uv run ruff format .       # 代码格式化
uv run pytest              # 运行测试
```

## License

MIT

## Trend

## Star History

[![Star History Chart](https://api.star-history.com/image?repos=autoclaw-cc/xiaohongshu-skills&type=date&legend=top-left)](https://www.star-history.com/?repos=autoclaw-cc%2Fxiaohongshu-skills&type=date&legend=top-left)
