# MiniMax 接入生成类 Skill — 设计文档

- 日期：2026-06-08
- 分支：`worktree-feat-minimax-generation`
- 参考：MiniMax 开放平台 API（https://platform.minimaxi.com/docs/api-reference）

## 1. 目标

1. 在现有 `image-generation`、`video-generation`、`podcast-generation` 三个 skill 中接入 MiniMax 作为可选 provider（与现有 Gemini / Volcengine 并存）。
2. 用项目自带的 `skill-creator` skill 新建一个 `music-generation` skill，对接 MiniMax 音乐生成 API。

## 2. 背景与现状

三个生成 skill 均位于 `skills/public/<name>/`，是**自包含目录**：

- `SKILL.md`（frontmatter：`name`、`description` + 给 agent 的使用说明，运行时路径为 `/mnt/skills/public/<name>/...`、产物写到 `/mnt/user-data/...`）
- `scripts/generate.py`（纯 `requests` 调用外部 API 的 CLI，`argparse`）
- 可选 `templates/`

现状 provider：

| Skill | 现 provider | 端点 | 凭证 |
|---|---|---|---|
| image-generation | Gemini | `generativelanguage.googleapis.com/.../gemini-3-pro-image-preview:generateContent` | `GEMINI_API_KEY` |
| video-generation | Gemini Veo | `.../veo-3.1-generate-preview:predictLongRunning`（长任务轮询） | `GEMINI_API_KEY` |
| podcast-generation | Volcengine TTS | `openspeech.bytedance.com/api/v1/tts`（逐行多线程，base64 音频拼接） | `VOLCENGINE_TTS_APPID` + `VOLCENGINE_TTS_ACCESS_TOKEN`（+ 可选 `VOLCENGINE_TTS_CLUSTER`） |

MiniMax 已作为 **LLM chat provider** 接入（`config.example.yaml` + `patched_minimax.py`），但**未用于**图像/视频/音频生成。仓库中**无** music 生成功能。

沙箱中各 skill 目录隔离、互不 import → MiniMax 代码在每个 skill 内**各自内联**，不做跨 skill 共享模块（少量重复可接受）。

`skill-creator` 是仓库内真实公共 skill（`skills/public/skill-creator/`，含 `scripts/init_skill.py` 脚手架）。前端 `frontend/src/app/mock/api/skills/route.ts` 维护着 UI 展示用的 skill 列表（mock）。

## 3. Provider 选择机制（已和用户确认）

每个被改造的脚本新增 `_resolve_provider()`，判定顺序：

1. **显式覆盖**：若环境变量 `<SKILL>_PROVIDER` 已设（如 `IMAGE_GENERATION_PROVIDER`、`VIDEO_GENERATION_PROVIDER`、`PODCAST_GENERATION_PROVIDER`，取值 `gemini`/`volcengine`/`minimax`），直接采用，覆盖自动判断。
2. **现有 provider 优先**：现 provider 凭证齐全 → 用现有 provider（保持完全向后兼容）。
3. **回退 MiniMax**：否则若 `MINIMAX_API_KEY` 已设 → 用 MiniMax。
4. 都不满足 → 抛出清晰错误，提示两套环境变量该如何配置。

> 设计含义：默认行为不变（已有用户配了 Gemini/Volcengine 的不受影响）；只配了 MiniMax 的用户自动走 MiniMax；两者都配又想用 MiniMax 的用户用 `<SKILL>_PROVIDER` 强制。

## 4. MiniMax 接口对接细节

通用：

- Base URL 默认 `https://api.minimaxi.com`，可用 `MINIMAX_API_HOST` 覆盖（备用 `https://api-bj.minimaxi.com`）。
- Header：`Authorization: Bearer $MINIMAX_API_KEY`、`Content-Type: application/json`。
- 统一错误处理：响应体 `base_resp.status_code != 0` → 抛带 `status_msg` 的异常。

### 4.1 图像 `POST /v1/image_generation`（同步）

请求体：
```json
{
  "model": "image-01",
  "prompt": "<文本>",
  "aspect_ratio": "16:9",
  "response_format": "base64",
  "n": 1,
  "prompt_optimizer": true
}
```
- 参考图：转成 Data URL（`data:image/jpeg;base64,...`），放入
  `subject_reference: [{"type": "character", "image_file": "<data url>"}]`（仅 `image-01` 支持；用现有 `--reference-images` 的图片）。
- 响应：`data.image_base64[0]` → `base64.b64decode` 写出文件；`response_format:url` 时取 `data.image_urls[0]` 下载（实现选 base64，少一次下载）。
- 模型可用 `MINIMAX_IMAGE_MODEL` 覆盖（默认 `image-01`）。

### 4.2 视频（异步三步）

1. `POST /v1/video_generation`：
   ```json
   { "model": "MiniMax-Hailuo-2.3", "prompt": "<文本>", "first_frame_image": "<data url，可选>" }
   ```
   → `{ "task_id": "...", "base_resp": {...} }`
2. 轮询 `GET /v1/query/video_generation?task_id=<id>` → `status ∈ {Preparing,Queueing,Processing,Success,Fail}`；`Success` 时返回 `file_id`。
3. `GET /v1/files/retrieve?file_id=<id>` → `file.download_url`；下载 mp4 写出。
- 参考图：第一张转 Data URL 作 `first_frame_image`。
- 视频无 `aspect_ratio` 概念（用 resolution/duration），MiniMax 路径忽略 `--aspect-ratio`，用默认 resolution。
- 轮询间隔 3s，设最大次数上限（如 120 次≈6 分钟）防止无限循环；`Fail`/超时报错。
- 模型可用 `MINIMAX_VIDEO_MODEL` 覆盖（默认 `MiniMax-Hailuo-2.3`）。

### 4.3 播客 TTS `POST /v1/t2a_v2`（同步）

沿用现有"逐行 + `ThreadPoolExecutor` 多线程 + 拼接"结构，仅替换单行合成函数：
```json
{
  "model": "speech-2.6-hd",
  "text": "<单行文本>",
  "voice_setting": { "voice_id": "<male/female 预设>", "speed": 1.0, "vol": 1.0, "pitch": 0 },
  "audio_setting": { "sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1 },
  "output_format": "hex"
}
```
- 响应 `data.audio` 为 **hex 编码** → `bytes.fromhex(audio)`（区别于 Volcengine 的 base64）。
- 角色映射：`male`/`female` → MiniMax voice_id 预设，默认值可用 `MINIMAX_TTS_VOICE_MALE` / `MINIMAX_TTS_VOICE_FEMALE` 覆盖。
- 模型可用 `MINIMAX_TTS_MODEL` 覆盖（默认 `speech-2.6-hd`）。

### 4.4 音乐 `POST /v1/music_generation`（同步，新 skill）

请求体：
```json
{
  "model": "music-2.6-free",
  "prompt": "<风格/情绪/场景>",
  "lyrics": "[verse]\n...\n[chorus]\n...",
  "output_format": "hex",
  "audio_setting": { "sample_rate": 44100, "bitrate": 256000, "format": "mp3" }
}
```
- 响应 `data.audio` 为 **hex** → `bytes.fromhex` 写 mp3。
- 歌词规则：
  - 提供 `lyrics`：直接用（含 `[Verse]`/`[Chorus]` 等结构标签，`\n` 分行）。
  - 未提供且 `is_instrumental` 为真：`is_instrumental:true`（不需要 lyrics）。
  - 未提供且非纯音乐：`lyrics_optimizer:true`（系统据 `prompt` 自动写词）。
- 仅用 `MINIMAX_API_KEY`（音乐只有 MiniMax 提供，无 provider 判断）；模型可用 `MINIMAX_MUSIC_MODEL` 覆盖（默认 `music-2.6-free`，付费用户可设 `music-2.6`）。

## 5. 各组件改动清单

### 5.1 `skills/public/image-generation/scripts/generate.py`
- 抽出现有 Gemini 逻辑为 `_generate_image_gemini(...)`。
- 新增 `_generate_image_minimax(...)`、`_resolve_provider("image_generation", ...)`、`_to_data_url(path)`。
- `generate_image(...)` 顶层按 provider 路由；保留 CLI 与签名不变。
- `SKILL.md`：在说明里补充 MiniMax provider 与所需环境变量（不改变调用方式）。

### 5.2 `skills/public/video-generation/scripts/generate.py`
- 同上模式：`_generate_video_gemini`、`_generate_video_minimax`（三步轮询）、`_resolve_provider("video_generation", ...)`。
- `SKILL.md` 补充 MiniMax provider 说明。

### 5.3 `skills/public/podcast-generation/scripts/generate.py`
- `text_to_speech_volcengine`（现有改名）+ `text_to_speech_minimax`；`_process_line`/`tts_node` 内按 `_resolve_provider("podcast_generation", ...)` 选择合成函数与 voice 映射。
- 环境变量校验同时支持两套；`SKILL.md` 补充说明。

### 5.4 新增 `skills/public/music-generation/`（用 skill-creator）
- 用 `skill-creator/scripts/init_skill.py` 脚手架生成目录骨架，再填充：
  - `SKILL.md`：frontmatter `name: music-generation` + description；说明输入 JSON 结构、调用方式、环境变量、示例（按现有生成 skill 的风格与运行时路径 `/mnt/skills/public/music-generation/...`）。
  - `scripts/generate.py`：CLI `--prompt-file <json> --output-file <mp3>`；读 JSON `{title, prompt, lyrics?, is_instrumental?}`；调 `/v1/music_generation`；hex→mp3。
- `frontend/src/app/mock/api/skills/route.ts`：新增 `music-generation` 条目（按字母序，`category:"public"`、`enabled:true`），使其出现在 UI skill 列表。

## 6. 测试（TDD）

- 框架：pytest。测试目录：仓库根 `tests/skills/`（**不放进会部署到沙箱的 skill 目录**）。
- 用 `importlib.util.spec_from_file_location` 按路径加载各 `generate.py`。
- `requests.post` / `requests.get` 全部用 `unittest.mock` 打桩，**不打真实 API**。
- 覆盖点：
  - `_resolve_provider`：各环境变量组合（仅现有 key / 仅 MiniMax key / 两者 / 都无 / `<SKILL>_PROVIDER` 覆盖）→ 正确 provider 或正确报错。
  - 请求体构造：image/video/podcast/music 各自 payload 字段、模型默认与 env 覆盖、参考图 Data URL 转换。
  - 响应解析：image base64 解码写文件、music/podcast hex 解码、video 三步流转（mock task_id→Success→download_url→内容写出）。
  - 错误：`base_resp.status_code != 0` 抛异常；video `Fail`/超时分支。
- 先写失败测试，再实现到通过。

## 7. 向后兼容性

- 现有 CLI 参数与默认行为完全不变；仅当现 provider 凭证缺失（或显式 `<SKILL>_PROVIDER`）时才走 MiniMax。
- 不改 LLM 侧已有的 MiniMax 接入。

## 8. 新增环境变量汇总

| 变量 | 用途 | 默认 |
|---|---|---|
| `MINIMAX_API_KEY` | 复用现有 LLM 同名 key | 必填（走 MiniMax 时） |
| `MINIMAX_API_HOST` | MiniMax base url | `https://api.minimaxi.com` |
| `IMAGE_GENERATION_PROVIDER` / `VIDEO_GENERATION_PROVIDER` / `PODCAST_GENERATION_PROVIDER` | 强制 provider | 不设（自动判断） |
| `MINIMAX_IMAGE_MODEL` | 图像模型 | `image-01` |
| `MINIMAX_VIDEO_MODEL` | 视频模型 | `MiniMax-Hailuo-2.3` |
| `MINIMAX_TTS_MODEL` | TTS 模型 | `speech-2.6-hd` |
| `MINIMAX_TTS_VOICE_MALE` / `MINIMAX_TTS_VOICE_FEMALE` | 播客音色 | 选定的男/女系统音色 |
| `MINIMAX_MUSIC_MODEL` | 音乐模型 | `music-2.6-free` |

## 9. 非目标（YAGNI）

- 不做翻唱（`music-cover` / `music_cover_preprocess`）、独立歌词生成接口（`lyrics_generation`，音乐内置 `lyrics_optimizer` 已覆盖"自动写词"）、音色复刻/设计、视频模板 Agent、流式合成。
- 不为各 skill 抽象统一 "GenerationProvider" 框架（沙箱隔离 + YAGNI）。
