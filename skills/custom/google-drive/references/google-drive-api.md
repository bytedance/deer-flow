# Google Drive API 参考

## 认证范围

| 范围 | 描述 |
|------|------|
| `https://www.googleapis.com/auth/drive` | 完全访问权限 |
| `https://www.googleapis.com/auth/drive.file` | 仅访问由应用创建或打开的文件 |
| `https://www.googleapis.com/auth/drive.readonly` | 只读访问 |
| `https://www.googleapis.com/auth/drive.metadata.readonly` | 仅元数据只读 |

当前实现会请求 `drive`、`drive.file` 和 `drive.readonly` 范围。
如需遵循最小权限原则，推荐优先使用 `drive.file`，因为它是更安全的最低权限选择。

## MIME 类型

### Google Workspace 类型

| 类型 | MIME 类型 |
|------|-----------|
| 文档 | `application/vnd.google-apps.document` |
| 表格 | `application/vnd.google-apps.spreadsheet` |
| 演示文稿 | `application/vnd.google-apps.presentation` |
| 文件夹 | `application/vnd.google-apps.folder` |
| 绘图 | `application/vnd.google-apps.drawing` |
| 表单 | `application/vnd.google-apps.form` |

### 常见文件类型

| 扩展名 | MIME 类型 |
|--------|-----------|
| .pdf | `application/pdf` |
| .txt | `text/plain` |
| .html | `text/html` |
| .jpg/.jpeg | `image/jpeg` |
| .png | `image/png` |
| .doc | `application/msword` |
| .docx | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| .xls | `application/vnd.ms-excel` |
| .xlsx | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

## API 常用操作

### 文件操作

#### 列出文件
```python
service.files().list(
    q="trashed = false",
    pageSize=10,
    fields="files(id, name, mimeType)"
).execute()
```

#### 获取文件
```python
service.files().get(fileId=file_id).execute()
```

#### 创建文件
```python
file_metadata = {'name': '文件名'}
media = MediaFileUpload('file.pdf', mimetype='application/pdf')
service.files().create(body=file_metadata, media_body=media).execute()
```

#### 更新文件
```python
service.files().update(fileId=file_id, body=metadata).execute()
```

#### 删除文件
```python
service.files().delete(fileId=file_id).execute()
```

### 搜索查询语法

| 操作 | 示例 |
|------|------|
| 文件名包含 | `name contains '报告'` |
| 全文搜索 | `fullText contains '关键词'` |
| 文件夹内 | `'folder_id' in parents` |
| MIME 类型 | `mimeType = 'application/pdf'` |
| 修改时间 | `modifiedTime > '2024-01-01T00:00:00'` |
| 已删除 | `trashed = true` |

## 参考链接

- [官方 API 文档](https://developers.google.com/drive/api/v3/reference)
- [Python 快速开始](https://developers.google.com/drive/api/v3/quickstart/python)
- [查询语法参考](https://developers.google.com/drive/api/v3/search-files)
