# Google Drive 集成 - 快速开始指南

## 5 分钟快速开始

### 步骤 1: 安装依赖 (1 分钟)

```bash
cd skills/custom/google-drive
pip install -r requirements.txt
```

### 步骤 2: 获取 Google Cloud 凭证 (2 分钟)

1. 访问 https://console.cloud.google.com/
2. 搜索 "Google Drive API" 并启用
3. 创建 "OAuth 客户端 ID" (桌面应用类型)
4. 下载 JSON 文件，重命名为 `credentials.json` 并放在项目根目录

### 步骤 3: 完成认证 (1 分钟)

```bash
python scripts/auth_setup.py
```

浏览器会自动打开，完成授权即可。

### 步骤 4: 测试一下！(1 分钟)

```bash
# 列出你的文件
python list_files.py

# 搜索文件
python search_files.py --query "我的文档"
```

## 常用命令速查

| 操作 | 命令 |
|------|------|
| 列出文件 | `python list_files.py` |
| 搜索文件 | `python search_files.py --query "关键词"` |
| 读取文件 | `python read_file.py --file-id <文件ID>` |
| 创建文件夹 | `python create_file.py folder "文件夹名"` |
| 上传文件 | `python create_file.py upload /path/to/file.pdf` |

## 下一步

- 查看完整文档: [README.md](README.md)
- API 参考: [references/google-drive-api.md](references/google-drive-api.md)
- LangGraph 集成: [assets/langgraph_integration_example.py](assets/langgraph_integration_example.py)

## 遇到问题？

1. 确保 `credentials.json` 在正确位置
2. 确保已运行 `auth_setup.py` 完成认证
3. 查看错误信息，检查 Google Cloud Console 中 API 是否已启用
