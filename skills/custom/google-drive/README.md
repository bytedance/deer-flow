# Google Drive 集成技能

DeerFlow 的 Google Drive 集成技能，提供与 Google Drive 云存储的完整交互能力。

## 功能特性

- ✅ **认证管理**: OAuth 2.0 安全认证
- ✅ **文件浏览**: 列出文件和文件夹，支持分页和排序
- ✅ **文件读取**: 读取文本文件、Google Docs、Sheets、Slides
- ✅ **文件创建**: 创建文件夹、Google 文档、上传本地文件
- ✅ **文件更新**: 重命名、移动、更新文件内容
- ✅ **文件搜索**: 强大的搜索功能，支持多种过滤条件
- ✅ **LangGraph 集成**: 可作为 LangGraph 节点使用

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 获取 Google Cloud 凭证

1. 访问 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建新项目或选择现有项目
3. 搜索并启用 "Google Drive API"
4. 前往 "API 和服务" > "凭据"
5. 点击 "创建凭据" > "OAuth 客户端 ID"
6. 选择应用类型为 "桌面应用"
7. 输入名称并点击 "创建"
8. 下载 JSON 凭证文件并保存为 `credentials.json`

### 3. 完成认证

```bash
cd scripts
python auth_setup.py
```

按照提示在浏览器中完成授权。

## 使用方法

### 列出文件

```bash
# 列出根目录文件
python list_files.py

# 列出特定文件夹
python list_files.py --folder-id <文件夹ID>

# 只列出文件夹
python list_files.py --folders-only
```

### 读取文件

```bash
# 通过文件 ID 读取
python read_file.py --file-id <文件ID>

# 通过文件名读取（会搜索）
python read_file.py --file-name "报告.docx"

# 下载到本地
python read_file.py --file-id <文件ID> --download local_file.txt

# 只预览前 500 字符
python read_file.py --file-id <文件ID> --preview
```

### 创建文件

```bash
# 创建文件夹
python create_file.py folder "我的文件夹"

# 创建 Google 文档
python create_file.py doc doc "会议记录"
python create_file.py doc sheet "数据表格"
python create_file.py doc slide "演示文稿"

# 上传本地文件
python create_file.py upload /path/to/local/file.pdf --name "上传的文件.pdf"
```

### 更新文件

```bash
# 重命名
python update_file.py <文件ID> rename "新名称.txt"

# 移动到其他文件夹
python update_file.py <文件ID> move <目标文件夹ID>

# 更新文件内容
python update_file.py <文件ID> content /path/to/new/content.txt
```

### 搜索文件

```bash
# 全文搜索
python search_files.py --query "项目报告"

# 按类型搜索
python search_files.py --type pdf

# 按文件名搜索
python search_files.py --name "合同"

# 组合条件
python search_files.py --type doc --modified-after "2024-01-01T00:00:00"
```

## 集成到 DeerFlow

### 作为技能使用

将此技能目录放置在 DeerFlow 的 `skills/` 目录下，然后重新启动 DeerFlow。

### LangGraph 节点示例

```python
from langgraph.graph import StateGraph
from scripts.utils import get_credentials, build_drive_service

def google_drive_node(state):
    """Google Drive 集成节点"""
    creds = get_credentials()
    service = build_drive_service(creds)
    
    # 执行操作...
    return {"drive_result": result}
```

## 目录结构

```
google-drive-integration/
├── SKILL.md              # 技能定义
├── README.md             # 本文档
├── requirements.txt      # 依赖文件
├── scripts/              # 脚本目录
│   ├── utils.py          # 通用工具函数
│   ├── auth_setup.py     # 认证设置工具
│   ├── list_files.py     # 列出文件
│   ├── read_file.py      # 读取文件
│   ├── create_file.py    # 创建文件
│   ├── update_file.py    # 更新文件
│   └── search_files.py   # 搜索文件
├── references/           # 参考文档
├── assets/               # 资源文件
└── evals/                # 评估测试
```

## 安全注意事项

1. **凭证安全**: 切勿将 `credentials.json` 和 `token.json` 提交到版本控制系统
2. **权限范围**: 只请求必要的 API 权限
3. **Token 刷新**: Token 会自动刷新，无需重复认证
4. **错误处理**: 所有脚本都包含基本的错误处理

## 许可证

MIT License - 与 openclaw-lark 相同的许可证

## 参考

- [Google Drive API 文档](https://developers.google.com/drive/api)
- [openclaw-lark GitHub](https://github.com/larksuite/openclaw-lark)
- [DeerFlow 文档](https://deer-flow.dev/docs)
