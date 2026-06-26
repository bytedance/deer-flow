## 1. 实现

- [x] 1.1 为 DeerFlow 前端新增宿主 `AI_TOKEN_REFRESH` 消息监听与 origin 校验
- [x] 1.2 收到新 token 后更新 `ehm_token` / `ehm_user`
- [x] 1.3 收到新 token 后主动调用 `/api/v1/auth/ins-base/authenticate` 重建 session
- [x] 1.4 抽取或复用共享桥接逻辑，避免 token 刷新处理散落在单页面代码中
- [x] 1.5 更新文档，明确 EHM iframe 长驻场景下的 token 重同步协议
- [x] 1.6 在 `401` 时先向宿主请求最新 token，再决定是否跳登录
- [x] 1.7 将宿主桥接提升到根布局，覆盖登录页恢复场景
- [x] 1.8 让登录页在 iframe 场景下主动再次请求宿主 token，并在恢复成功后自动回跳
- [x] 1.9 放宽宿主 token 请求超时并补充链路日志

## 2. 验证

- [x] 2.1 代码检查旧消息不会覆盖较新的 token
- [x] 2.2 验证同步新 token 后，前端无需 reload 即可继续维持 DeerFlow session
- [x] 2.3 验证同步失败时仍保留既有 401 恢复链路
- [x] 2.4 验证登录页也能接收宿主 `AI_TOKEN_REFRESH` 恢复会话
- [x] 2.5 验证登录页会在前一次请求超时后再次向宿主请求新 token
- [x] 2.6 验证宿主 refresh 耗时超过 1.5 秒时不会过早跳过恢复
