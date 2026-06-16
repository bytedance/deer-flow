## Why

用户上传知识库文档时，前端缺少可见的文件大小限制提示（20 MB）和客户端预校验（大小和格式），导致用户选择超大或错误格式的文件后只能等到上传失败才知道超限，体验差。虽然后端有 `_UPLOAD_MAX_SIZE = 20 * 1024 * 1024` 和 `_ALLOWED_EXTENSIONS` 限制且 nginx 已修复，但前端应在用户提交时立即给出友好反馈。

## What Changes

- 文件上传前进行客户端大小校验（> 20 MB 时 toast 错误并阻止上传）
- 文件上传前进行客户端格式校验（不在允许列表时 toast 错误并阻止上传）
- 上传区域始终显示 "最大 20 MB" 的静态提示文字
- 新增 i18n key `uploadFileSizeHint`、`uploadFileTooLarge`、`uploadFileUnsupportedType`，中英文双语

## Capabilities

### New Capabilities
- `kb-upload-client-validation`: 知识库文档上传前端客户端校验，包括文件大小和格式预检，以及始终可见的限制提示

### Modified Capabilities
<!-- None -->

## Impact

- [frontend/src/core/knowledge-base/api.ts](frontend/src/core/knowledge-base/api.ts): 导出 `KB_UPLOAD_MAX_SIZE` 和 `KB_ALLOWED_EXTENSIONS` 常量
- [frontend/src/components/workspace/knowledge-bases/kb-documents-dialog.tsx](frontend/src/components/workspace/knowledge-bases/kb-documents-dialog.tsx): AddDocumentForm 组件增加文件大小和格式校验、静态提示
- [frontend/src/core/i18n/locales/types.ts](frontend/src/core/i18n/locales/types.ts): 类型定义新增字段
- [frontend/src/core/i18n/locales/zh-CN.ts](frontend/src/core/i18n/locales/zh-CN.ts): 新增中文翻译 key
- [frontend/src/core/i18n/locales/en-US.ts](frontend/src/core/i18n/locales/en-US.ts): 新增英文翻译 key
- [frontend/tests/unit/core/knowledge-base/](frontend/tests/unit/core/knowledge-base/): 新增校验逻辑单元测试
- [frontend/tests/unit/components/knowledge-bases/](frontend/tests/unit/components/knowledge-bases/): 新增组件交互测试
