---
name: google-drive-integration
description: "Google Drive 集成技能，用于在 DeerFlow 中访问、创建、更新和管理 Google Drive 文件和文件夹。当用户提到 Google Drive、云盘文件、文档存储、文件列表、文件读取、文件上传或任何与 Google Drive 相关的操作时，使用此技能。"
compatibility: "需要 google-api-python-client, google-auth-httplib2, google-auth-oauthlib"
---

# Google Drive 集成技能

此技能为 DeerFlow 提供完整的 Google Drive 集成能力，包括文件列表、读取、创建、更新、搜索等功能。

## 架构

```
google-drive-integration/
├── SKILL.md
├── scripts/
│   ├── auth_setup.py          - 认证设置工具
│   ├── list_files.py          - 列出文件和文件夹
│   ├── read_file.py           - 读取文件内容
│   ├── create_file.py         - 创建文件
│   ├── update_file.py         - 更新文件
│   ├── search_files.py        - 搜索文件
│   └── utils.py               - 通用工具函数
├── references/
│   ├── api_guide.md           - API 详细指南
│   ├── authentication.md      - 认证配置指南
│   └── examples.md            - 使用示例
├── assets/
│   └── credentials.example.json - 凭证示例
└── evals/
    └── evals.json             - 评估测试用例
```

## 核心指令

### 1. 初始设置

在使用 Google Drive 技能之前，需要完成以下设置：

1. **Google Cloud 项目设置**
   - 访问 [Google Cloud Console](https://console.cloud.google.com/)
   - 创建新项目或选择现有项目
   - 启用 Google Drive API
   - 创建 OAuth 2.0 凭证（桌面应用类型）
   - 下载 credentials.json 并保存到安全位置

2. **安装依赖**
   ```bash
   pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
   ```

3. **首次认证**
   - 运行认证设置脚本完成 OAuth 流程
   - 这将生成 token.json 用于后续访问

### 2. 主要功能

#### 列出文件和文件夹
- 支持按文件夹筛选
- 支持分页和限制结果数量
- 返回文件元数据（名称、ID、类型、修改时间等）

#### 读取文件
- 支持多种文件格式（文档、表格、图片等）
- Google Docs/Sheets/Slides 自动转换为可读格式
- 支持下载原始文件

#### 创建文件
- 支持上传本地文件
- 支持创建新的 Google Docs/Sheets/Slides
- 支持指定文件夹位置

#### 更新文件
- 支持更新文件内容
- 支持重命名和移动文件
- 支持修改文件权限

#### 搜索文件
- 支持按名称、类型、修改时间搜索
- 支持全文搜索（适用于 Google 文档）
- 支持复杂查询条件

## 使用模式

### 常见使用场景

**场景 1: 列出最近的文件**
```
用户: "列出我 Google Drive 中最近修改的 10 个文件"
执行: 使用 list_files.py，按修改时间排序，限制 10 个结果
```

**场景 2: 读取文档内容**
```
用户: "读取我的 '项目计划' 文档"
执行: 先搜索文件，然后使用 read_file.py 获取内容
```

**场景 3: 创建新文档**
```
用户: "在我的 '工作' 文件夹中创建一个新的 Google 文档，标题为'会议记录'"
执行: 使用 create_file.py，指定文件夹和文档类型
```

**场景 4: 搜索文件**
```
用户: "搜索包含 '预算' 关键词的所有表格文件"
执行: 使用 search_files.py，指定文件类型和关键词
```

### 工作流程

1. **确定用户意图** - 理解用户想要执行的 Google Drive 操作
2. **检查认证状态** - 确认用户已完成 OAuth 认证
3. **选择合适的脚本** - 根据操作类型选择相应的脚本
4. **执行操作** - 调用脚本执行具体的 Google Drive API 操作
5. **返回结果** - 以友好的格式向用户展示结果

## 参考资源

- `references/api_guide.md` - 完整的 API 参考文档
- `references/authentication.md` - 详细的认证配置指南
- `references/examples.md` - 更多使用示例和代码片段

## 安全注意事项

1. **凭证安全** - 永远不要将 credentials.json 和 token.json 提交到版本控制
2. **权限范围** - 只请求必要的权限范围，避免过度授权
3. **用户确认** - 在执行修改或删除操作前，要求用户确认
4. **错误处理** - 妥善处理 API 错误，避免暴露敏感信息

## 故障排除

如果遇到问题，请检查：
1. Google Cloud 项目中 Drive API 是否已启用
2. OAuth 凭证是否正确配置
3. token.json 是否存在且有效
4. 网络连接是否正常
5. 依赖包是否正确安装

更多故障排除信息请参考 `references/api_guide.md`。
