# Chat Audio Input Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在对话框中交付可上线的音频输入能力，先支持浏览器麦克风语音转文字，再支持音频文件上传转写，并统一收敛到现有文本消息发送链路。

**Architecture:** 采用分阶段落地。前端先接入现有 `PromptInputSpeechButton` 作为 P0；后端再新增独立的 `audio_input` 配置、转写 Provider 抽象和 `/audio/transcriptions` 路由作为 P1。文本仍然是消息协议的唯一主载体，原始音频只是可选附件引用。

**Tech Stack:** Next.js 16、React 19、Vitest、FastAPI、Pydantic、可插拔 STT Provider、线程上传目录。

---

## Status（2026-05-09）

当前计划中的 Task 1-8 主体已完成，并已通过聚焦单测、前端类型检查和目标文件 ESLint。

已完成交付：

- Task 1: `audio_input` 配置域已落地并接入 `AppConfig`
- Task 2: 音频转写 Provider 抽象与 OpenAI-compatible provider 已落地
- Task 3: `POST /api/threads/{thread_id}/audio/transcriptions` 已落地
- Task 4: 前端 `audio` API / hooks 已落地
- Task 5: `PromptInputSpeechButton` 已接入受控输入
- Task 6: `InputBox` 已支持输入方式选择器与麦克风模式
- Task 7: 音频文件模式已支持自动转写、错误提示和重试
- Task 8: 已补 `GET /api/audio/config` 用于前端能力门控，并完成本轮回归与文档对齐

后续可选增强：

1. 增加“发送时附带原始音频”的显式 UI 开关。
2. 增加更多 locale 与 provider 实现。
3. 补真实浏览器麦克风 E2E 和移动端兼容验证。

### Task 1: 定义音频输入配置与后端能力开关

**Files:**
- Create: `backend/packages/harness/deerflow/config/audio_input_config.py`
- Modify: `backend/packages/harness/deerflow/config/app_config.py`
- Test: `backend/tests/test_audio_input_config.py`

**Step 1: Write the failing test**

新增配置测试，覆盖：

- 默认值加载成功
- `enabled/microphone_enabled/file_transcription_enabled`
- `accepted_mime_types`
- `supported_locales`
- provider 配置解析

示例测试骨架：

```python
def test_audio_input_config_defaults():
    config = AudioInputConfig()
    assert config.enabled is False
    assert config.microphone_enabled is True
    assert "audio/mpeg" in config.accepted_mime_types
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest backend/tests/test_audio_input_config.py -q
```

Expected:

- `ModuleNotFoundError` 或 `AudioInputConfig` 未定义

**Step 3: Write minimal implementation**

新增配置模型：

```python
class AudioInputProviderConfig(BaseModel):
    use: str = "deerflow.audio.providers.openai:OpenAITranscriptionProvider"
    config: dict[str, Any] = Field(default_factory=dict)


class AudioInputConfig(BaseModel):
    enabled: bool = False
    microphone_enabled: bool = True
    file_transcription_enabled: bool = False
    default_locale: str = "zh-CN"
    supported_locales: list[str] = Field(default_factory=lambda: ["zh-CN", "en-US"])
    accepted_mime_types: list[str] = Field(default_factory=lambda: [
        "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/webm", "audio/ogg",
    ])
    max_file_size: int = 25 * 1024 * 1024
    provider: AudioInputProviderConfig = Field(default_factory=AudioInputProviderConfig)
```

并把 `AppConfig` 接上：

- 新增 `audio_input: AudioInputConfig`
- 在 `_apply_singleton_configs` 或配置加载链路中接线

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest backend/tests/test_audio_input_config.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/config/audio_input_config.py backend/packages/harness/deerflow/config/app_config.py backend/tests/test_audio_input_config.py
git commit -m "feat: add audio input configuration"
```

### Task 2: 建立音频转写 Provider 抽象

**Files:**
- Create: `backend/packages/harness/deerflow/audio/providers/base.py`
- Create: `backend/packages/harness/deerflow/audio/providers/openai.py`
- Test: `backend/tests/test_audio_transcription_provider.py`

**Step 1: Write the failing test**

覆盖：

- Provider 接口返回统一结果结构
- OpenAI-compatible provider 能组装 multipart 请求
- provider 调用失败时抛出受控异常

示例测试骨架：

```python
@pytest.mark.asyncio
async def test_openai_provider_returns_transcript(httpx_mock):
    provider = OpenAITranscriptionProvider(model="gpt-4o-mini-transcribe", api_key="test")
    result = await provider.transcribe(Path("sample.wav"), locale="zh-CN")
    assert result.transcript == "你好世界"
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest backend/tests/test_audio_transcription_provider.py -q
```

Expected:

- Provider 模块不存在

**Step 3: Write minimal implementation**

统一返回类型建议：

```python
@dataclass
class AudioTranscriptionResult:
    transcript: str
    language: str | None = None
    duration_ms: int | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    raw_response: dict[str, Any] | None = None
```

Provider 接口建议：

```python
class AudioTranscriptionProvider(Protocol):
    async def transcribe(self, file_path: Path, *, locale: str | None = None) -> AudioTranscriptionResult: ...
```

OpenAI provider 最小实现：

- 从 config 读 `model/api_key/base_url`
- 发到 `/audio/transcriptions`
- 解析 `text/language/duration`

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest backend/tests/test_audio_transcription_provider.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/audio/providers/base.py backend/packages/harness/deerflow/audio/providers/openai.py backend/tests/test_audio_transcription_provider.py
git commit -m "feat: add audio transcription provider abstraction"
```

### Task 3: 新增音频转写 Gateway 路由

**Files:**
- Create: `backend/app/gateway/routers/audio.py`
- Modify: `backend/app/gateway/routers/__init__.py`
- Modify: `backend/app/gateway/app.py`
- Test: `backend/tests/test_audio_router.py`

**Step 1: Write the failing test**

覆盖：

- 未启用 `audio_input.enabled` 时返回 404/400
- 非法 MIME 被拒绝
- 超大文件被拒绝
- 正常上传时返回 `transcript + file info`

示例测试骨架：

```python
def test_audio_transcription_rejects_unsupported_mime(client):
    response = client.post("/api/threads/t1/audio/transcriptions", files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 415
```

**Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest backend/tests/test_audio_router.py -q
```

Expected:

- `/audio/transcriptions` 路由不存在

**Step 3: Write minimal implementation**

路由建议：

- `POST /api/threads/{thread_id}/audio/transcriptions`

最小流程：

1. 校验 feature flag
2. 校验 MIME / size
3. 保存文件到线程 uploads 目录
4. 调用 Provider 转写
5. 返回：
   - `success`
   - `transcript`
   - `language`
   - `duration_ms`
   - `file.filename`
   - `file.virtual_path`
   - `file.artifact_url`

优先复用：

- `ensure_uploads_dir`
- `normalize_filename`
- `upload_virtual_path`
- `upload_artifact_url`

**Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest backend/tests/test_audio_router.py -q
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add backend/app/gateway/routers/audio.py backend/app/gateway/routers/__init__.py backend/app/gateway/app.py backend/tests/test_audio_router.py
git commit -m "feat: add audio transcription gateway endpoint"
```

### Task 4: 新增前端音频 API 层

**Files:**
- Create: `frontend/src/core/audio/api.ts`
- Create: `frontend/src/core/audio/hooks.ts`
- Test: `frontend/tests/unit/core/audio/api.test.ts`

**Step 1: Write the failing test**

覆盖：

- multipart 请求正确发送
- 错误响应能正确读出 detail
- 成功响应结构被正确解析

示例测试骨架：

```ts
test("transcribeAudioFile posts multipart form data", async () => {
  const result = await transcribeAudioFile("thread-1", file, { locale: "zh-CN" });
  expect(result.transcript).toBe("你好");
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/core/audio/api.test.ts
```

Expected:

- `Cannot find module '@/core/audio/api'`

**Step 3: Write minimal implementation**

建议导出：

```ts
export async function transcribeAudioFile(
  threadId: string,
  file: File,
  options?: { locale?: string; attachOriginal?: boolean },
): Promise<AudioTranscriptionResponse>
```

可选 hooks：

- `useAudioTranscription(threadId)`

**Step 4: Run test to verify it passes**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/core/audio/api.test.ts
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add frontend/src/core/audio/api.ts frontend/src/core/audio/hooks.ts frontend/tests/unit/core/audio/api.test.ts
git commit -m "feat: add frontend audio transcription api"
```

### Task 5: 把 Speech Button 接入受控输入链路

**Files:**
- Modify: `frontend/src/components/ai-elements/prompt-input.tsx`
- Test: `frontend/tests/unit/components/ai-elements/prompt-input-speech.test.tsx`

**Step 1: Write the failing test**

覆盖：

- 支持浏览器语音识别时按钮可用
- 识别结果写入受控 `textInput`
- `lang` 可配置
- 停止录音后状态恢复

示例测试骨架：

```ts
test("speech button appends transcript into controlled input", async () => {
  render(...)
  expect(screen.getByRole("button", { name: /speech/i })).toBeEnabled()
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/ai-elements/prompt-input-speech.test.tsx
```

Expected:

- 现有实现无法稳定驱动受控输入，或测试组件不存在

**Step 3: Write minimal implementation**

改造目标：

1. `PromptInputSpeechButton` 支持 `lang`
2. 优先通过 `usePromptInputController().textInput.setInput()` 写值
3. 保留 `textareaRef` 仅作兼容兜底
4. 把错误状态通过回调或 toast 暴露出来

**Step 4: Run test to verify it passes**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/ai-elements/prompt-input-speech.test.tsx
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add frontend/src/components/ai-elements/prompt-input.tsx frontend/tests/unit/components/ai-elements/prompt-input-speech.test.tsx
git commit -m "feat: wire speech recognition into controlled prompt input"
```

### Task 6: 在 InputBox 中加入输入方式选择器与 P0 麦克风模式

**Files:**
- Modify: `frontend/src/components/workspace/input-box.tsx`
- Modify: `frontend/src/core/i18n/locales/types.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Test: `frontend/tests/unit/components/workspace/input-box-audio.test.tsx`

**Step 1: Write the failing test**

覆盖：

- 可切换 `text / microphone / audio-file`
- 麦克风模式下显示语音按钮
- 浏览器不支持时显示降级提示
- 切回文本模式后现有行为不变

示例测试骨架：

```ts
test("switches input source to microphone and shows speech button", async () => {
  render(<InputBox ... />)
  await user.click(screen.getByText("文本输入"))
  await user.click(screen.getByText("麦克风输入"))
  expect(screen.getByRole("button", { name: /microphone/i })).toBeInTheDocument()
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/workspace/input-box-audio.test.tsx
```

Expected:

- 输入方式选择器不存在

**Step 3: Write minimal implementation**

在 `InputBox` 中新增：

```ts
type InputSource = "text" | "microphone" | "audio-file";
```

接入点：

- 附件按钮旁新增 dropdown/toggle
- `microphone` 模式显示 `PromptInputSpeechButton`
- placeholder 跟随模式变化

**Step 4: Run test to verify it passes**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/workspace/input-box-audio.test.tsx
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add frontend/src/components/workspace/input-box.tsx frontend/src/core/i18n/locales/types.ts frontend/src/core/i18n/locales/zh-CN.ts frontend/src/core/i18n/locales/en-US.ts frontend/tests/unit/components/workspace/input-box-audio.test.tsx
git commit -m "feat: add chat input source selector and microphone mode"
```

### Task 7: 增加音频文件模式与转写结果回填

**Files:**
- Modify: `frontend/src/components/workspace/input-box.tsx`
- Modify: `frontend/src/components/ai-elements/prompt-input.tsx`
- Modify: `frontend/src/core/uploads/file-validation.ts`
- Test: `frontend/tests/unit/components/workspace/input-box-audio-file.test.tsx`
- Test: `frontend/tests/unit/core/uploads/file-validation-audio.test.ts`

**Step 1: Write the failing test**

覆盖：

- `audio-file` 模式下文件选择只接受音频 MIME
- 选择音频后触发转写 API
- 转写结果回填到 textarea
- 转写失败后保留重试入口

示例测试骨架：

```ts
test("audio file mode transcribes selected audio into textarea", async () => {
  render(<InputBox ... />)
  // choose audio mode -> upload file -> transcript appears
})
```

**Step 2: Run test to verify it fails**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/workspace/input-box-audio-file.test.tsx tests/unit/core/uploads/file-validation-audio.test.ts
```

Expected:

- 音频模式和音频 MIME 校验逻辑不存在

**Step 3: Write minimal implementation**

前端策略：

1. `audio-file` 模式下给 `PromptInput` 传 `accept="audio/*"`
2. 选中文件后优先调用 `transcribeAudioFile`
3. 成功后：
   - 把 transcript 写入 textarea
   - 根据产品决策决定是否保留原始音频附件
4. 失败后：
   - toast
   - 保留文件供删除或重试

**Step 4: Run test to verify it passes**

Run:

```bash
pnpm --dir frontend vitest run tests/unit/components/workspace/input-box-audio-file.test.tsx tests/unit/core/uploads/file-validation-audio.test.ts
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add frontend/src/components/workspace/input-box.tsx frontend/src/components/ai-elements/prompt-input.tsx frontend/src/core/uploads/file-validation.ts frontend/tests/unit/components/workspace/input-box-audio-file.test.tsx frontend/tests/unit/core/uploads/file-validation-audio.test.ts
git commit -m "feat: add audio file transcription mode in chat input"
```

### Task 8: 联调、回归与文档收尾

**Files:**
- Modify: `docs/plans/2026-05-08-chat-audio-input-design.md`
- Modify: `docs/plans/2026-05-08-chat-audio-input-implementation-plan.md`
- Test: `backend/tests/test_audio_router.py`
- Test: `backend/tests/test_audio_transcription_provider.py`
- Test: `frontend/tests/unit/components/workspace/input-box-audio.test.tsx`
- Test: `frontend/tests/unit/components/workspace/input-box-audio-file.test.tsx`

**Step 1: Run focused backend tests**

```bash
python -m pytest backend/tests/test_audio_input_config.py backend/tests/test_audio_transcription_provider.py backend/tests/test_audio_router.py -q
```

Expected:

- PASS

**Step 2: Run focused frontend tests**

```bash
pnpm --dir frontend vitest run tests/unit/core/audio/api.test.ts tests/unit/components/ai-elements/prompt-input-speech.test.tsx tests/unit/components/workspace/input-box-audio.test.tsx tests/unit/components/workspace/input-box-audio-file.test.tsx
```

Expected:

- PASS

**Step 3: Run frontend typecheck**

```bash
pnpm --dir frontend typecheck
```

Expected:

- PASS

**Step 4: Run frontend lint**

```bash
pnpm --dir frontend lint
```

Expected:

- PASS

**Step 5: Document final behavior**

在设计稿中补充：

- P0 已实现范围
- P1 已实现范围
- 已知浏览器兼容性限制

**Step 6: Commit**

```bash
git add docs/plans/2026-05-08-chat-audio-input-design.md docs/plans/2026-05-08-chat-audio-input-implementation-plan.md
git commit -m "docs: finalize chat audio input implementation plan"
```

## 验收标准

1. 用户能在对话框中看到明确的输入方式选择器。
2. 麦克风模式下，浏览器支持时可把语音识别结果写入输入框。
3. 音频文件模式下，用户可上传音频并获得可编辑转写文本。
4. 文本最终仍通过现有消息发送链路提交，不引入新的主消息格式。
5. 原有文本输入、附件上传、知识库选择、模型选择不回归。

## 实施顺序建议

1. 先完成 Task 1-3，保证后端能力边界清晰。
2. 再完成 Task 5-6，把 P0 先交付上线。
3. 最后完成 Task 4 + Task 7，把音频文件转写接上。
4. Task 8 作为合并前的统一回归口。
