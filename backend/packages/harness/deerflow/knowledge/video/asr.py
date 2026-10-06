"""ASR leg (spec 2026-09-08 §2/§3, plan Task 3).

第二条腿：把视频音轨转录为带 PTS 毫秒时间戳的口述段序列。这是**降级腿**——
整腿失败（依赖缺失/模型加载失败/解码失败）抛 ``AsrError``，worker（Task 7）
捕获后置 asr=failed 并让镜头卡口述段写「（ASR 失败）」，文档仍可达 ready
（spec §2 降级矩阵），绝不因 ASR 挂掉整篇文档。

provider 协议隔离（spec §7 asr_provider）：两支**进程内引擎**（funasr / whisper，
重依赖延迟 import，缺失即降级 AsrError）+ 两支**服务档**（openai-audio / dashscope，
同步 blocking 的 HTTP 调用，spec 2026-09-28 D5）。``normalize_transcript``
是核心纯函数：把各 provider 的原始 (start, end, text) 三元组（秒或毫秒）规整为
统一 PTS 毫秒轴的 TranscriptSegment——单位换算、取整、去空白、丢弃无效段、按
start_ms 升序（spec §3 时间轴对齐规则的上游；下游 materialize 再按镜头桶 join）。

blocking 的模型推理与服务档的 HTTP 调用都经 ``run_file_io`` 落线程池，不阻塞事件循环。
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx

from deerflow.config.rag_config_file import configured_rag_secret
from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.endpoint_url import join_endpoint
from deerflow.knowledge.messages import bilingual
from deerflow.knowledge.providers import secret_env_var
from deerflow.utils.file_io import run_file_io

logger = logging.getLogger(__name__)

Unit = Literal["ms", "s"]


class AsrError(Exception):
    """ASR 整腿失败——worker 降级 asr=failed，文档仍 ready（spec §2）。"""


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    """一条口述段，落在 PTS 毫秒轴上的闭开区间 ``[start_ms, end_ms)``。"""

    start_ms: int
    end_ms: int
    text: str


class AsrProvider(Protocol):
    """ASR backend 协议：同步 blocking transcribe，返回原始 (start, end, text) 三元组。"""

    name: str
    unit: Unit

    def transcribe(self, path: str) -> list[tuple[float, float, str]]: ...


def normalize_transcript(rows: Iterable[Sequence[Any]], *, unit: Unit = "ms") -> list[TranscriptSegment]:
    """把 provider 原始 (start, end, text) 规整为标准 TranscriptSegment 序列。

    纯函数，ASR 腿的核心契约：

    - 单位换算：``unit="s"`` 时秒 → 毫秒；两者都 round 到整数毫秒；
    - 清洗：text 去首尾空白，空/纯空白文本丢弃；
    - 有效性：``start_ms < 0`` 或 ``end_ms <= start_ms``（零/负长度）的段丢弃（防御）；
    - 排序：按 ``(start_ms, end_ms)`` 升序（provider 输出可能乱序）。

    **不合并相邻段**——按镜头桶拼接是 materialize 腿（Task 7）的职责，此处只
    产出干净、有序、有效的段序列供其 join。
    """
    scale = 1000.0 if unit == "s" else 1.0
    segments: list[TranscriptSegment] = []
    for row in rows:
        try:
            start_ms = int(round(float(row[0]) * scale))
            end_ms = int(round(float(row[1]) * scale))
        except (TypeError, ValueError, IndexError):
            continue  # 畸形行防御性跳过
        text = str(row[2]).strip()
        if not text or start_ms < 0 or end_ms <= start_ms:
            continue
        segments.append(TranscriptSegment(start_ms=start_ms, end_ms=end_ms, text=text))
    segments.sort(key=lambda seg: (seg.start_ms, seg.end_ms))
    return segments


#: funasr 自带配件（spec 2026-09-28 §2 D1/D3）：VAD 3.9 MB 负责长音频切段；
#: cam++ 28 MB 在无 punc 时退到 vad_segment 模式，**顺带产出 `sentence_info`**（VAD 段粒度 + `spk`）。
_VAD_MODEL = "fsmn-vad"
_SPK_MODEL = "cam++"

#: 不吃配件的名字（spec §2 D3）：流式按 chunk 调；ModelScope 托管的 whisper 走自己的路径。
_NO_COMPANION_NAMES = frozenset({"paraformer-zh-streaming"})
_NO_COMPANION_PREFIXES = ("Whisper-",)


def _funasr_kwargs(model: str) -> dict[str, str]:
    """该模型名要带的配件（VAD + 说话人）；例外名单里返回空（spec §2 D3）。"""
    if model in _NO_COMPANION_NAMES or model.startswith(_NO_COMPANION_PREFIXES):
        return {}
    return {"vad_model": _VAD_MODEL, "spk_model": _SPK_MODEL}


class FunAsrProvider:
    """FunASR Paraformer（默认，本地 CPU 离线，spec §7）。重依赖延迟 import。"""

    name = "funasr"
    unit: Unit = "ms"  # Paraformer 时间戳为毫秒

    def __init__(self, model: str) -> None:
        self._model = model

    def transcribe(self, path: str) -> list[tuple[float, float, str]]:
        try:
            from funasr import AutoModel  # 延迟 import：缺失即降级
        except ImportError as exc:
            raise AsrError("FunASR 未安装：视频口述转录需要 funasr（pip install funasr）；或改配置 rag.video.asr_provider=whisper 走兼容档") from exc
        try:
            model = AutoModel(model=self._model, disable_update=True, **_funasr_kwargs(self._model))
            result = model.generate(input=path, batch_size_s=300)
        except Exception as exc:  # 模型加载/解码/推理失败统一降级
            raise AsrError(f"FunASR 转录失败（{self._model}）：{exc}") from exc
        return _rows_from_funasr(result)


class WhisperProvider:
    """whisper（本地 CPU 兼容档，spec §7）。重依赖延迟 import。"""

    name = "whisper"
    unit: Unit = "s"  # whisper segment 时间戳为秒（float）

    def __init__(self, model: str) -> None:
        self._model = model

    def transcribe(self, path: str) -> list[tuple[float, float, str]]:
        try:
            import whisper  # 延迟 import：缺失即降级
        except ImportError as exc:
            raise AsrError("whisper 未安装：走 whisper 档需要 openai-whisper（pip install openai-whisper）；或用默认 rag.video.asr_provider=funasr") from exc
        try:
            model = whisper.load_model(self._model)
            result = model.transcribe(path)
        except Exception as exc:
            raise AsrError(f"whisper 转录失败（{self._model}）：{exc}") from exc
        return _rows_from_whisper(result)


#: 「整段一行」的判据（spec 2026-09-28 §4.2）：只有一段、且覆盖 ≥90% 时长 ⇒ 口述只落一张卡。
_COLLAPSED_SPAN_RATIO = 0.9
_COLLAPSED_WARNING = "ASR 转录整段一行（单段覆盖全片）：口述只会落在一张镜头卡上——连续语音时 VAD 只切出一段（spec 2026-09-28 §4.2）。"

#: 服务档（走 HTTP）的名字 —— 与 allowlist 的 `asr` 腿同一份清单；另外两个是进程内引擎。
#: 公开常量：探针要按它判断"这一格有没有端点可测"（D7 只挂服务档）。
SERVICE_TIER_NAMES = frozenset({"openai-audio", "dashscope"})
#: D6：同步 + base64 只服务 ≤5 分钟；更长的整段留在本地腿（一期不投递）。
SERVICE_TIER_MAX_AUDIO_MS = 5 * 60 * 1000
#: 超长音频的落点：进程内引擎里的默认那支（D6 的「本地腿」）。
_LOCAL_ENGINE_NAME = "funasr"

_DASHSCOPE_ASR_PATH = "/api/v1/services/aigc/multimodal-generation/generation"
_OPENAI_AUDIO_PATH = "/v1/audio/transcriptions"
#: 转写是长请求，但必须有界：超时收敛为 AsrError（D8）。
_SERVICE_TIMEOUT_SECONDS = 120.0


def resolve_leg_provider(provider_name: str, *, duration_ms: int | None) -> str:
    """D6：服务档只吃 ≤5 分钟（同步 + base64），更长的整段留在本地腿。

    时长未知时不换（拿不到判据就不改行为）；进程内引擎的名字原样返回。
    """
    if provider_name in SERVICE_TIER_NAMES and duration_ms is not None and duration_ms > SERVICE_TIER_MAX_AUDIO_MS:
        return _LOCAL_ENGINE_NAME
    return provider_name


class _ServiceAsrProvider:
    """服务档共用：地址守卫、钥匙解析（配置 → 环境）、客户端注入与超时。

    地址留空是**配置错误**，不是"用厂商默认"（2026-09-25 rag-endpoint-unlock D1 乙）——
    所以守卫在构造里，保存期那条检查只要构造一次就能拿到同一个判定（与 build_reranker 同形）。
    """

    name: str = ""
    unit: Unit = "ms"
    _key_env_var: str | None = None

    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
        timeout_seconds: float = _SERVICE_TIMEOUT_SECONDS,
    ) -> None:
        if not (base_url or "").strip():
            raise RagConfigurationError(bilingual(f"服务档 ASR 需要服务地址：请设置 rag.asr_base_url（asr_provider={self.name}）", f"A service-tier ASR needs a service address: set rag.asr_base_url (asr_provider={self.name})"))
        self._model = model
        self._base_url = base_url.strip().rstrip("/")
        self._api_key = api_key
        self._client = client
        self._timeout = timeout_seconds

    def _read_api_key(self) -> str:
        key = self._api_key or configured_rag_secret("asr_api_key") or (os.environ.get(self._key_env_var) if self._key_env_var else None)
        if not key:
            raise AsrError(f"{self.name} 缺少 API Key：填 rag.asr_api_key 或设置环境变量 {self._key_env_var}")
        return key

    def _http_client(self) -> httpx.Client:
        """同步客户端（blocking，经 run_file_io 落线程池）；测试可注入一个桩。"""
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    def transcribe(self, path: str) -> list[tuple[float, float, str]]:  # pragma: no cover - 协议占位
        raise NotImplementedError


class DashScopeAsrProvider(_ServiceAsrProvider):
    """百炼同步档（spec 2026-09-28 §5.4）：原生协议，`qwen-audio-3.1-asr-flash`。

    三条硬事实都钉在这里：``parameters.format`` 必填（值不校验，填后缀即可）、
    ``speaker_diarization_enabled`` 在 **parameters 顶层**（它同时是分段开关）、
    音频走 base64 data URL。
    """

    name = "dashscope"
    unit: Unit = "ms"  # begin_time / end_time 是毫秒
    _key_env_var = secret_env_var("asr", "dashscope")

    def transcribe(self, path: str) -> list[tuple[float, float, str]]:
        suffix = Path(path).suffix.lstrip(".").lower() or "wav"
        encoded = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        payload = {
            "model": self._model,
            "input": {"messages": [{"role": "user", "content": [{"audio": f"data:audio/{suffix};base64,{encoded}"}]}]},
            "parameters": {"format": suffix, "speaker_diarization_enabled": True},
        }
        response = self._http_client().post(
            f"{self._base_url}{_DASHSCOPE_ASR_PATH}",
            headers={"Authorization": f"Bearer {self._read_api_key()}"},
            json=payload,
        )
        response.raise_for_status()
        return _rows_from_dashscope(response.json())


class OpenAiAudioProvider(_ServiceAsrProvider):
    """OpenAI 音频协议档：`POST /audio/transcriptions`（OpenAI 官方 / 兼容端点 / 本机服务同形）。

    ``response_format=verbose_json`` 是段级时间戳的前提——默认只回文本。
    """

    name = "openai-audio"
    unit: Unit = "s"  # segments[].start / end 是秒
    _key_env_var = secret_env_var("asr", "openai-audio")

    def transcribe(self, path: str) -> list[tuple[float, float, str]]:
        source = Path(path)
        response = self._http_client().post(
            join_endpoint(self._base_url, _OPENAI_AUDIO_PATH),
            headers={"Authorization": f"Bearer {self._read_api_key()}"},
            data={"model": self._model, "response_format": "verbose_json"},
            files={"file": (source.name, source.read_bytes(), "application/octet-stream")},
        )
        response.raise_for_status()
        return _rows_from_openai_audio(response.json())


def _is_collapsed(segments: Sequence[TranscriptSegment], duration_ms: int | None) -> bool:
    """单段且跨度≈全片 ⇒ 退化；拿不到时长时不判（spec §4.2）。"""
    if not duration_ms or len(segments) != 1:
        return False
    span = segments[0].end_ms - segments[0].start_ms
    return span >= duration_ms * _COLLAPSED_SPAN_RATIO


def _rows_from_funasr(result: Any) -> list[tuple[float, float, str]]:
    """FunASR ``generate()`` 输出 → (start_ms, end_ms, text) 三元组。

    真机校准（2026-09-29，spec 2026-09-28 §2 D2）：句级分段在 ``sentence_info``
    （每项 ``{text, start, end, ...}``，毫秒；装 punc 或 cam++ 时才出现）；
    没有它时退回 ``timestamp``（逐字对）取首末（"整段一行"的信号由调用方按跨度判，见 ``_is_collapsed``）。
    """
    rows: list[tuple[float, float, str]] = []
    items = result if isinstance(result, (list, tuple)) else [result]
    for item in items:
        if not isinstance(item, dict):
            continue
        sentences = item.get("sentence_info")
        if isinstance(sentences, dict):
            sentences = [sentences]
        if isinstance(sentences, list) and sentences:
            for sent in sentences:
                if isinstance(sent, dict) and "start" in sent and "end" in sent:
                    rows.append((sent["start"], sent["end"], sent.get("text", "")))
            continue
        stamps = item.get("timestamp")
        if isinstance(stamps, list) and stamps:
            rows.append((stamps[0][0], stamps[-1][-1], item.get("text", "")))
    return rows


def _rows_from_whisper(result: Any) -> list[tuple[float, float, str]]:
    """whisper ``transcribe()`` 输出 → (start_s, end_s, text) 三元组（原文不 strip）。"""
    rows: list[tuple[float, float, str]] = []
    segments = result.get("segments") if isinstance(result, dict) else None
    for seg in segments or []:
        if isinstance(seg, dict):
            rows.append((seg.get("start", 0.0), seg.get("end", 0.0), seg.get("text", "")))
    return rows


def _dashscope_levels(result: Any) -> list[dict]:
    """百炼实测里同一份结果挂在 `output.*` 与 `output.output.*` 两层（spec §5.4 ③）。"""
    if not isinstance(result, dict):
        return []
    output = result.get("output")
    if not isinstance(output, dict):
        return []
    levels = [output]
    inner = output.get("output")
    if isinstance(inner, dict):
        levels.append(inner)
    return levels


def _segments_to_rows(entries: Any) -> list[tuple[float, float, str]]:
    """`[{start, end, text}]` 形状的条目 → 三元组；**空或单段 ⇒ 空 rows**。

    三种拼法都认：OpenAI 的 `start`/`end`（秒）、百炼的 `begin_time`/`end_time`（毫秒）、
    火山的 `start_time`/`end_time`（毫秒）——单位由 provider 的 `unit` 声明，这里只取数。

    单段也算"没答案"（spec §1 硬要求 ③）：服务端没分段时不要假装有一行——本地腿那条
    "整段一行"的降级在服务档这里不成立，因为服务档本来就该给段。
    """
    rows: list[tuple[float, float, str]] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start", entry.get("begin_time", entry.get("start_time")))
        end = entry.get("end", entry.get("end_time"))
        if start is None or end is None:
            continue
        rows.append((float(start), float(end), str(entry.get("text", ""))))
    return rows if len(rows) > 1 else []


def _rows_from_dashscope(result: Any) -> list[tuple[float, float, str]]:
    """百炼同步档输出 → (start_ms, end_ms, text) 三元组。

    `sentences[]`（**开了说话人开关才有**）优先，没有它时退回 `utterances[]`（火山形状，
    随投递二期）。两层嵌套都认（§5.4 ③）。
    """
    levels = _dashscope_levels(result)
    for key in ("sentences", "utterances"):
        entries = next((level[key] for level in levels if isinstance(level.get(key), list) and level[key]), None)
        if entries:
            return _segments_to_rows(entries)
    return []


def _rows_from_openai_audio(result: Any) -> list[tuple[float, float, str]]:
    """OpenAI 音频协议输出 → (start_s, end_s, text) 三元组（`verbose_json` 的 `segments[]`）。

    ⚠️ 「有 segments」≠「真时间戳」：`funasr-server` 在只拿到文本时会**自己造段**
    （按字数等比摊开，spec §5.2）——本函数照收，识破它的是探针（D7）。
    """
    segments = result.get("segments") if isinstance(result, dict) else None
    return _segments_to_rows(segments)


def resolve_provider(name: str, *, model: str, base_url: str | None = None, api_key: str | None = None) -> AsrProvider:
    """按配置名路由到 provider 实例（spec §7 asr_provider；服务档 spec 2026-09-28 D5）。

    服务档的地址守卫在 provider 的构造里，所以保存期那条检查构造一次即可（与
    ``build_reranker`` 同形）；进程内引擎不吃地址与钥匙。
    """
    if name == "funasr":
        return FunAsrProvider(model=model)
    if name == "whisper":
        return WhisperProvider(model=model)
    if name == "openai-audio":
        return OpenAiAudioProvider(model, base_url=base_url, api_key=api_key)
    if name == "dashscope":
        return DashScopeAsrProvider(model, base_url=base_url, api_key=api_key)
    raise AsrError(f"未知 ASR provider：{name!r}（支持 funasr | whisper | openai-audio | dashscope）")


async def transcribe_video(
    path: str,
    *,
    provider: AsrProvider | None = None,
    provider_name: str = "funasr",
    model: str,
    duration_ms: int | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> list[TranscriptSegment]:
    """转录视频音轨为规整的口述段序列（第二条腿，降级腿）。

    ``provider`` 可注入（测试用 fake）；否则按 ``provider_name`` 解析真实
    provider（服务档要 ``base_url`` / ``api_key``——worker 从 ``rag.video`` 那一对传进来）。
    blocking 推理与 HTTP 调用经 ``run_file_io`` 落线程池。任何失败——依赖缺失、
    模型崩溃、解码错误、网络失败、超时、401——都收敛为 ``AsrError`` 供 worker 降级
    （asr=failed），绝不让整篇文档因 ASR 挂掉。

    ``duration_ms``（探测腿给的时长）有两个用处：判"整段一行"（只有一段且覆盖 ≥90%
    时长时记一条 warning，spec 2026-09-28 §4.2），以及服务档的长音频闸门（调用方按
    ``resolve_leg_provider`` 先决定用哪支）。
    """
    prov = provider or resolve_provider(provider_name, model=model, base_url=base_url, api_key=api_key)
    try:
        raw = await run_file_io(prov.transcribe, path)
    except AsrError:
        raise
    except Exception as exc:
        raise AsrError(f"ASR 转录失败（{getattr(prov, 'name', provider_name)}）：{exc}") from exc
    segments = normalize_transcript(raw, unit=getattr(prov, "unit", "ms"))
    if _is_collapsed(segments, duration_ms):
        logger.warning(_COLLAPSED_WARNING)
    return segments
