# 文件路径使用示例

## 三种路径类型

DeerFlow 的文件上传系统返回三种不同的路径，每种路径用于不同的场景：

### 1. 实际文件系统路径 (path)

```
{DEER_FLOW_HOME}/users/{user_id}/threads/{thread_id}/user-data/uploads/document.pdf
```

API 返回的是**绝对路径**，且上传文件按用户分桶。`{DEER_FLOW_HOME}` 表示实际的运行时数据根目录：优先使用 `DEER_FLOW_HOME`；未设置时使用 `DEER_FLOW_PROJECT_ROOT/.deer-flow/`；两个环境变量都未设置时，才使用当前启动目录下的 `.deer-flow/`。

**用途：**
- 文件在服务器文件系统中的实际位置
- 用于直接文件系统访问、备份、调试等

**示例：**
```python
# Python 代码中直接访问：解析当前用户上传桶，不要手写路径
from deerflow.uploads.manager import get_uploads_dir

file_path = get_uploads_dir("abc123") / "document.pdf"
content = file_path.read_bytes()
```

### 2. 虚拟路径 (virtual_path)

```
/mnt/user-data/uploads/document.pdf
```

**用途：**
- Agent 在沙箱环境中使用的路径
- 沙箱系统会自动映射到实际路径
- Agent 的所有文件操作工具都使用这个路径

**示例：**
Agent 在对话中使用：
```python
# Agent 使用 read_file 工具
read_file(path="/mnt/user-data/uploads/document.pdf")

# Agent 使用 bash 工具
bash(command="cat /mnt/user-data/uploads/document.pdf")
```

### 3. HTTP 访问 URL (artifact_url)

```
/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf
```

**用途：**
- 前端通过 HTTP 访问文件
- 用于下载、预览文件
- 可以直接在浏览器中打开

**示例：**
```typescript
// 前端 TypeScript/JavaScript 代码
const threadId = 'abc123';
const filename = 'document.pdf';

// 下载文件
const downloadUrl = `/api/threads/${threadId}/artifacts/mnt/user-data/uploads/${filename}?download=true`;
window.open(downloadUrl);

// 在新窗口预览
const viewUrl = `/api/threads/${threadId}/artifacts/mnt/user-data/uploads/${filename}`;
window.open(viewUrl, '_blank');

// 使用 fetch API 获取
const response = await fetch(viewUrl);
const blob = await response.blob();
```

## 完整使用流程示例

### 场景：前端上传文件并让 Agent 处理

```typescript
// 1. 前端上传文件
async function uploadAndProcess(threadId: string, file: File) {
  // 上传文件
  const formData = new FormData();
  formData.append('files', file);

  const uploadResponse = await fetch(
    `/api/threads/${threadId}/uploads`,
    {
      method: 'POST',
      body: formData
    }
  );

  const uploadData = await uploadResponse.json();
  const fileInfo = uploadData.files[0];

  console.log('文件信息：', fileInfo);
  // {
  //   filename: "report.pdf",
  //   // path / markdown_path 是绝对路径；下面按默认数据目录 backend/.deer-flow 示例
  //   path: "/srv/deer-flow/backend/.deer-flow/users/default/threads/abc123/user-data/uploads/report.pdf",
  //   virtual_path: "/mnt/user-data/uploads/report.pdf",
  //   artifact_url: "/api/threads/abc123/artifacts/mnt/user-data/uploads/report.pdf",
  //   markdown_file: "report.md",
  //   markdown_path: "/srv/deer-flow/backend/.deer-flow/users/default/threads/abc123/user-data/uploads/report.md",
  //   markdown_virtual_path: "/mnt/user-data/uploads/report.md",
  //   markdown_artifact_url: "/api/threads/abc123/artifacts/mnt/user-data/uploads/report.md"
  // }

  // 2. 发送消息给 Agent
  await sendMessage(threadId, "请分析刚上传的 PDF 文件");

  // Agent 会自动看到文件列表，包含：
  // - report.pdf (虚拟路径: /mnt/user-data/uploads/report.pdf)
  // - report.md (虚拟路径: /mnt/user-data/uploads/report.md)

  // 3. 前端可以直接访问转换后的 Markdown
  const mdResponse = await fetch(fileInfo.markdown_artifact_url);
  const markdownContent = await mdResponse.text();
  console.log('Markdown 内容：', markdownContent);

  // 4. 或者下载原始 PDF
  const downloadLink = document.createElement('a');
  downloadLink.href = fileInfo.artifact_url + '?download=true';
  downloadLink.download = fileInfo.filename;
  downloadLink.click();
}
```

## 路径转换表

| 场景 | 使用的路径类型 | 示例 |
|------|---------------|------|
| 服务器后端代码直接访问 | `path` | `{DEER_FLOW_HOME}/users/default/threads/abc123/user-data/uploads/file.pdf` |
| Agent 工具调用 | `virtual_path` | `/mnt/user-data/uploads/file.pdf` |
| 前端下载/预览 | `artifact_url` | `/api/threads/abc123/artifacts/mnt/user-data/uploads/file.pdf` |
| 备份脚本 | `path` | `{DEER_FLOW_HOME}/users/default/threads/abc123/user-data/uploads/file.pdf` |
| 日志记录 | `path` | `{DEER_FLOW_HOME}/users/default/threads/abc123/user-data/uploads/file.pdf` |

`path` 是绝对路径。上表中的 `{DEER_FLOW_HOME}` 优先取 `DEER_FLOW_HOME`；未设置时取 `DEER_FLOW_PROJECT_ROOT/.deer-flow/`；两个环境变量都未设置时，才取当前启动目录下的 `.deer-flow/`。其中的 `users/default/` 是上传所属用户，换用户时该段会变，所以后端代码请用 `get_uploads_dir(thread_id)` 解析，不要按上表拼字符串。

## 代码示例集合

### Python - 后端处理

```python
from deerflow.uploads.manager import get_uploads_dir

def process_uploaded_file(thread_id: str, filename: str):
    # 使用实际路径：Gateway 的上传落在解析后用户的桶里，
    # 即 .deer-flow/users/{user_id}/threads/{thread_id}/user-data/uploads/
    base_dir = get_uploads_dir(thread_id)
    file_path = base_dir / filename

    # 直接读取
    with open(file_path, 'rb') as f:
        content = f.read()

    return content
```

### JavaScript - 前端访问

```javascript
// 列出已上传的文件
async function listUploadedFiles(threadId) {
  const response = await fetch(`/api/threads/${threadId}/uploads/list`);
  const data = await response.json();

  // 为每个文件创建下载链接
  data.files.forEach(file => {
    console.log(`文件: ${file.filename}`);
    console.log(`下载: ${file.artifact_url}?download=true`);
    console.log(`预览: ${file.artifact_url}`);

    // 如果是文档，还有 Markdown 版本
    if (file.markdown_artifact_url) {
      console.log(`Markdown: ${file.markdown_artifact_url}`);
    }
  });

  return data.files;
}

// 删除文件
async function deleteFile(threadId, filename) {
  const response = await fetch(
    `/api/threads/${threadId}/uploads/${filename}`,
    { method: 'DELETE' }
  );
  return response.json();
}
```

### React 组件示例

```tsx
import React, { useState, useEffect } from 'react';

interface UploadedFile {
  filename: string;
  size: number;
  path: string;
  virtual_path: string;
  artifact_url: string;
  extension: string;
  modified: number;
  markdown_artifact_url?: string;
}

function FileUploadList({ threadId }: { threadId: string }) {
  const [files, setFiles] = useState<UploadedFile[]>([]);

  useEffect(() => {
    fetchFiles();
  }, [threadId]);

  async function fetchFiles() {
    const response = await fetch(`/api/threads/${threadId}/uploads/list`);
    const data = await response.json();
    setFiles(data.files);
  }

  async function handleUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const fileList = event.target.files;
    if (!fileList) return;

    const formData = new FormData();
    Array.from(fileList).forEach(file => {
      formData.append('files', file);
    });

    await fetch(`/api/threads/${threadId}/uploads`, {
      method: 'POST',
      body: formData
    });

    fetchFiles(); // 刷新列表
  }

  async function handleDelete(filename: string) {
    await fetch(`/api/threads/${threadId}/uploads/${filename}`, {
      method: 'DELETE'
    });
    fetchFiles(); // 刷新列表
  }

  return (
    <div>
      <input type="file" multiple onChange={handleUpload} />

      <ul>
        {files.map(file => (
          <li key={file.filename}>
            <span>{file.filename}</span>
            <a href={file.artifact_url} target="_blank">预览</a>
            <a href={`${file.artifact_url}?download=true`}>下载</a>
            {file.markdown_artifact_url && (
              <a href={file.markdown_artifact_url} target="_blank">Markdown</a>
            )}
            <button onClick={() => handleDelete(file.filename)}>删除</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

## 注意事项

1. **路径安全性**
   - 实际路径（`path`）包含线程 ID，确保隔离
   - API 会验证路径，防止目录遍历攻击
   - 前端不应直接使用 `path`，而应使用 `artifact_url`

2. **Agent 使用**
   - Agent 只能看到和使用 `virtual_path`
   - 沙箱系统自动映射到实际路径
   - Agent 不需要知道实际的文件系统结构

3. **前端集成**
   - 始终使用 `artifact_url` 访问文件
   - 不要尝试直接访问文件系统路径
   - 使用 `?download=true` 参数强制下载

4. **Markdown 转换**
   - 转换成功时，会返回额外的 `markdown_*` 字段
   - 建议优先使用 Markdown 版本（更易处理）
   - 原始文件始终保留
