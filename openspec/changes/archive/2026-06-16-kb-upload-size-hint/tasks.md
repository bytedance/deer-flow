## 1. i18n 文案

- [x] 1.1 在 `types.ts` 中新增 `uploadFileSizeHint`、`uploadFileTooLarge`、`uploadFileUnsupportedType` 类型定义
- [x] 1.2 在 `zh-CN.ts` 中新增 `uploadFileSizeHint: "最大 20 MB"`、`uploadFileTooLarge: "文件过大（{size}MB），最大支持 20 MB"`、`uploadFileUnsupportedType: "不支持的文件格式：{name}（支持 PDF、DOCX、Markdown、TXT）"`
- [x] 1.3 在 `en-US.ts` 中新增 `uploadFileSizeHint: "Max 20 MB"`、`uploadFileTooLarge: "File too large ({size}MB), max 20 MB"`、`uploadFileUnsupportedType: "Unsupported file type: {name} (PDF, DOCX, Markdown, TXT supported)"`

## 2. 上传校验常量

- [x] 2.1 在 `api.ts` 中导出 `KB_UPLOAD_MAX_SIZE = 20 * 1024 * 1024` 和 `KB_ALLOWED_EXTENSIONS = new Set([".pdf", ".doc", ".docx", ".md", ".txt"])`（带点前缀，与后端 `Path.suffix` 格式一致）

## 3. UI 组件修改

- [x] 3.1 在 `AddDocumentForm` 的 file upload 区域添加 `uploadFileSizeHint` 静态提示文字（始终可见，与选中的文件名并列）
- [x] 3.2 在 `handleFileSubmit` 开头添加文件扩展名校验：取 `"." + file.name.split(".").pop()?.toLowerCase()`，`KB_ALLOWED_EXTENSIONS.has(ext)` 为 false 时 toast `t.knowledgeBase.uploadFileUnsupportedType.replace("{name}", file.name)` 并 `setFile(null)` return
- [x] 3.3 在扩展名校验通过后添加文件大小校验：`file.size > KB_UPLOAD_MAX_SIZE` 时 toast `t.knowledgeBase.uploadFileTooLarge.replace("{size}", String(Math.round(file.size / 1024 / 1024)))` 并 `setFile(null)` return

## 4. 测试

- [x] 4.1 在 `tests/unit/core/knowledge-base/api.test.ts` 中新增测试：验证 `KB_UPLOAD_MAX_SIZE === 20 * 1024 * 1024`，`KB_ALLOWED_EXTENSIONS` 包含 `.pdf/.doc/.docx/.md/.txt` 且值带点前缀，`validateUploadFile` 覆盖合法文件、不支持格式、超大文件、无扩展名、大写扩展名、多点文件名、格式优先于大小
- [x] 4.2 类型检查通过（`pnpm typecheck` 零错误），验证 i18n key 存在且 `uploadFileSizeHint` 在 UI 中引用正确
