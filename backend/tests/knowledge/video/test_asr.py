"""ASR leg contract tests (spec 2026-09-08 §2/§3, plan Task 3).

真实 provider（FunASR/whisper）是重依赖 + 需 ffmpeg 解码音频：本机/CI 不装，
故规整纯函数、provider 协议路由、异常降级用 fake provider 全覆盖。真实
provider 在依赖缺失时必须降级为 AsrError（整腿失败，worker 捕获后 asr=failed
但文档仍 ready，spec §2），本测试直接依赖「本机 funasr/whisper 未装」这一事实
钉死降级路径。

时间戳合并纯函数 normalize_transcript 是 ASR 腿的核心契约：把各 provider 的
原始 (start, end, text) 三元组（秒或毫秒）规整为统一的 PTS 毫秒轴
TranscriptSegment 序列——单位换算、取整、去空白、丢弃无效段、按 start_ms
升序（spec §3 时间轴对齐规则的上游）。
"""

from __future__ import annotations

import inspect
import json
import logging
import sys
import types

import httpx
import pytest

from deerflow.knowledge.embedder import RagConfigurationError
from deerflow.knowledge.video.asr import (
    AsrError,
    DashScopeAsrProvider,
    FunAsrProvider,
    OpenAiAudioProvider,
    TranscriptSegment,
    WhisperProvider,
    _rows_from_dashscope,
    _rows_from_funasr,
    _rows_from_openai_audio,
    _rows_from_whisper,
    normalize_transcript,
    resolve_leg_provider,
    resolve_provider,
    transcribe_video,
)

# ── normalize_transcript 纯函数 ──────────────────────────────────────────


def test_normalize_converts_seconds_to_integer_ms():
    segs = normalize_transcript([(0.0, 2.5, "你好"), (2.5, 5.123, "世界")], unit="s")
    assert segs == [TranscriptSegment(0, 2500, "你好"), TranscriptSegment(2500, 5123, "世界")]


def test_normalize_ms_unit_passes_through():
    segs = normalize_transcript([(0, 1500, "开场")], unit="ms")
    assert segs == [TranscriptSegment(0, 1500, "开场")]


def test_normalize_sorts_by_start_and_strips_text():
    segs = normalize_transcript([(5000, 6000, "  后段  "), (0, 1000, "前段")], unit="ms")
    assert [(seg.start_ms, seg.text) for seg in segs] == [(0, "前段"), (5000, "后段")]


def test_normalize_drops_empty_zero_negative_and_invalid():
    segs = normalize_transcript(
        [
            (0, 1000, "   "),  # 空白文本 → 丢
            (1000, 1000, "零长度"),  # end == start → 丢
            (2000, 1500, "负长度"),  # end < start → 丢
            (-500, 500, "负起点"),  # start < 0 → 丢
            (3000, 4000, "保留"),  # 合法
        ],
        unit="ms",
    )
    assert segs == [TranscriptSegment(3000, 4000, "保留")]


def test_normalize_empty_input_is_empty_list():
    assert normalize_transcript([], unit="ms") == []


# ── provider 工厂路由 ────────────────────────────────────────────────────


def test_resolve_provider_routes_by_name():
    assert isinstance(resolve_provider("funasr", model="paraformer-zh"), FunAsrProvider)
    assert isinstance(resolve_provider("whisper", model="small"), WhisperProvider)


def test_resolve_provider_unknown_name_raises_asrerror():
    with pytest.raises(AsrError):
        resolve_provider("nonexistent-provider", model="x")


# ── C-3: 模型名必须由调用方给（spec 2026-09-30 D3，③＝甲）────────────────


def test_transcribe_video_requires_the_model_name():
    signature = inspect.signature(transcribe_video)

    assert signature.parameters["model"].default is inspect.Parameter.empty


def test_funasr_provider_requires_the_model_name():
    signature = inspect.signature(FunAsrProvider.__init__)

    assert signature.parameters["model"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        FunAsrProvider()


def test_whisper_provider_requires_the_model_name():
    signature = inspect.signature(WhisperProvider.__init__)

    assert signature.parameters["model"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        WhisperProvider()


def test_resolve_provider_still_requires_the_model_name():
    """The pre-existing required shape stays a guard (it was already correct)."""
    signature = inspect.signature(resolve_provider)

    assert signature.parameters["model"].default is inspect.Parameter.empty


def test_resolve_leg_provider_takes_no_model():
    """The tier downgrade answers with a provider name only — never a model."""
    signature = inspect.signature(resolve_leg_provider)

    assert "model" not in signature.parameters


# ── transcribe_video 编排（fake provider 注入）───────────────────────────


class _FakeProvider:
    """协议对齐：name / unit / transcribe(path) -> 原始三元组序列。"""

    def __init__(self, rows, *, unit="s", name="fake", exc=None):
        self._rows = rows
        self.unit = unit
        self.name = name
        self._exc = exc
        self.seen_paths: list[str] = []

    def transcribe(self, path: str):
        self.seen_paths.append(path)
        if self._exc is not None:
            raise self._exc
        return self._rows


async def test_transcribe_video_uses_injected_provider_and_unit(tmp_path):
    fake = _FakeProvider([(0.0, 2.5, "你好"), (2.5, 4.0, "世界")], unit="s")
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"placeholder")

    segs = await transcribe_video(str(target), provider=fake, model="paraformer-zh")

    assert segs == [TranscriptSegment(0, 2500, "你好"), TranscriptSegment(2500, 4000, "世界")]
    assert fake.seen_paths == [str(target)]  # path 透传给 provider


async def test_transcribe_video_wraps_provider_crash_as_asrerror(tmp_path):
    fake = _FakeProvider([], exc=RuntimeError("模型加载炸了"))
    with pytest.raises(AsrError) as excinfo:
        await transcribe_video(str(tmp_path / "clip.mp4"), provider=fake, model="paraformer-zh")
    assert "模型加载炸了" in str(excinfo.value)  # 原始错误进降级信息


async def test_transcribe_video_propagates_asrerror_unchanged(tmp_path):
    fake = _FakeProvider([], exc=AsrError("已经是 AsrError"))
    with pytest.raises(AsrError) as excinfo:
        await transcribe_video(str(tmp_path / "clip.mp4"), provider=fake, model="paraformer-zh")
    assert str(excinfo.value) == "已经是 AsrError"  # 不二次包裹


# ── 真实 provider 依赖缺失 → 降级 AsrError（本机 funasr/whisper 未装）─────


async def test_real_funasr_provider_degrades_to_asrerror(tmp_path):
    with pytest.raises(AsrError):
        await transcribe_video(str(tmp_path / "clip.mp4"), provider_name="funasr", model="paraformer-zh")


async def test_real_whisper_provider_degrades_to_asrerror(tmp_path):
    with pytest.raises(AsrError):
        await transcribe_video(str(tmp_path / "clip.mp4"), provider_name="whisper", model="small")


# ── 真实 provider 输出解析（白盒，钉死格式转换契约；真实形状待 Task 7 集成校准）──


def test_rows_from_funasr_prefers_sentence_info_segments():
    # 真机键名是 `sentence_info`（spec 2026-09-28 §2 D2 校准；`sentence` 键从不出现）。
    result = [{"text": "你好世界", "sentence_info": [{"start": 0, "end": 1200, "text": "你好"}, {"start": 1200, "end": 2500, "text": "世界"}]}]
    assert _rows_from_funasr(result) == [(0, 1200, "你好"), (1200, 2500, "世界")]


def test_rows_from_funasr_falls_back_to_utterance_timestamp():
    result = [{"text": "你好", "timestamp": [[0, 600], [600, 1200]]}]
    assert _rows_from_funasr(result) == [(0, 1200, "你好")]  # 首字 start → 末字 end


def test_rows_from_funasr_returns_empty_without_any_timing():
    assert _rows_from_funasr([{"text": "你好"}]) == []  # 不抛：降级语义不变


# ── "整段一行"信号（spec 2026-09-28 §4.2：单段覆盖全片 ⇒ 口述只落一张卡）─────────


async def test_transcribe_video_warns_when_one_segment_covers_the_file(tmp_path, caplog):
    fake = _FakeProvider([(0.0, 18.0, "整段")], unit="s")
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"placeholder")

    with caplog.at_level(logging.WARNING):
        segments = await transcribe_video(str(target), provider=fake, model="paraformer-zh", duration_ms=18_000)

    assert len(segments) == 1
    assert any("整段" in record.getMessage() for record in caplog.records)


async def test_transcribe_video_stays_quiet_when_the_file_has_many_segments(tmp_path, caplog):
    fake = _FakeProvider([(0.0, 9.0, "前"), (9.0, 18.0, "后")], unit="s")
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"placeholder")

    with caplog.at_level(logging.WARNING):
        await transcribe_video(str(target), provider=fake, model="paraformer-zh", duration_ms=18_000)

    assert not [record for record in caplog.records if "整段" in record.getMessage()]


async def test_transcribe_video_cannot_judge_without_a_duration(tmp_path, caplog):
    fake = _FakeProvider([(0.0, 18.0, "整段")], unit="s")
    target = tmp_path / "clip.mp4"
    target.write_bytes(b"placeholder")

    with caplog.at_level(logging.WARNING):
        await transcribe_video(str(target), provider=fake, model="paraformer-zh")  # 没给时长 ⇒ 不判、不报

    assert not [record for record in caplog.records if "整段" in record.getMessage()]


def test_rows_from_whisper_extracts_start_end_text():
    result = {"segments": [{"start": 0.0, "end": 2.5, "text": " hello "}, {"start": 2.5, "end": 4.0, "text": "world"}]}
    assert _rows_from_whisper(result) == [(0.0, 2.5, " hello "), (2.5, 4.0, "world")]  # 原文不 strip，规整在 normalize


# ── 调用侧带 VAD（spec 2026-09-28 §2 D1/D3）─────────────────────────────


def _install_fake_funasr(monkeypatch, calls: list[dict]) -> None:
    """把 `funasr.AutoModel` 换成记录构造参数的桩：不真加载模型，秒级返回。"""
    module = types.ModuleType("funasr")

    class _FakeAutoModel:
        def __init__(self, **kwargs):
            calls.append(kwargs)

        def generate(self, **kwargs):  # noqa: ARG002 - 桩只关心构造参数
            return [{"text": "你好", "timestamp": [[0, 600], [600, 1200]]}]

    module.AutoModel = _FakeAutoModel
    monkeypatch.setitem(sys.modules, "funasr", module)


def test_funasr_provider_asks_for_vad_and_speakers_but_never_punc(monkeypatch):
    calls: list[dict] = []
    _install_fake_funasr(monkeypatch, calls)

    rows = FunAsrProvider(model="paraformer-zh").transcribe("clip.mp4")

    assert calls[0]["model"] == "paraformer-zh"
    assert calls[0]["disable_update"] is True
    assert calls[0]["vad_model"] == "fsmn-vad"
    assert calls[0]["spk_model"] == "cam++"  # 顺带产出 sentence_info（VAD 段 + spk）
    assert "punc_model" not in calls[0]  # D1 不补标点
    assert rows == [(0, 1200, "你好")]  # 带配件不影响取数路径


@pytest.mark.parametrize("model", ["paraformer-zh-streaming", "Whisper-large-v3"])
def test_funasr_provider_skips_companions_for_the_exception_list(monkeypatch, model):
    calls: list[dict] = []
    _install_fake_funasr(monkeypatch, calls)

    FunAsrProvider(model=model).transcribe("clip.mp4")

    # 流式按 chunk 调；托管 whisper 走自己的路径 —— VAD 与 cam++ 两个都不给。
    assert "vad_model" not in calls[0]
    assert "spk_model" not in calls[0]


# ── 服务档：路由 / 地址守卫（spec 2026-09-28 D5 + D4）────────────────────


def test_resolve_provider_routes_the_service_tiers():
    assert isinstance(resolve_provider("dashscope", model="qwen-audio-3.1-asr-flash", base_url="https://dashscope.aliyuncs.com"), DashScopeAsrProvider)
    assert isinstance(resolve_provider("openai-audio", model="whisper-1", base_url="http://127.0.0.1:8000/v1"), OpenAiAudioProvider)
    assert isinstance(resolve_provider("funasr", model="paraformer-zh"), FunAsrProvider)


@pytest.mark.parametrize("name", ["dashscope", "openai-audio"])
@pytest.mark.parametrize("base_url", [None, "", "   "])
def test_the_service_rows_need_an_address(name, base_url):
    """09-25 D1 乙「连回落删」：地址留空不是"用厂商默认"，是配置错误。"""
    with pytest.raises(RagConfigurationError):
        resolve_provider(name, model="m", base_url=base_url)


def test_the_in_process_rows_need_no_address():
    assert isinstance(resolve_provider("funasr", model="paraformer-zh"), FunAsrProvider)
    assert isinstance(resolve_provider("whisper", model="small"), WhisperProvider)


def test_long_audio_stays_on_the_local_leg():
    """D6：服务档只吃 ≤5 分钟（同步 + base64），更长的整段留在本地腿。"""
    assert resolve_leg_provider("dashscope", duration_ms=6 * 60 * 1000) == "funasr"
    assert resolve_leg_provider("openai-audio", duration_ms=6 * 60 * 1000) == "funasr"
    # 边界与未知时长都不换：5 分钟整仍在服务档；拿不到时长就不判。
    assert resolve_leg_provider("dashscope", duration_ms=5 * 60 * 1000) == "dashscope"
    assert resolve_leg_provider("dashscope", duration_ms=None) == "dashscope"
    assert resolve_leg_provider("whisper", duration_ms=6 * 60 * 1000) == "whisper"


# ── 服务档：请求形状（spec §5.4 的三条硬事实）───────────────────────────

_DASHSCOPE_ASR_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"


def _sync_client(recorded: list[httpx.Request], *, json_body: dict, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(status, json=json_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


_TWO_SENTENCES = {
    "output": {
        "sentence": {"begin_time": 0, "end_time": 2400, "text": "甲乙"},
        "sentences": [
            {"begin_time": 0, "end_time": 1200, "text": "甲"},
            {"begin_time": 1200, "end_time": 2400, "text": "乙"},
        ],
    }
}


def test_dashscope_sends_the_documented_request(tmp_path):
    recorded: list[httpx.Request] = []
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x01\x02")

    provider = DashScopeAsrProvider(
        model="qwen-audio-3.1-asr-flash",
        base_url="https://dashscope.aliyuncs.com",
        api_key="sk-asr",
        client=_sync_client(recorded, json_body=_TWO_SENTENCES),
    )
    rows = provider.transcribe(str(clip))

    request = recorded[0]
    assert str(request.url) == _DASHSCOPE_ASR_URL
    assert request.headers["authorization"] == "Bearer sk-asr"
    body = json.loads(request.content)
    assert body["model"] == "qwen-audio-3.1-asr-flash"
    # §5.4 ①：format 必填（缺了服务端秒回 400「format is empty」）——填文件后缀即可。
    assert body["parameters"]["format"] == "mp4"
    # §5.4 ②：说话人开关是**分段开关**，且必须在 parameters 顶层（塞 asr_options 里无效）。
    assert body["parameters"]["speaker_diarization_enabled"] is True
    assert "asr_options" not in body["parameters"]
    audio = body["input"]["messages"][0]["content"][0]["audio"]
    assert audio.startswith("data:") and ";base64," in audio
    assert rows == [(0, 1200, "甲"), (1200, 2400, "乙")]


def test_openai_audio_posts_multipart_and_reads_segments(tmp_path):
    recorded: list[httpx.Request] = []
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x01\x02")
    reply = {"segments": [{"start": 0.0, "end": 1.2, "text": "甲"}, {"start": 1.2, "end": 2.4, "text": "乙"}]}

    provider = OpenAiAudioProvider(model="whisper-1", base_url="http://127.0.0.1:8000/v1", api_key="sk-x", client=_sync_client(recorded, json_body=reply))
    rows = provider.transcribe(str(clip))

    request = recorded[0]
    # 通用协议：`/v1` 不写两遍（join_endpoint 的既有规则）。
    assert str(request.url) == "http://127.0.0.1:8000/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer sk-x"
    # verbose_json 是段级时间戳的前提——默认的 json 只给文本。
    assert b'name="response_format"' in request.content and b"verbose_json" in request.content
    assert b'name="model"' in request.content
    assert rows == [(0.0, 1.2, "甲"), (1.2, 2.4, "乙")]


# ── 服务档：抽取（sentences[] 优先 / utterances[] 回退 / 空或单段 = 没答案）──


def test_rows_from_dashscope_prefers_sentences():
    assert _rows_from_dashscope(_TWO_SENTENCES) == [(0, 1200, "甲"), (1200, 2400, "乙")]


def test_rows_from_dashscope_reads_the_doubly_nested_copy():
    """实测里同一份结果挂在 `output.*` 与 `output.output.*` 两层（§5.4 ③）。"""
    nested = {"output": {"output": _TWO_SENTENCES["output"]}}
    assert _rows_from_dashscope(nested) == [(0, 1200, "甲"), (1200, 2400, "乙")]


def test_rows_from_dashscope_falls_back_to_utterances():
    """火山形状（随投递二期）；回退路径先钉住，两种拼法都认。"""
    result = {
        "output": {
            "utterances": [
                {"start_time": 0, "end_time": 1200, "text": "甲"},
                {"begin_time": 1200, "end_time": 2400, "text": "乙"},
            ]
        }
    }
    assert _rows_from_dashscope(result) == [(0, 1200, "甲"), (1200, 2400, "乙")]


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"output": {}},
        {"output": {"sentences": []}},
        # 单段（哪怕带真时间戳）也算"没答案"：硬要求 ③——服务端没分段时不要假装有一行。
        {"output": {"sentences": [{"begin_time": 0, "end_time": 9000, "text": "整段"}]}},
        {"output": {"sentence": {"begin_time": 0, "end_time": 9000, "text": "整段"}}},
    ],
)
def test_a_single_or_empty_dashscope_result_is_no_answer(result):
    assert _rows_from_dashscope(result) == []


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"segments": []},
        {"segments": [{"start": 0.0, "end": 9.0, "text": "整段"}]},
    ],
)
def test_a_single_or_empty_openai_result_is_no_answer(result):
    assert _rows_from_openai_audio(result) == []


def test_rows_from_openai_audio_keeps_a_multi_segment_transcript():
    result = {"segments": [{"start": 0.0, "end": 1.0, "text": "甲"}, {"start": 1.0, "end": 2.0, "text": "乙"}]}
    assert _rows_from_openai_audio(result) == [(0.0, 1.0, "甲"), (1.0, 2.0, "乙")]


# ── 服务档：降级（D8：网络失败 / 超时 / 401 ⇒ AsrError，不加新状态值）──────


@pytest.mark.parametrize("failure", ["connect", "timeout", "401"])
async def test_a_service_failure_degrades_to_asrerror(tmp_path, failure):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x01\x02")

    if failure == "401":
        client = _sync_client([], json_body={"code": "InvalidApiKey", "message": "blocked"}, status=401)
    else:

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request) if failure == "timeout" else httpx.ConnectError("no route", request=request)

        client = httpx.Client(transport=httpx.MockTransport(handler))

    provider = DashScopeAsrProvider(model="m", base_url="https://dashscope.aliyuncs.com", api_key="sk", client=client)
    with pytest.raises(AsrError):
        await transcribe_video(str(clip), provider=provider, model="paraformer-zh")


# ── 服务档：签名把地址与钥匙送到 provider（worker 侧的同一条路）──────────


async def test_transcribe_video_carries_the_address_and_key(tmp_path, monkeypatch):
    recorded: list[httpx.Request] = []
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x01\x02")

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=_TWO_SENTENCES)

    real_client = httpx.Client  # 捕获真类，否则桩自己会再进桩（无限递归）
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))

    segments = await transcribe_video(
        str(clip),
        provider_name="dashscope",
        model="qwen-audio-3.1-asr-flash",
        base_url="https://dashscope.aliyuncs.com",
        api_key="sk-asr",
    )

    assert str(recorded[0].url) == _DASHSCOPE_ASR_URL
    assert recorded[0].headers["authorization"] == "Bearer sk-asr"
    assert segments == [TranscriptSegment(0, 1200, "甲"), TranscriptSegment(1200, 2400, "乙")]
