# xiaohongshu-skills

小红书自动化 Claude Code Skills，基于 Python CDP 浏览器自动化引擎。

## Git 工作流

- 所有代码修改必须在分支上进行，禁止直接推送 main 分支
- 分支开发完成后通过 PR 合入 main

## 开发命令

```bash
uv sync                    # 安装依赖
uv run ruff check .        # Lint 检查
uv run ruff format .       # 代码格式化
uv run pytest              # 运行测试
```

## 架构

双层结构：`scripts/` 是 Python CDP 自动化引擎，`skills/` 是 Claude Code Skills 定义（SKILL.md 格式）。

- `scripts/xhs/` — 核心自动化库（模块化，每个功能一个文件）
- `scripts/cli.py` — 统一 CLI 入口，23 个子命令，JSON 结构化输出
- `scripts/publish_pipeline.py` — 发布编排器（含图片下载和登录检查）
- `skills/*/SKILL.md` — 指导 Claude 如何调用 scripts/

### 调用方式

```bash
python scripts/cli.py check-login
python scripts/cli.py search-feeds --keyword "关键词"
python scripts/cli.py publish --title-file t.txt --content-file c.txt --images pic.jpg
python scripts/publish_pipeline.py --title-file t.txt --content-file c.txt --images URL1
```

## 代码规范

- 行长度上限 100 字符
- 完整 type hints，使用 `from __future__ import annotations`
- 异常继承 `XHSError`（`xhs/errors.py`）
- CLI exit code：0=成功，1=未登录，2=错误
- 用户可见错误信息使用中文
- JSON 输出 `ensure_ascii=False`

### 安全约束

- 发布类操作必须有用户确认机制
- 文件路径必须使用绝对路径
- 敏感内容通过文件传递，不内联到命令行参数
- Chrome Profile 目录隔离账号 cookies

## CLI 子命令对照表

| CLI 子命令 | 对应 MCP 工具 | 分类 |
|--|--|--|
| `check-login` | check_login_status | 认证 |
| `login` | get_login_qrcode | 认证 |
| `phone-login` | — | 认证 |
| `delete-cookies` | delete_cookies | 认证 |
| `list-feeds` | list_feeds | 浏览 |
| `search-feeds` | search_feeds | 浏览 |
| `get-feed-detail` | get_feed_detail | 浏览 |
| `user-profile` | user_profile | 浏览 |
| `post-comment` | post_comment_to_feed | 互动 |
| `reply-comment` | reply_comment_in_feed | 互动 |
| `like-feed` | like_feed | 互动 |
| `favorite-feed` | favorite_feed | 互动 |
| `publish` | publish_content | 发布 |
| `publish-video` | publish_with_video | 发布 |
| `fill-publish` | — | 分步发布（图文填写） |
| `fill-publish-video` | — | 分步发布（视频填写） |
| `click-publish` | — | 分步发布（点击发布） |
| `long-article` | — | 长文发布（填写+排版） |
| `select-template` | — | 长文发布（选择模板） |
| `next-step` | — | 长文发布（下一步+描述） |
| `add-account` | — | 账号管理（添加，自动分配端口） |
| `list-accounts` | — | 账号管理（列出所有） |
| `remove-account` | — | 账号管理（删除） |
| `set-default-account` | — | 账号管理（设置默认） |
