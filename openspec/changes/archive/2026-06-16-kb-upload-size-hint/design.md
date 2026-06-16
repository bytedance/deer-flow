## Context

知识库文档上传入口在 `kb-documents-dialog.tsx` 的 `AddDocumentForm` 组件中。当前用户选择文件后，前端不做任何预处理校验，直接将文件通过 `FormData` POST 到 `/api/knowledge-bases/{kbId}/documents/upload`。后端有 20MB 限制（`_UPLOAD_MAX_SIZE`）和格式限制（`_ALLOWED_EXTENSIONS = {.pdf,.doc,.docx,.md,.txt}`），超限返回 413/422。`<input accept>` 属性只在系统文件对话框中起过滤作用，用户可以绕过。

i18n 已有 `uploadFilePlaceholder` 包含 "最大 20 MB" 文案，但仅在空状态（未选文件时）显示，选择文件后被文件名覆盖，用户无法再次看到限制提示。

## Goals / Non-Goals

**Goals:**
- 选择文件后提交时检查文件大小（> 20 MB toast 报错并阻止上传）
- 选择文件后提交时检查文件扩展名（不在允许列表 toast 报错并阻止上传）
- 上传区域始终可见 "最大 20 MB" 提示
- 中英文提示文案完整
- 带测试覆盖

**Non-Goals:**
- 不修改后端上传限制值
- 不添加后端 API 动态返回文件大小上限
- 不修改其他上传入口（如 thread uploads）—— 它们已有各自的处理

## Decisions

1. **常量定义位置**: 在 `api.ts` 顶部导出 `KB_UPLOAD_MAX_SIZE` 和 `KB_ALLOWED_EXTENSIONS`，与后端 `_UPLOAD_MAX_SIZE` / `_ALLOWED_EXTENSIONS` 保持同步。放在 api.ts 而非独立 constants.ts，因为这个常量只被 api.ts 和 kb-documents-dialog.tsx 两个文件引用，不值得新建文件。

2. **校验时机**: 在 `handleFileSubmit` 开头做校验，toast 错误后直接 return。不在 `onChange` 里校验，避免用户选择文件时立刻弹 toast 打断操作。

3. **文件类型校验同时做**: `accept` 属性无法阻止用户绕过（拖拽、选"所有文件"），与大小校验是同一类 UX 问题。边际改动很小（约 5 行代码 + 1 个 i18n key），本次一起覆盖。扩展名提取方式：`"." + file.name.split(".").pop()?.toLowerCase()`，与后端 `Path(filename).suffix.lower()` 语义一致。`KB_ALLOWED_EXTENSIONS` 使用 `Set` 且值带点前缀（`".pdf"` 而非 `"pdf"`），直接 O(1) 查找。

4. **校验失败后清除文件状态**: 客户端校验失败（大小或格式）后，除 toast 报错外，同时 `setFile(null)` 清除文件状态，让上传区域回到空状态。网络错误（catch 块）不清除，用户可以重试。这两个场景的用户出口不同。

5. **i18n key 设计**: 新增三个 key：
   - `uploadFileSizeHint`: "最大 20 MB" — upload 区域始终可见的静态提示
   - `uploadFileTooLarge`: "文件过大（{size}MB），最大支持 20 MB" — 超限 toast
   - `uploadFileUnsupportedType`: "不支持的文件格式：{name}（支持 PDF、DOCX、Markdown、TXT）" — 格式错误 toast

6. **20MB / 扩展名硬编码**: 前后端均硬编码，当前规模下不需要后端 API 动态返回。如有需要后续可添加 `GET /api/knowledge-bases/upload-limits` 端点。

## Risks / Trade-offs

- 前后端限制值需手动保持同步 → 在 `api.ts` 中定义单一常量，修改时只需改一处
- 其他上传入口（thread uploads）未同步加校验 → 非本次 scope，记录为已知 gap
