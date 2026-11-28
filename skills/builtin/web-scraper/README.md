# Web Scraper Skill for DeerFlow

一个用于 DeerFlow AI Agent 框架的智能网页抓取技能，支持从网页中提取结构化内容。

## 功能特性

- ✅ 提取网页标题、描述、正文内容
- ✅ 自动清理 HTML 标签和无关内容
- ✅ 提取图片列表（含 alt 文本）
- ✅ 提取重要链接
- ✅ 解析元数据（作者、发布日期、关键词）
- ✅ 处理相对 URL 转绝对 URL
- ✅ 支持重定向跟踪
- ✅ 友好的错误处理

## 安装

### 1. 将此技能复制到 DeerFlow skills 目录

```bash
# 克隆或下载此项目
cd /path/to/deer-flow

# 复制到 custom skills 目录
cp -r /path/to/web-scraper-skill skills/custom/web-scraper
```

### 2. 安装 Python 依赖

```bash
pip install requests beautifulsoup4 lxml html2text
```

## 使用方法

### 在 DeerFlow 中使用

当你向 DeerFlow Agent 发起请求时，它会自动加载此技能：

**示例对话：**

```
用户: "请帮我抓取 https://example.com/article 这篇文章的内容"

Agent: [自动调用 web-scraper skill]
       正在抓取网页...
       ✓ 成功提取内容：
       - 标题: Example Article Title
       - 正文: 1234 字
       - 图片: 5 张
       - 链接: 12 个
```

### 直接运行脚本

你也可以独立运行抓取脚本：

```bash
cd scripts
python scrape.py --url "https://example.com" --output "../output/result.json"
```

**参数说明：**
- `--url`: 要抓取的网页 URL（必需）
- `--output`: 输出 JSON 文件路径（必需）
- `--timeout`: 请求超时时间（秒，默认 30）

## 输出格式

```json
{
  "url": "https://example.com/article",
  "scraped_at": "2026-10-18T10:30:00Z",
  "status": "success",
  "status_code": 200,
  "data": {
    "title": "文章标题",
    "description": "文章描述...",
    "body": "清理后的正文内容（Markdown 格式）...",
    "images": [
      {
        "url": "https://example.com/image.jpg",
        "alt": "图片描述"
      }
    ],
    "links": [
      {
        "text": "相关文章",
        "url": "https://example.com/related"
      }
    ],
    "metadata": {
      "author": "作者名",
      "publish_date": "2026-10-15",
      "keywords": ["关键词1", "关键词2"]
    }
  }
}
```

## 使用场景

### 1. 研究和信息收集
```
"帮我收集这5篇AI论文的摘要信息"
```

### 2. 内容分析
```
"分析这个新闻网站的最新文章内容"
```

### 3. 数据提取
```
"从这个产品页面提取产品名称、价格和描述"
```

### 4. 监控网页变化
```
"检查这个文档页面是否有更新"
```

## 最佳实践

1. **遵守 robots.txt**：脚本会尊重网站的爬虫规则
2. **合理限速**：避免频繁请求同一网站（建议间隔 1-2 秒）
3. **检查使用条款**：抓取前确认网站是否允许
4. **优先使用 API**：如果网站提供官方 API，优先使用而非抓取

## 限制说明

- ❌ 无法抓取需要登录的内容（除非提供凭证）
- ❌ 可能被反爬虫机制阻止
- ❌ JavaScript 重度渲染的页面需要额外工具（如 Playwright）
- ⚠️ 部分网站可能屏蔽自动化访问

## 技术栈

- **Python 3.7+**
- **requests** - HTTP 请求库
- **BeautifulSoup4** - HTML 解析
- **lxml** - XML/HTML 解析器
- **html2text** - HTML 转 Markdown

## 贡献

欢迎提交 Issue 和 Pull Request！

### 开发计划

- [ ] 添加 JavaScript 渲染支持（Playwright）
- [ ] 支持批量 URL 抓取
- [ ] 添加缓存机制
- [ ] 支持更多内容提取策略
- [ ] 添加代理支持

## License

MIT License

## 作者

**LJK-ikun** - [GitHub](https://github.com/LJK-ikun)

为 [DeerFlow](https://github.com/bytedance/deer-flow) 贡献的开源技能。

---

## Changelog

### v1.0.0 (2026-10-18)
- ✨ 初始版本发布
- ✅ 支持基础网页抓取
- ✅ 结构化内容提取
- ✅ 错误处理机制
