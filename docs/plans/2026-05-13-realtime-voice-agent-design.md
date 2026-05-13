# 实时语音对话 Agent 设计文档

> **修订说明**：本版本根据架构评审意见重写，严格遵循 DeerFlow 现有模式（Provider 反射工厂、Singleton Config、Harness/App 边界、多租户隔离、SSE 优先、消息持久化）。

## 1. 概述

### 1.1 目标

在 EHM AI 工作台中新增"语音沟通"智能体，支持用户与 AI 进行实时语音对话。

### 1.2 交互模式

```
用户说话 → 麦克风采集 → STT（语音转文字）→ LLM 推理 → TTS（文字转语音）→ 扬声器播放
```

用户全程通过语音交互。AI 以语音形式回复，同时在界面上显示文字记录。语音对话作为普通 HumanMessage/AIMessage 持久化到 thread，刷新页面后历史依然可见。

### 1.3 核心指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 首字延迟 | < 1.5s | 用户说完到 AI 开始回复的时间 |
| 端到端延迟 | < 3s | 用户说完到听到 AI 语音的时间 |
| 语音识别准确率 | > 95% | 中文普通话环境 |
| 并发支持 | 10+ | 同时进行的语音会话数 |

---

## 2. 技术方案选型

### 2.1 方案对比

| 方案 | 延迟 | 成本 | 复杂度 | 适用场景 |
|------|------|------|--------|----------|
| **A: OpenAI Realtime API** | ~500ms | 高 | 低 | 英文为主，需要最低延迟 |
| **B: STT + LLM + TTS 分离** | 1-3s | 中 | 中 | 灵活可控，支持国内服务 |
| **C: WebRTC + 自建流式管线** | ~800ms | 低（自建） | 高 | 大规模部署 |

### 2.2 推荐方案：B（STT + LLM + TTS 分离）

**理由**：
- 国内网络环境下 OpenAI Realtime API 不稳定
- 可灵活选择国内 STT/TTS 服务商（讯飞、阿里、腾讯）
- 与现有 `deerflow.audio.providers` Provider 抽象兼容，可复用反射工厂
- 各组件可独立替换和升级

### 2.3 传输层：SSE + 分块 POST（优先）vs WebSocket（备选）

**当前项目无任何 WebSocket 端点，全部流式输出走 SSE**（`POST /api/threads/{id}/runs/stream`）。为最大程度复用现有中间件栈（CORS / CSRF / Auth / Rate Limit / Tenant Header），优先选择 **SSE + 分块上传** 方案：

| 方向 | 传输 | 端点 |
|------|------|------|
| 客户端 → 服务端（音频上行） | 分块 POST（multipart） | `POST /api/threads/{thread_id}/voice/audio` |
| 服务端 → 客户端（STT/LLM/TTS 下行） | SSE 长连接 | `GET /api/threads/{thread_id}/voice/stream` |
| 控制信令 | REST | `POST /api/threads/{thread_id}/voice/control` |

**WebSocket 作为 Phase 2 备选**：若 SSE 上行延迟无法满足首字 < 1.5s，再切换 WebSocket。WebSocket 切换时需补充：
- nginx `proxy_set_header Upgrade` 配置
- 握手期 token 校验（query param 或首条消息）
- 显式 tenant_id / user_id / thread_id 校验

---

## 3. 系统架构

### 3.1 整体架构（遵循 Harness/App 边界）

```
┌──────────────────────────────────────────────────────────────┐
│                      Frontend                                 │
│                                                              │
│  components/workspace/voice-chat/                           │
│  ┌──────────────┐   core/voice/api.ts (fetchGateway)        │
│  │ VoicePanel   │───▶ POST /api/.../voice/audio  (上行)     │
│  │ VoiceControls│◀── GET  /api/.../voice/stream (SSE 下行) │
│  │ Transcript   │   core/voice/hooks.ts (useVoiceSession)  │
│  └──────────────┘                                            │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP/SSE（复用 fetchGateway + CSRF + Tenant）
┌────────────────────────┼─────────────────────────────────────┐
│                        ▼   Backend (app 层 — 仅薄路由)        │
│                                                              │
│  backend/app/gateway/routers/voice.py                        │
│   ├ POST /api/threads/{tid}/voice/audio    上行音频块         │
│   ├ GET  /api/threads/{tid}/voice/stream   SSE 下行           │
│   └ POST /api/threads/{tid}/voice/control  控制信令           │
│   └── @require_permission("threads", "write", owner_check)   │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│                  Harness (deerflow.*)                         │
│                                                              │
│  deerflow/voice/session.py    VoiceSession 状态机           │
│  deerflow/voice/vad.py        VAD 语音活动检测              │
│  deerflow/voice/orchestrator.py STT→LLM→TTS 编排            │
│                                                              │
│  deerflow/audio/providers/    (已存在，仅扩展)              │
│   ├ base.py:  AudioTranscriptionProvider (已有)             │
│   │           StreamingSTTProvider Protocol (新增)           │
│   ├ openai.py (已有)                                         │
│   ├ xfyun_stt.py / aliyun_stt.py (新增，流式 STT)           │
│  deerflow/audio/tts/          (新增子包)                    │
│   ├ base.py:  TTSProvider Protocol + factory                │
│   ├ xfyun.py / aliyun.py                                     │
│                                                              │
│  deerflow/config/voice_config.py  VoiceConfig (singleton)   │
│                                                              │
│  调用 DeerFlowClient.stream() 走正常 agent 流水线           │
│  消息持久化为 HumanMessage / AIMessage 入 LangGraph thread  │
│  费用统计接入 UsageStorage + CostCalculator                 │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 数据流（SSE 方案）

```
1. 前端 useVoiceSession 打开 SSE：GET /api/threads/{tid}/voice/stream
2. 前端 MediaRecorder 采集 PCM 16k 16bit，每 100ms 一帧
3. 每帧通过 POST /api/threads/{tid}/voice/audio 上传
4. 后端 VoiceSession 累积音频，VAD 检测静音 > 800ms 判定说完
5. 累积音频送入 StreamingSTTProvider → 文本
6. 文本作为 HumanMessage 持久化到 thread
7. 通过 DeerFlowClient.stream(text, thread_id=tid) 调用 LLM（与文字模式同一管线）
8. LLM 流式 token → 按句切分（句号、问号、感叹号、逗号 > 50 字符）
9. 每句送入 TTSProvider → PCM 音频流
10. SSE 推送：state | stt_interim | stt_final | llm_delta | tts_audio (base64)
11. 前端 AudioContext BufferQueue 无缝播放
12. AI 完整回复持久化为 AIMessage
```

### 3.3 VAD 策略

```python
# deerflow/voice/vad.py
from pydantic import BaseModel

class VADConfig(BaseModel):
    silence_threshold_ms: int = 800
    min_speech_duration_ms: int = 300
    max_speech_duration_ms: int = 30000
    energy_threshold: float = 0.01
```

---

## 4. 后端组件设计

### 4.1 模块结构（严格对齐现有布局）

```
backend/packages/harness/deerflow/
├── audio/
│   ├── providers/
│   │   ├── base.py            # 扩展：新增 StreamingSTTProvider Protocol
│   │   ├── openai.py          # 已存在，不变
│   │   ├── xfyun_stt.py       # 新增：讯飞实时语音识别
│   │   └── aliyun_stt.py      # 新增：阿里云实时语音识别
│   └── tts/                    # 新增子包
│       ├── __init__.py
│       ├── base.py            # TTSProvider Protocol + build_tts_provider 工厂
│       ├── xfyun.py
│       └── aliyun.py
├── voice/                      # 新增：语音会话编排（不放 provider）
│   ├── __init__.py
│   ├── session.py             # VoiceSession 状态机
│   ├── vad.py                 # VAD
│   └── orchestrator.py        # STT → run_agent → 句切分 → TTS
├── config/
│   └── voice_config.py        # 新增：VoiceConfig + singleton

backend/app/gateway/routers/
└── voice.py                    # 新增：SSE + 上行 POST 端点
```

### 4.2 Provider 抽象（扩展现有 `deerflow.audio.providers.base`）

```python
# deerflow/audio/providers/base.py（追加，不修改现有代码）

from typing import AsyncIterator, Protocol, runtime_checkable
from dataclasses import dataclass

@dataclass(frozen=True)
class STTPartialResult:
    text: str
    is_final: bool
    language: str | None = None

@runtime_checkable
class StreamingSTTProvider(Protocol):
    """流式语音识别 Provider。与已有 AudioTranscriptionProvider 并存。"""

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        locale: str = "zh-CN",
        sample_rate: int = 16000,
    ) -> AsyncIterator[STTPartialResult]: ...
```

```python
# deerflow/audio/tts/base.py（新增）

from typing import AsyncIterator, Protocol, runtime_checkable
from deerflow.reflection.resolvers import resolve_variable

@runtime_checkable
class TTSProvider(Protocol):
    async def synthesize_stream(
        self,
        text: str,
        *,
        voice: str = "xiaoyan",
        speed: float = 1.0,
        sample_rate: int = 16000,
    ) -> AsyncIterator[bytes]: ...

def build_tts_provider(config: "VoiceConfig") -> TTSProvider:
    """按 use:"module.path:ClassName" 反射实例化（与 build_audio_transcription_provider 同模式）。"""
    provider_cls = resolve_variable(config.tts.use)
    return provider_cls(**(config.tts.config or {}))
```

### 4.3 配置（遵循 Singleton Config 模式）

```python
# deerflow/config/voice_config.py（对齐 audio_input_config.py）

from pydantic import BaseModel, Field
from threading import RLock

class ProviderRef(BaseModel):
    use: str  # "deerflow.audio.providers.xfyun_stt:XfyunStreamingSTTProvider"
    config: dict = Field(default_factory=dict)

class VADConfig(BaseModel):
    silence_threshold_ms: int = 800
    min_speech_duration_ms: int = 300
    max_speech_duration_ms: int = 30000

class AudioFrameConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    bit_depth: int = 16
    chunk_duration_ms: int = 100

class VoiceSessionLimits(BaseModel):
    max_duration_minutes: int = 30
    idle_timeout_seconds: int = 120

class VoiceConfig(BaseModel):
    enabled: bool = False
    stt: ProviderRef
    tts: ProviderRef
    vad: VADConfig = Field(default_factory=VADConfig)
    audio: AudioFrameConfig = Field(default_factory=AudioFrameConfig)
    session: VoiceSessionLimits = Field(default_factory=VoiceSessionLimits)

_voice_config: VoiceConfig | None = None
_lock = RLock()

def get_voice_config() -> VoiceConfig:
    with _lock:
        if _voice_config is None:
            raise RuntimeError("VoiceConfig not loaded")
        return _voice_config

def load_voice_config_from_dict(data: dict | None) -> None:
    global _voice_config
    with _lock:
        _voice_config = VoiceConfig(
            **(data or {"enabled": False, "stt": {"use": ""}, "tts": {"use": ""}})
        )

def reset_voice_config() -> None:
    global _voice_config
    with _lock:
        _voice_config = None
```

在 `AppConfig._apply_singleton_configs()` 追加：`load_voice_config_from_dict(data.get("voice"))`

### 4.4 VoiceSession 状态机

```
                    ┌─────────┐
                    │  IDLE   │
                    └────┬────┘
                         │ POST /voice/control {action: "start"}
                         ▼
              ┌────▶┌─────────┐
              │     │LISTENING│
              │     └────┬────┘
              │          │ VAD 检测静音 > silence_threshold_ms
              │          ▼
              │     ┌──────────┐
              │     │PROCESSING│  STT → DeerFlowClient.stream() → LLM
              │     └────┬─────┘
              │          │ LLM 首句 token + TTS 开始
              │          ▼
              │     ┌─────────┐
              └─────│SPEAKING │
   用户打断          └────┬────┘
   (interrupt)           │ 播放完毕
                         ▼
                    ┌─────────┐
                    │  IDLE   │
                    └─────────┘
```

**打断**：`POST /voice/control {action: "interrupt"}` → 取消当前 TTS task → 清空音频队列 → 切回 LISTENING。

**部署约束**：`VoiceSessionRegistry` 是进程内 dict，**Phase 1 仅支持单 worker 部署**（uvicorn `--workers 1`）。多 worker 时上行 POST 与下行 SSE 可能落到不同进程导致 session miss。Phase 2 引入 Redis 共享 session 状态以支持横向扩展。

### 4.5 路由（薄层，复用现有装饰器）

```python
# backend/app/gateway/routers/voice.py

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.gateway.authz import require_permission
from app.gateway.services import format_sse
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.voice.session import VoiceSessionRegistry

router = APIRouter(tags=["voice"])


class VoiceControlRequest(BaseModel):
    action: str  # "start" | "stop" | "interrupt"


async def voice_sse_consumer(session, request: Request):
    async for event in session.events():
        if await request.is_disconnected():
            break
        yield format_sse(event.type, event.data, event_id=event.id)


@router.get("/api/threads/{thread_id}/voice/stream")
@require_permission("threads", "read", owner_check=True, require_existing=True)
async def voice_stream(thread_id: str, request: Request) -> StreamingResponse:
    """SSE 下行：推送 state/stt/llm/tts 事件。"""
    user_id = get_effective_user_id()
    session = VoiceSessionRegistry.get_or_create(thread_id, user_id)
    return StreamingResponse(
        voice_sse_consumer(session, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/threads/{thread_id}/voice/audio")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def voice_audio(
    thread_id: str,
    request: Request,
    chunk: UploadFile = File(...),
):
    """上行音频块：前端每 100ms 发送一帧 PCM。"""
    user_id = get_effective_user_id()
    session = VoiceSessionRegistry.get(thread_id, user_id)
    await session.push_audio(await chunk.read())
    return {"ok": True}


@router.post("/api/threads/{thread_id}/voice/control")
@require_permission("threads", "write", owner_check=True, require_existing=True)
async def voice_control(
    thread_id: str,
    request: Request,
    body: VoiceControlRequest,
):
    """控制信令：start / stop / interrupt。"""
    user_id = get_effective_user_id()
    session = VoiceSessionRegistry.get_or_create(thread_id, user_id)
    await session.handle_control(body.action)
    return {"ok": True}
```

新增 router 后还需在 `backend/app/gateway/app.py` 注册：

```python
from app.gateway.routers import (..., voice, ...)

# create_app() 内
app.include_router(voice.router)
```

### 4.6 SSE 事件格式

```
event: state
data: {"state": "listening"}

event: stt_interim
data: {"text": "今天天气", "is_final": false}

event: stt_final
data: {"text": "今天天气怎么样", "language": "zh"}

event: llm_delta
data: {"text": "今天", "seq": 1}

event: tts_audio
data: {"data": "<base64 PCM 16kHz 16bit mono>", "seq": 1, "sentence_id": 1}

event: error
data: {"message": "STT service unavailable", "code": "stt_error"}
```

### 4.7 LLM 调用：复用 DeerFlowClient

语音会话 **不** 直接调用 `make_lead_agent()` 或 `deerflow.runtime.run_agent()`（后者依赖 app 层 `RunContext`，harness 代码无法访问）。而是通过 `DeerFlowClient.stream(message, thread_id=tid)` 走与文字模式相同的 agent 流水线。

```python
# deerflow/voice/orchestrator.py
from deerflow.client import DeerFlowClient, StreamEvent

client = DeerFlowClient(
    agent_name="voice-chat",
    tenant_id=tenant_id,
)

for event in client.stream(stt_text, thread_id=thread_id):
    if event.type == "messages-tuple" and event.data.get("type") == "ai":
        delta = event.data.get("content", "")
        if delta:
            # 按句切分 → 送入 TTSProvider
            sentence_buffer.append(delta)
```

`DeerFlowClient` 内部自行管理 checkpointer、store、agent factory，不依赖 app 层 singleton。保证：
- 同一 agent 同时可用于文字/语音
- 多租户、工具执行、子 agent、cost 追踪、UI Block 全部复用
- 消息以标准 HumanMessage/AIMessage 持久化到 LangGraph checkpoint

### 4.8 费用追踪

STT/TTS 每次调用通过 `UsageStorage().add_record(UsageRecord(...))` 上报（与 `worker.py` 中 LLM 费用上报同一模式）：

```python
from datetime import datetime, timezone
from deerflow.config.cost_config import get_cost_config
from deerflow.config.tenant import get_current_tenant_id
from deerflow.cost.storage import UsageRecord, UsageStorage

cost_cfg = get_cost_config()
if cost_cfg.enabled:
    storage = UsageStorage()
    storage.add_record(UsageRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        tenant_id=get_current_tenant_id(),
        thread_id=thread_id,
        model_name="xfyun_stt",  # 或 "xfyun_tts"
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cost_usd=estimated_cost,  # 按服务商单价换算
        user_id=user_id,
    ))
```

LLM 部分由 `DeerFlowClient` 内部自动上报，无需额外处理。

---

## 5. 前端组件设计

### 5.1 目录结构（对齐现有 workspace/ 与 core/ 模式）

```
frontend/src/core/voice/
├── api.ts                    # startVoiceStream / pushAudio / control
├── hooks.ts                  # useVoiceConfig / useVoiceSession
└── types.ts                  # VoiceState / VoiceEvent 类型

frontend/src/components/workspace/voice-chat/
├── voice-chat-panel.tsx      # 主面板（接入 ThreadContext）
├── voice-controls.tsx        # 静音/结束/设置按钮
├── voice-visualizer.tsx      # 波形可视化
├── voice-transcript.tsx      # 字幕区
└── use-voice-chat.ts         # 会话状态机 + AudioPlayer 管理
```

### 5.2 API 客户端（复用 fetchGateway 与 CSRF）

```typescript
// frontend/src/core/voice/api.ts
import { fetchGateway } from "@/core/api/fetch-gateway";

export async function pushVoiceAudio(threadId: string, chunk: Blob): Promise<void> {
  const form = new FormData();
  form.append("chunk", chunk);
  await fetchGateway(`/api/threads/${threadId}/voice/audio`, {
    method: "POST",
    body: form,
  });
}

export async function voiceControl(
  threadId: string,
  action: "start" | "stop" | "interrupt",
): Promise<void> {
  await fetchGateway(`/api/threads/${threadId}/voice/control`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
}

/**
 * 基于 fetch + ReadableStream 的 SSE 下行（不使用原生 EventSource，因其不支持自定义 Header）。
 * fetchGateway 自动注入 X-DeerFlow-Tenant / X-CSRF-Token / credentials。
 */
export async function openVoiceStream(
  threadId: string,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetchGateway(`/api/threads/${threadId}/voice/stream`, {
    method: "GET",
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) throw new Error(`Voice stream failed: ${response.status}`);
  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // 按 SSE 协议解析 event/data 帧
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const eventMatch = frame.match(/^event:\s*(.+)$/m);
      const dataMatch = frame.match(/^data:\s*(.+)$/m);
      if (eventMatch && dataMatch) {
        onEvent(eventMatch[1], JSON.parse(dataMatch[1]));
      }
    }
  }
}
```

### 5.3 hooks（参考 LangGraph SDK useStream 模式）

```typescript
// frontend/src/core/voice/hooks.ts
export function useVoiceSession(threadId: string) {
  // 基于 fetch+ReadableStream 的 SSE 连接管理（不使用 EventSource）
  // 重连策略参考 LangGraph SDK useStream：指数退避 1s → 30s max
  // AbortController 管理连接生命周期
  // 暴露: state, transcript, isRecording, startRecording, stopRecording, interrupt
  // 音频采集: AudioWorklet → pushVoiceAudio
  // 音频播放: AudioContext BufferQueue
}
```

### 5.4 Agent 配置

```yaml
# agents/builtin/voice-chat/config.yaml
name: voice-chat
display_name: "语音沟通"
description: "实时语音对话，像打电话一样与 AI 交流"
icon: "🎙️"
order: 6
model: null
tool_groups:
  - bash
skills: []
mcp_servers: null
tags:
  - voice
advanced:
  subagent_enabled: false
```

**说明**：
- `tags: [voice]` — 前端据此 tag 切换到语音 UI，不在 agent 配置中嵌入 provider 信息
- 语音基础设施配置统一放在全局 `config.yaml` 的 `voice:` 节
- SOUL.md 针对语音交互优化（短句、口语化、避免长 markdown）

---

## 6. 全局配置（config.yaml）

```yaml
voice:
  enabled: true
  stt:
    use: "deerflow.audio.providers.xfyun_stt:XfyunStreamingSTTProvider"
    config:
      app_id: $XFYUN_APP_ID
      api_key: $XFYUN_API_KEY
      api_secret: $XFYUN_API_SECRET
  tts:
    use: "deerflow.audio.tts.xfyun:XfyunTTSProvider"
    config:
      app_id: $XFYUN_APP_ID
      api_key: $XFYUN_API_KEY
      api_secret: $XFYUN_API_SECRET
      voice: xiaoyan
      speed: 50
      volume: 50
  vad:
    silence_threshold_ms: 800
    min_speech_duration_ms: 300
    max_speech_duration_ms: 30000
  audio:
    sample_rate: 16000
    channels: 1
    bit_depth: 16
    chunk_duration_ms: 100
  session:
    max_duration_minutes: 30
    idle_timeout_seconds: 120
```

**多租户**：Phase 1 仅全局凭证。Phase 2 支持 `tenants/{tenant_id}/voice.yaml` 覆盖（延续 `http_connectors` 模式）。

---

## 7. 前端音频处理

### 7.1 音频采集（AudioWorklet）

```typescript
const audioContext = new AudioContext({ sampleRate: 16000 });
const stream = await navigator.mediaDevices.getUserMedia({
  audio: {
    sampleRate: 16000,
    channelCount: 1,
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  },
});
await audioContext.audioWorklet.addModule("/audio-processor.js");
const worklet = new AudioWorkletNode(audioContext, "audio-processor");
// 每 100ms 输出 PCM Float32 → 转 Int16 → POST /voice/audio
```

### 7.2 播放队列

```typescript
class AudioPlayer {
  private context: AudioContext;
  private queue: AudioBuffer[] = [];
  private isPlaying = false;

  async playChunk(pcm: ArrayBuffer) {
    const buffer = this.context.createBuffer(1, pcm.byteLength / 2, 16000);
    // decode PCM Int16 to Float32
    this.queue.push(buffer);
    if (!this.isPlaying) this.playNext();
  }

  interrupt() {
    this.queue = [];
    this.isPlaying = false;
  }
}
```

### 7.3 回声 / 自激

- 浏览器 `echoCancellation: true` 兜底
- AI 播放期间前端门控静音麦克风
- 后续可接 WebRTC AEC

---

## 8. 实施计划

### Phase 1: 后端骨架（3天）

- [ ] `deerflow/config/voice_config.py` + AppConfig `_apply_singleton_configs` 注册
- [ ] `deerflow/audio/providers/base.py` 追加 `StreamingSTTProvider` Protocol
- [ ] `deerflow/audio/tts/base.py` + 工厂
- [ ] `deerflow/voice/session.py` 状态机 + `VoiceSessionRegistry`
- [ ] `deerflow/voice/vad.py` 能量阈值版本
- [ ] `app/gateway/routers/voice.py` 三个端点（StreamingResponse + format_sse）
- [ ] `app/gateway/app.py` 注册 `voice.router`（`app.include_router(voice.router)`）
- [ ] nginx 配置：voice 端点 keepalive + 关闭 proxy_buffering
- [ ] 单元测试：状态机、VAD、Provider 工厂反射

### Phase 2: Provider 实现（2天）

- [ ] `XfyunStreamingSTTProvider`（wss://iat-api.xfyun.cn/v2/iat）
- [ ] `XfyunTTSProvider`（wss://tts-api.xfyun.cn/v2/tts）
- [ ] 接入 `deerflow.cost.record_usage()`
- [ ] 联调：录音 → STT → 文字 → TTS → 音频

### Phase 3: LLM 编排（2天）

- [ ] `deerflow/voice/orchestrator.py`
- [ ] 消息持久化：HumanMessage / AIMessage 入 LangGraph
- [ ] 打断机制

### Phase 4: 前端（3天）

- [ ] `core/voice/api.ts` + `hooks.ts`（fetch + ReadableStream SSE + 指数退避）
- [ ] AudioWorklet 处理器（`public/audio-processor.js`）
- [ ] `voice-chat-panel.tsx` + visualizer + transcript
- [ ] 接入 `tags: voice` agent 路由
- [ ] 错误降级

### Phase 5: 测试与调优（2天）

- [ ] 端到端延迟测试（< 3s）
- [ ] 并发压测（10+ 会话）
- [ ] 多浏览器兼容
- [ ] 多租户隔离测试

---

## 9. 风险与应对

| 风险 | 影响 | 应对 |
|------|------|------|
| STT/TTS 服务不稳定 | 对话中断 | Provider 工厂支持多备选，自动降级 |
| SSE 上行延迟过高 | 首字延迟超标 | Phase 1 要求 HTTP keepalive + nginx `proxy_buffering off`；超标切 WebSocket |
| 100ms 一次 POST 请求开销高 | 网关压力大 | 连接复用；必要时改为 200ms chunk 或 WebSocket |
| 多 worker session 不一致 | 音频块找不到 session | Phase 1 单 worker；Phase 2 Redis-backed VoiceSessionRegistry |
| 浏览器兼容性 | 无法使用 | 降级文字输入；前端探测 MediaRecorder/AudioWorklet |
| 回声自激 | 识别干扰 | AEC + 播放期间门控麦克风 |
| 并发成本失控 | 费用高 | 会话时长限制 + 空闲超时 + cost 阈值告警 |
| 跨租户凭证泄露 | 安全 | Phase 1 全局凭证，Phase 2 引入 tenant 覆盖 |

---

## 10. 成本估算

讯飞按量计费：

| 服务 | 单价 | 预估用量/月 | 月费用 |
|------|------|-------------|--------|
| 实时语音识别 | ¥0.033/次 | 10000 次 | ¥330 |
| 语音合成 | ¥0.02/次 | 10000 次 | ¥200 |
| **合计** | | | **¥530/月** |

---

## 11. 后续扩展

1. **多语言**：切换 STT/TTS locale
2. **语音克隆**：自定义音色
3. **WebSocket 升级**：若 SSE 延迟瓶颈明确
4. **租户级 Provider**：`tenants/{id}/voice.yaml` 覆盖
5. **会议模式**：多人语音 + AI 参与

---

## 附录：与现有架构对齐检查表

| 项 | 现有模式 | 本设计 | 状态 |
|----|----------|--------|------|
| STT Provider 位置 | `deerflow/audio/providers/` | 同 | ✅ |
| TTS Provider 位置 | — | `deerflow/audio/tts/`（同级新子包） | ✅ |
| Provider 实例化 | `use: module:Class` + `resolve_variable` | 同 | ✅ |
| Config 模式 | Pydantic + module singleton + load/reset | 同 | ✅ |
| AppConfig 注册 | `_apply_singleton_configs` | 同 | ✅ |
| Router 注册 | `app.include_router(xxx.router)` in `app.py` | 同 | ✅ |
| SSE 流式 | `StreamingResponse` + `format_sse()` | 同 | ✅ |
| 路由权限 | `@require_permission(..., owner_check=True)` | 同 | ✅ |
| 用户解析 | `get_effective_user_id()` | 同 | ✅ |
| 租户隔离 | `X-DeerFlow-Tenant` + runtime 上下文 | 同 | ✅ |
| Harness/App 边界 | `deerflow.*` 不引 `app.*` | 同 | ✅ |
| LLM 调用 | `DeerFlowClient.stream()` | 同（不绕过 runtime） | ✅ |
| 消息持久化 | LangGraph HumanMessage/AIMessage | 同 | ✅ |
| 费用统计 | `UsageStorage().add_record(UsageRecord(...))` | 同 | ✅ |
| Agent 配置 | tags + advanced.subagent_enabled | tags: [voice] | ✅ |
| 前端 API | `fetchGateway` + CSRF + Tenant Header | 同 | ✅ |
| 前端 SSE | `fetch` + `ReadableStream`（非 EventSource） | 同 | ✅ |
| 前端重连 | LangGraph SDK `useStream` 指数退避 | 同 | ✅ |
| 组件位置 | `components/workspace/<feature>/` | `components/workspace/voice-chat/` | ✅ |
| Hook 位置 | `core/<domain>/hooks.ts` | `core/voice/hooks.ts` | ✅ |
| 部署约束 | 单 worker / 多 worker | Phase 1 单 worker，Phase 2 Redis | ✅ |
