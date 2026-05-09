# Chat Audio Input Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在对话框中实现“可选择音频输入”的能力，让用户可以在文本输入、浏览器麦克风语音转文字、音频文件转写三种输入方式之间切换。

**Architecture:** 采用“两阶段方案”。P0 复用前端已存在但未接线的浏览器 `SpeechRecognition` 能力，实现实时语音转文字；P1 补充后端音频转写接口，支持上传音频文件并将其转为可编辑文本，再进入现有消息发送链路。

**Tech Stack:** Next.js / React、现有 `PromptInput` 组件体系、FastAPI Gateway、线程上传链路、可插拔 STT Provider（优先 OpenAI-compatible transcription API）。

---

## 0. 当前实现状态（2026-05-09）

当前仓库已经完成了 P0 和 P1 的主链路实现，设计文档需要按“现状说明”来理解，而不是纯待实现方案。

已完成：

- 对话框已支持 `文本输入 / 麦克风输入 / 音频文件输入` 三种输入方式切换。
- `PromptInputSpeechButton` 已接入受控输入链路，浏览器支持时可把识别结果直接写回输入框。
- 后端已新增独立 `audio_input` 配置域、转写 Provider 抽象，以及 `POST /api/threads/{thread_id}/audio/transcriptions` 接口。
- 前端已支持选择音频文件后自动转写，并把结果回填到可编辑文本框。
- 前后端已补充 `GET /api/audio/config`，前端会根据 `enabled / microphone_enabled / file_transcription_enabled` 动态展示可用输入方式。

当前实现与原始方案的差异：

- 音频文件转写默认使用 `attachOriginal: false`，也就是默认不把原始音频作为消息附件保留；但后端接口仍支持可选保留原音频。
- 前端当前没有单独暴露“发送时附带原始音频”的 UI 开关，这一项仍可作为后续增强。
- locale 目前按后端配置白名单收敛，默认覆盖 `zh-CN / en-US` 两类主路径。

已知限制：

- 浏览器麦克风能力仍依赖 `SpeechRecognition / webkitSpeechRecognition`，兼容性受浏览器实现影响。
- 真实转写质量与成本取决于配置的 STT Provider 与模型，不属于输入框本身保证范围。
- 当前验证以单元测试和类型检查为主，尚未补真实浏览器麦克风 E2E。

## 1. 背景

当前项目的对话框已经具备较强的多模态输入基础，但“音频输入”尚未形成完整产品能力：

- 对话框组件 `PromptInput` 已支持：
  - 文本输入
  - 附件选择
  - 拖拽上传
  - 粘贴文件
- 底层组件中其实已经定义了 `PromptInputSpeechButton`
  - 文件：`frontend/src/components/ai-elements/prompt-input.tsx`
  - 能力：调用浏览器 `SpeechRecognition / webkitSpeechRecognition`
  - 现状：尚未被 `frontend/src/components/workspace/input-box.tsx` 接入
- 发送链路已支持：
  - 将 `PromptInputFilePart` 还原为浏览器 `File`
  - 先上传文件，再把文件路径写入消息 `additional_kwargs`
  - 文件：`frontend/src/core/threads/hooks.ts`
- 后端上传链路已支持通用文件上传
  - 文件：`backend/app/gateway/routers/uploads.py`
  - 现状：只负责保存文件，不负责音频转写

这意味着：

1. “语音转文字”前端已有半成品。
2. “音频文件上传”基础设施已经存在。
3. 真正缺的是“对话框中的输入方式选择”和“音频 -> 文本”的完整产品链路。

## 2. 目标

### 2.1 必须满足

1. 用户可以在对话框中明确选择输入方式。
2. 至少支持两类音频输入：
   - 麦克风实时语音输入
   - 本地音频文件输入
3. 音频输入的结果必须先落为“可编辑文本”，再进入现有消息发送流程。
4. 不破坏现有文本输入、附件上传、知识库选择、模型选择等交互。
5. 在不支持音频能力的浏览器或后端环境下，能优雅降级。

### 2.2 非目标

1. 不做实时双向语音对话（TTS 回放、全双工通话）。
2. 不做服务端长时间流式音频识别。
3. 不做说话人分离、时间轴字幕编辑、降噪增强等高级音频处理。
4. 不把音频能力混入通用聊天模型能力判断中。

## 3. 现有可复用能力盘点

### 3.1 前端

#### 3.1.1 输入框主组件

- `frontend/src/components/workspace/input-box.tsx`
- 已负责：
  - 文本框
  - 附件按钮
  - 模式选择
  - 模型选择
  - 知识库选择

适合作为“输入方式切换”的承载点。

#### 3.1.2 语音识别按钮雏形

- `frontend/src/components/ai-elements/prompt-input.tsx`
- 已存在：
  - `PromptInputSpeechButton`
  - `SpeechRecognition` 类型定义
  - `onresult` 回填 textarea 的逻辑

优点：

- P0 几乎不需要后端改造
- 可快速验证 UX

限制：

- 依赖浏览器能力
- 当前语言写死为 `en-US`
- 不支持上传音频文件转写

#### 3.1.3 附件与文件上传链路

- `frontend/src/core/uploads/prompt-input-files.ts`
- `frontend/src/core/uploads/api.ts`
- `frontend/src/core/threads/hooks.ts`

当前文件发送逻辑是：

1. 在对话框里选择文件
2. 前端先调上传接口
3. 后端返回 `virtual_path`
4. 前端把文件信息放入消息 `additional_kwargs.files`

这条链路可以复用于“上传音频文件后转写”。

### 3.2 后端

#### 3.2.1 上传接口

- `backend/app/gateway/routers/uploads.py`

已支持：

- 多文件上传
- 文件大小限制
- 线程作用域存储
- 沙箱同步

未支持：

- 音频 MIME 白名单
- 音频转写
- 音频转写任务状态

#### 3.2.2 模型配置

当前模型配置只包含：

- `supports_thinking`
- `supports_reasoning_effort`
- `supports_vision`

未包含：

- `supports_audio_input`
- `supports_transcription`

因此音频输入能力不应直接挂在聊天模型元数据上，而应设计为独立配置域。

## 4. 推荐总体方案

推荐把“音频输入”拆成两条产品路径，并统一收敛到“提交前生成可编辑文本”的原则。

### 4.1 路径 A：麦克风实时语音输入

适用场景：

- 用户想快速口述问题
- 浏览器支持 Web Speech API
- 不要求上传原始音频文件

能力流程：

1. 用户在输入框中切换到“麦克风输入”
2. 点击录音按钮开始识别
3. 识别结果实时追加到 textarea
4. 用户可手动编辑文本
5. 最终仍按普通文本消息发送

### 4.2 路径 B：音频文件输入

适用场景：

- 用户已有 `.mp3/.wav/.m4a/.ogg/.webm`
- 需要更稳定的转写结果
- 需要保留原始音频作为上下文附件

能力流程：

1. 用户在输入框中切换到“音频文件输入”
2. 选择本地音频文件
3. 前端上传文件
4. 后端调用 STT Provider 生成转写文本
5. 前端展示可编辑转写结果
6. 用户确认后发送
7. 可选地在消息中携带原音频文件引用

### 4.3 为什么推荐“两阶段”

#### P0：先接浏览器语音识别

原因：

- 代码基础已经存在
- 风险低
- 无需新增后端模型和队列
- 可以先验证输入框交互是否被用户接受

#### P1：再补服务端音频转写

原因：

- 真正可用的“音频输入”不能只依赖浏览器语音识别
- 文件音频转写更稳定，也适合移动端、语音备忘、会议片段等场景
- 能力边界更完整

## 5. 交互设计

### 5.1 输入方式选择器

推荐在 `InputBox` 左侧工具区新增一个“输入方式选择器”，紧邻附件按钮。

建议选项：

1. `文本输入`
2. `麦克风输入`
3. `音频文件`

推荐 UI 形式：

- 一级按钮显示当前模式
- 点击展开下拉菜单选择输入方式

原因：

- 与当前“模式选择 / 模型选择 / 知识库选择”一致
- 不占太多空间
- 适合桌面和移动端压缩布局

### 5.2 文本输入模式

保持现状，不做行为变化。

### 5.3 麦克风输入模式

#### 5.3.1 UI 变化

进入该模式后：

1. 在输入框工具区显示 `麦克风按钮`
2. 可选显示 `语言选择`
3. 文本框 placeholder 改为：
   - “点击麦克风开始说话，识别结果会自动填入输入框”

#### 5.3.2 状态

建议状态机：

- `idle`
- `listening`
- `processing`
- `error`
- `unsupported`

#### 5.3.3 交互规则

1. 识别结果默认追加到当前文本末尾，不覆盖用户已输入内容。
2. 点击停止后，用户仍可编辑文本。
3. 若浏览器不支持语音识别：
   - 禁用该模式
   - 或切换后展示说明并引导改用“音频文件”

### 5.4 音频文件输入模式

#### 5.4.1 UI 变化

进入该模式后：

1. 附件按钮只接受音频文件
2. 显示音频文件卡片
3. 显示“转写中 / 转写完成 / 转写失败”
4. 转写完成后，把结果填入 textarea

#### 5.4.2 可选行为

建议支持一个开关：

- `发送时附带原始音频`

默认建议：

- 打开

原因：

- Agent 在需要时仍可读取原音频文件
- 后续如果支持更高级音频分析，不需要改消息协议

### 5.5 错误与降级

错误类型：

1. 浏览器不支持麦克风识别
2. 麦克风权限被拒绝
3. 音频文件过大
4. 音频格式不支持
5. 转写服务失败
6. 转写文本为空

处理原则：

1. 永远不要吞掉错误
2. 给用户明确反馈
3. 允许用户退回文本输入
4. 已上传音频文件可删除后重试

## 6. 后端设计

### 6.1 新增独立配置域

建议新增：

```yaml
audio_input:
  enabled: true
  microphone_enabled: true
  file_transcription_enabled: true
  default_locale: zh-CN
  supported_locales:
    - zh-CN
    - en-US
  accepted_mime_types:
    - audio/mpeg
    - audio/wav
    - audio/x-wav
    - audio/mp4
    - audio/webm
    - audio/ogg
  max_file_size: 26214400
  provider:
    use: deerflow.audio.providers.openai:OpenAITranscriptionProvider
    config:
      model: gpt-4o-mini-transcribe
      api_key: $OPENAI_API_KEY
      base_url: ""
```

说明：

1. `audio_input` 是独立能力，不跟 `models[]` 混用。
2. 聊天模型和转写模型允许不同。
3. 后续可以扩展为多 Provider。

另外建议补一个只返回安全字段的能力接口：

- `GET /api/audio/config`

用途：

1. 前端决定是否显示 `麦克风输入 / 音频文件输入`
2. 前端读取 `default_locale / supported_locales / max_file_size`
3. 避免把后端关闭的能力继续暴露成可点击入口

### 6.2 新增转写接口

建议新增路由：

`POST /api/threads/{thread_id}/audio/transcriptions`

请求：

- `multipart/form-data`
- `file`
- `locale`
- `attach_original` 可选

响应建议：

```json
{
  "success": true,
  "transcript": "这是转写结果",
  "language": "zh-CN",
  "duration_ms": 12345,
  "file": {
    "filename": "meeting.m4a",
    "virtual_path": "/mnt/user-data/uploads/meeting.m4a",
    "artifact_url": "/api/threads/xxx/artifacts/..."
  }
}
```

### 6.3 复用上传链路还是单独链路

推荐：

1. 文件保存仍复用现有上传目录和线程作用域。
2. 但音频转写接口单独存在，不直接复用普通 `/uploads` 路由作为最终 API。

原因：

1. 普通上传只负责存文件
2. 音频输入需要“上传 + 转写 + 返回文本”的原子交互
3. 单独路由更适合后续补充：
   - MIME 校验
   - 时长限制
   - provider metrics
   - 转写失败码

### 6.4 Provider 抽象

建议新增：

- `backend/packages/harness/deerflow/audio/providers/base.py`
- `backend/packages/harness/deerflow/audio/providers/openai.py`

统一接口：

```python
class AudioTranscriptionProvider(Protocol):
    async def transcribe(
        self,
        file_path: Path,
        *,
        locale: str | None = None,
    ) -> AudioTranscriptionResult: ...
```

返回值：

- `transcript`
- `language`
- `duration_ms`
- `segments` 可选
- `raw_response` 可选

### 6.5 安全与约束

1. 只允许白名单 MIME。
2. 增加音频文件大小限制。
3. 可选增加音频时长限制。
4. 不把原始音频字节写入数据库。
5. 日志中避免打印完整转写内容。

## 7. 前端设计

### 7.1 `InputBox` 改造

目标文件：

- `frontend/src/components/workspace/input-box.tsx`

新增本地状态建议：

```ts
type InputSource = "text" | "microphone" | "audio-file";
```

新增内容：

1. 输入方式选择器
2. 麦克风按钮接入
3. 音频文件模式下的文件选择与转写状态 UI

### 7.2 `PromptInput` 组件层改造

目标文件：

- `frontend/src/components/ai-elements/prompt-input.tsx`

建议改造点：

1. 给 `PromptInputTextarea` 暴露 `ref`
2. 让 `PromptInputSpeechButton` 支持：
   - 传入 `lang`
   - 传入是否覆盖/追加策略
   - 更稳定的受控输入同步
3. 不直接操作 DOM `textarea.value`，尽量通过 controller 写值

原因：

当前 `PromptInputSpeechButton` 依赖 `textareaRef` 和原生 `input` 事件，能工作，但不够贴合现有受控输入结构。

### 7.3 新增前端 API

建议新增：

- `frontend/src/core/audio/api.ts`

能力：

1. `transcribeAudioFile(threadId, file, options)`
2. 统一处理错误码与返回值

### 7.4 新增本地化文案

需要补充：

- `frontend/src/core/i18n/locales/zh-CN.ts`
- `frontend/src/core/i18n/locales/en-US.ts`

新增文案建议：

- `audioInput`
- `textInput`
- `microphoneInput`
- `audioFileInput`
- `startListening`
- `stopListening`
- `transcribingAudio`
- `transcriptionFailed`
- `microphoneUnsupported`
- `microphonePermissionDenied`

## 8. 数据流设计

### 8.1 麦克风输入

```text
用户点击麦克风
-> 浏览器 SpeechRecognition
-> 识别结果写入 textarea
-> 用户编辑
-> 按普通文本消息发送
```

### 8.2 音频文件输入

```text
用户选择音频文件
-> 前端调用 /audio/transcriptions
-> 后端保存文件到线程 uploads
-> 后端调用 STT provider
-> 返回 transcript + 文件路径
-> 前端填入 textarea
-> 用户编辑并发送
-> 消息 additional_kwargs 可带原音频 files
```

## 9. 分阶段实施建议

### 9.1 P0：浏览器语音输入

范围：

1. 在 `InputBox` 中接入 `PromptInputSpeechButton`
2. 新增输入方式选择器
3. 增加基础麦克风状态反馈
4. 增加语言配置

不包含：

1. 后端转写
2. 音频文件上传转写

收益：

- 最快可上线
- 改动小
- 低风险验证用户需求

### 9.2 P1：音频文件转写

范围：

1. 新增音频转写后端接口
2. 新增 Provider 抽象
3. 前端增加音频文件模式
4. 支持“转写后再发送”

### 9.3 P2：增强项

可选增强：

1. 分段时间戳
2. 自动语言识别
3. “发送原音频 + 转写文本”双通道消息
4. 音频转写历史缓存
5. Safari / 移动端兼容优化

## 10. 关键决策

### 10.1 是否把音频识别直接作为消息发送

不建议。

建议始终先生成可编辑文本，再发送。

原因：

1. 用户可校正识别错误
2. 兼容现有消息协议
3. 不要求 Agent 立即理解原始音频

### 10.2 是否把音频能力挂在聊天模型配置上

不建议。

建议独立 `audio_input` 配置域。

原因：

1. 聊天模型不等于转写模型
2. 浏览器语音识别甚至不依赖后端模型
3. 能力边界更清晰

### 10.3 是否直接复用 `/uploads`

不建议直接把音频输入能力压在通用上传接口上。

建议：

- 文件保存复用上传基础设施
- 业务接口单独提供 `/audio/transcriptions`

## 11. 风险与缓解

| 风险 | 描述 | 缓解方式 |
| --- | --- | --- |
| 浏览器兼容性差 | Web Speech API 在不同浏览器支持不一致 | P0 仅作增强能力，失败时回退文本输入 |
| 识别语言错误 | 默认语言不匹配会严重影响结果 | 提供 locale 选择并记住用户最近选择 |
| 音频转写成本 | 服务端转写会消耗额外模型费用 | 单独配置模型、大小限制、可关闭文件转写 |
| 文件过大 | 音频可能远大于普通图片/文本附件 | 增加专门的音频大小与时长限制 |
| UX 混乱 | 文本、附件、语音、音频文件混在一起 | 用“输入方式”显式切换，避免同时暴露太多控件 |

## 12. 推荐结论

推荐采用以下落地顺序：

1. 先做 P0，把已有 `PromptInputSpeechButton` 正式接入对话框。
2. 把“音频输入”设计成输入方式选择，而不是简单再塞一个按钮。
3. 再做 P1，补齐服务端音频文件转写链路。
4. 转写结果始终先进入可编辑文本框，再走现有发送链路。
5. 原始音频文件作为可选附件保留，不作为主消息协议的唯一载体。

这个方案最大化复用了当前代码基础，也把“快速上线”和“完整能力”拆成了两步，适合当前项目节奏。

## 13. 建议修改文件

### 前端

- `frontend/src/components/workspace/input-box.tsx`
- `frontend/src/components/ai-elements/prompt-input.tsx`
- `frontend/src/core/audio/api.ts`（新建）
- `frontend/src/core/i18n/locales/zh-CN.ts`
- `frontend/src/core/i18n/locales/en-US.ts`

### 后端

- `backend/app/gateway/routers/audio.py`（新建）
- `backend/app/gateway/app.py`（注册路由）
- `backend/packages/harness/deerflow/audio/providers/base.py`（新建）
- `backend/packages/harness/deerflow/audio/providers/openai.py`（新建）
- `backend/packages/harness/deerflow/config/audio_input_config.py`（新建）
- `backend/packages/harness/deerflow/config/app_config.py`
