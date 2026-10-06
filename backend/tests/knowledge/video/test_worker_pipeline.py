"""Video worker pipeline integration tests (spec 2026-09-08 §2/§3, plan Task 7).

视频文档在 ``KnowledgeIndexWorker`` 里的全腿编排：``probe → asr → segment →
keyframe+ocr → caption → materialize`` 落入现有 ``vector → graph → wiki`` 腿。
所有媒体腿用 fake（monkeypatch worker 模块级函数），DB 用真实 SQLite
（``session_factory``）——测的是编排契约：legs / path_status / degraded 矩阵、
progress 腿权重、resume 只跑 pending 镜头、删除级联，而非各腿内部逻辑（Task 3–6
单测已覆盖）。

ASR→镜头桶投影纯函数（spec §3 时间轴对齐规则）单独逐条钉死：最大重叠占比归桶、
同重叠归较早桶、桶内 ``start_ms`` 升序拼接、零重叠段丢弃、静默镜头缺席。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from qdrant_client.models import SparseVector

from deerflow.knowledge.embedder import EmbeddingResult
from deerflow.knowledge.store import KnowledgeStore
from deerflow.knowledge.video.asr import AsrError, TranscriptSegment
from deerflow.knowledge.video.captioner import CaptionOutcome
from deerflow.knowledge.video.probe import VideoProbe, VideoUndecodableError
from deerflow.knowledge.video.store import VideoShotStore
from deerflow.knowledge.worker import KnowledgeIndexWorker, assign_transcript_to_shots

# ── ASR→镜头桶投影纯函数（spec §3 时间轴对齐规则，materialize 腿核心）──────────


def test_assign_transcript_max_overlap_wins():
    """每条转录段归入重叠占比最大的镜头（保句子完整性，检索单元友好）。"""
    shots = [(0, 5000), (5000, 10000)]
    # 段 (1000,8000) len=7000：与镜头0重叠 4000（0.571）、与镜头1重叠 3000（0.429）
    segments = [TranscriptSegment(start_ms=1000, end_ms=8000, text="跨镜长句")]
    result = assign_transcript_to_shots(segments, shots)
    assert result == {0: "跨镜长句"}  # 归占比更大的镜头0，镜头1 无


def test_assign_transcript_tie_goes_to_earlier_shot():
    """重叠占比相同 → 归较早镜头（确定性 tie-break）。"""
    shots = [(0, 5000), (5000, 10000)]
    # 段 (3000,7000) 恰跨中点：与两镜各重叠 2000（占比均 0.5）
    segments = [TranscriptSegment(start_ms=3000, end_ms=7000, text="骑墙句")]
    result = assign_transcript_to_shots(segments, shots)
    assert result == {0: "骑墙句"}


def test_assign_transcript_concatenates_in_ascending_order():
    """同镜头多段按 ``start_ms`` 升序拼接（输入乱序也稳定）。"""
    shots = [(0, 5000)]
    segments = [
        TranscriptSegment(start_ms=2000, end_ms=4000, text="世界"),
        TranscriptSegment(start_ms=0, end_ms=2000, text="你好"),
    ]
    result = assign_transcript_to_shots(segments, shots)
    assert result == {0: "你好 世界"}  # 升序 + 空格拼接（口述段保持单行）


def test_assign_transcript_drops_zero_overlap_segments():
    """与所有镜头重叠均为 0 的段丢弃（防御），不落任何桶。"""
    shots = [(0, 5000), (5000, 10000)]
    segments = [
        TranscriptSegment(start_ms=0, end_ms=4000, text="镜内"),
        TranscriptSegment(start_ms=11000, end_ms=12000, text="轴外越界"),
    ]
    result = assign_transcript_to_shots(segments, shots)
    assert result == {0: "镜内"}
    assert "轴外越界" not in result.get(0, "") + result.get(1, "")


def test_assign_transcript_silent_shot_is_absent():
    """无语音镜头不出现在结果里（worker 用 .get(index, '') 补空 → 卡口述段（无））。"""
    shots = [(0, 5000), (5000, 10000)]
    segments = [TranscriptSegment(start_ms=0, end_ms=4000, text="只有前镜")]
    result = assign_transcript_to_shots(segments, shots)
    assert 1 not in result
    assert result[0] == "只有前镜"


# ── fake 全腿基建 ─────────────────────────────────────────────────────────


class FakeEmbedder:
    batch_size = 20

    async def embed(self, texts, *, text_type: str = "document"):
        return [EmbeddingResult(dense=[0.01 * (i + 1)] * 1024, sparse=SparseVector(indices=[i + 1], values=[0.5])) for i, _ in enumerate(texts)]


class FakeLLM:
    """空抽取——视频腿测试关注编排，实体抽取由 test_worker.py 覆盖。"""

    async def ainvoke(self, messages):
        return SimpleNamespace(content='{"entities": [], "relations": []}')


def _vector_store_mock() -> MagicMock:
    vs = MagicMock()
    vs.init_collections = AsyncMock()
    vs.upsert_chunks = AsyncMock(return_value=0)
    vs.upsert_entities = AsyncMock(return_value=0)
    vs.set_chunk_entities = AsyncMock()
    vs.delete_by_doc = AsyncMock()
    vs.delete_entities = AsyncMock()
    vs.upsert_wiki_entries = AsyncMock(return_value=0)
    vs.get_entity_vectors = AsyncMock(return_value={})
    return vs


def _video_config(**overrides):
    """受控 rag.video 配置（max_shot=5s → 10s 视频切 2 镜头，不触发兜底再切）。"""
    defaults = {
        "max_shot_seconds": 5.0,
        "fallback_window_seconds": 10.0,
        "keyframes_per_shot": 1,
        "asr_provider": "funasr",
        "asr_model": "paraformer-zh",
        "card_text_mode": "full",
    }
    video = SimpleNamespace(**{**defaults, **overrides})
    # The ASR leg's connection info is top-level on `rag` (① 乙, 2026-09-29), not inside `video`.
    return SimpleNamespace(rag=SimpleNamespace(video=video, worker_concurrency=2, extract_concurrency=1, vlm_model="test-vlm", asr_base_url=None, asr_api_key=None))


def _fake_legs(
    monkeypatch,
    *,
    probe: VideoProbe | None = None,
    probe_error: Exception | None = None,
    transcript: list[TranscriptSegment] | None = None,
    asr_error: Exception | None = None,
    cuts: list[float] | None = None,
    cuts_error: Exception | None = None,
    keyframes: dict[int, str | None] | None = None,
    caption_frames: list[bytes] | None = None,
    screen_text: str | None = None,
    caption: CaptionOutcome | None = None,
    config: SimpleNamespace | None = None,
) -> dict[str, int]:
    """monkeypatch worker 模块级视频腿函数为 fake；返回各腿调用计数（resume 断言用）。

    默认 fixture：duration=10000ms、cuts=[5000] → 2 镜头 ``[(0,5000),(5000,10000)]``；
    ASR 段 (0,4000)→镜头0、(6000,9000)→镜头1；每镜头有关键帧 + 屏幕文字 + 场景描述。
    """
    import deerflow.knowledge.worker as w

    calls = {"probe": 0, "asr": 0, "cuts": 0, "keyframes": 0, "caption_frames": 0, "screen_text": 0, "caption": 0}

    async def _probe(path, **kw):
        calls["probe"] += 1
        if probe_error is not None:
            raise probe_error
        return probe or VideoProbe(duration_ms=10000, width=1920, height=1080, has_video_stream=True, has_audio_stream=True)

    async def _asr(path, **kw):
        calls["asr"] += 1
        if asr_error is not None:
            raise asr_error
        if transcript is not None:
            return transcript
        return [TranscriptSegment(start_ms=0, end_ms=4000, text="你好世界"), TranscriptSegment(start_ms=6000, end_ms=9000, text="第二句")]

    def _cuts(path):
        calls["cuts"] += 1
        if cuts_error is not None:
            raise cuts_error
        return cuts if cuts is not None else [5000.0]

    async def _keyframes(video_path, shots, doc_dir, **kw):
        calls["keyframes"] += 1
        if keyframes is not None:
            return keyframes
        return {i: f"frames/shot_{i:04d}.jpg" for i in range(len(shots))}

    async def _caption_frames(video_path, start_ms, end_ms, **kw):
        calls["caption_frames"] += 1
        return caption_frames if caption_frames is not None else [b"\xff\xd8frame"]

    async def _screen_text(shot_frames, **kw):
        calls["screen_text"] += 1
        return CaptionOutcome(captions={i: (screen_text if screen_text is not None else "屏幕文字") for i in shot_frames}, failed=0, degraded=False)

    async def _caption(shot_frames, **kw):
        calls["caption"] += 1
        if caption is not None:
            return caption
        return CaptionOutcome(captions={i: f"场景描述{i}" for i in shot_frames}, failed=0, degraded=False)

    monkeypatch.setattr(w, "probe_video", _probe)
    monkeypatch.setattr(w, "transcribe_video", _asr)
    monkeypatch.setattr(w, "_detect_scene_cuts", _cuts)
    monkeypatch.setattr(w, "extract_keyframes", _keyframes)
    monkeypatch.setattr(w, "extract_caption_frames", _caption_frames)
    monkeypatch.setattr(w, "screen_text_shots", _screen_text)
    monkeypatch.setattr(w, "caption_shots", _caption)
    monkeypatch.setattr(w, "get_app_config", lambda: config or _video_config())
    return calls


def _worker(store, **kwargs) -> KnowledgeIndexWorker:
    kwargs.setdefault("vector_store", _vector_store_mock())
    kwargs.setdefault("embedder", FakeEmbedder())
    kwargs.setdefault("llm", FakeLLM())
    kwargs.setdefault("concurrency", 2)
    return KnowledgeIndexWorker(store=store, **kwargs)


async def _video_doc(store, tmp_path, *, doc_id="doc-v", kb_id="kb-1", name="clip.mp4"):
    """造一个视频文档行 + per-doc 存储目录（storage_path 后缀 .mp4 触发视频分支）。"""
    doc_dir = tmp_path / "knowledge" / kb_id / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    storage = doc_dir / name
    storage.write_bytes(b"video-placeholder")
    await store.create_document(doc_id=doc_id, kb_id=kb_id, uploader_id="user-1", name=name, size_bytes=17, storage_path=str(storage))
    return doc_id, str(storage), doc_dir


# ── 全腿编排：legs / path_status / progress / chunks+shots 落库 ──────────────


@pytest.mark.asyncio
async def test_video_full_pipeline_to_ready(session_factory, tmp_path, monkeypatch):
    """2 镜头 fixture 全腿跑通 → ready；video_shots + 镜头卡 chunks 落库，落入 vector 腿。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch)
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    assert doc["progress_percent"] == 100
    assert doc["path_status"] == {"asr": "done", "segment": "done", "caption": "done", "vector": "done", "graph": "done"}

    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert [s["shot_index"] for s in shots] == [0, 1]
    assert shots[0]["start_ms"] == 0 and shots[0]["end_ms"] == 5000
    assert shots[1]["start_ms"] == 5000 and shots[1]["end_ms"] == 10000
    assert shots[0]["caption_status"] == "done"
    assert shots[0]["asr_text"] == "你好世界"  # 段 (0,4000) 归镜头0
    assert shots[1]["asr_text"] == "第二句"  # 段 (6000,9000) 归镜头1
    assert shots[0]["ocr_text"] == "屏幕文字"
    assert shots[0]["caption"] == "场景描述0"
    assert shots[0]["keyframe_path"] == "frames/shot_0000.jpg"

    chunks = await store.list_chunks(doc_id, limit=10)
    assert len(chunks) == 2
    assert chunks[0]["chunk_id"] == f"{doc_id}#0000"
    assert chunks[0]["chunk_index"] == 0
    # 冻结卡正文（嵌入文本契约：无时间码头，spec §3）
    assert chunks[0]["text"] == "场景：场景描述0\n口述：你好世界\n屏幕文字：屏幕文字"
    assert chunks[0]["heading_path"] == ["clip.mp4", "镜头 #0"]
    assert chunks[0]["page"] is None
    # materialize 后镜头卡作为普通 chunk 落入现有 vector 腿
    assert worker._vector_store.upsert_chunks.await_count >= 1


@pytest.mark.asyncio
async def test_video_path_status_extends_legs(session_factory, tmp_path, monkeypatch):
    """path_status 扩腿 {asr, segment, caption} + 现有 {vector, graph}，全程可见。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch)
    snapshots: list[dict[str, str]] = []
    original = store.update_document_status

    async def spy(doc_id_, status, **kwargs):
        result = await original(doc_id_, status, **kwargs)
        if result is not None and kwargs.get("path_status") is not None:
            snapshots.append(dict(result["path_status"]))
        return result

    store.update_document_status = spy  # type: ignore[method-assign]
    worker = _worker(store)

    await worker.process_document(doc_id)

    assert snapshots, "视频文档必须写 path_status"
    # 视频腿在解析阶段即初始化（悬停全程可用），文本腿不含视频键
    first = snapshots[0]
    assert {"asr", "segment", "caption", "vector", "graph"} <= set(first)
    # 终态快照五腿齐 done
    assert snapshots[-1] == {"asr": "done", "segment": "done", "caption": "done", "vector": "done", "graph": "done"}


@pytest.mark.asyncio
async def test_video_progress_weights_are_monotonic(session_factory, tmp_path, monkeypatch):
    """progress 腿权重 asr30/segment5/caption35/materialize5 累积单调，终点 100。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch)
    progress: list[int] = []
    original = store.update_document_status

    async def spy(doc_id_, status, **kwargs):
        if kwargs.get("progress_percent") is not None:
            progress.append(kwargs["progress_percent"])
        return await original(doc_id_, status, **kwargs)

    store.update_document_status = spy  # type: ignore[method-assign]
    worker = _worker(store)

    await worker.process_document(doc_id)

    assert progress == sorted(progress), "progress 必须单调不回退"
    assert progress[-1] == 100
    assert 30 in progress  # asr 腿权重
    assert 35 in progress  # +segment
    assert 70 in progress  # +caption
    assert 75 in progress  # +materialize


# ── degraded 矩阵（spec §2：单腿降级不阻断，文档仍 ready）──────────────────────


@pytest.mark.asyncio
async def test_video_asr_failure_degrades_but_reaches_ready(session_factory, tmp_path, monkeypatch):
    """asr 整腿失败 → asr=failed，口述段写「（ASR 失败）」，文档仍 ready（降级）。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch, asr_error=AsrError("FunASR 未安装"))
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    assert doc["path_status"]["asr"] == "failed"
    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert shots[0]["asr_text"] == "（ASR 失败）"
    chunks = await store.list_chunks(doc_id, limit=10)
    assert "口述：（ASR 失败）" in chunks[0]["text"]


@pytest.mark.asyncio
async def test_video_segment_failure_falls_back_to_windows(session_factory, tmp_path, monkeypatch):
    """segment 检测器失败 → 回退等距窗（fallback_window=10s → 1 镜头），segment=degraded。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch, cuts_error=RuntimeError("scenedetect 未安装"))
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    assert doc["path_status"]["segment"] == "degraded"
    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert len(shots) == 1  # fallback_windows(10000, 10000) = [(0,10000)]
    assert shots[0]["start_ms"] == 0 and shots[0]["end_ms"] == 10000


@pytest.mark.asyncio
async def test_video_caption_degraded_marks_leg(session_factory, tmp_path, monkeypatch):
    """caption >30% 失败 → caption=degraded；caption 空但 asr/ocr 有 → 卡仍产、状态 failed。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch, caption=CaptionOutcome(captions={0: "", 1: ""}, failed=2, degraded=True))
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    assert doc["path_status"]["caption"] == "degraded"
    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert shots[0]["caption_status"] == "failed"  # caption 空但 asr/ocr 非空
    chunks = await store.list_chunks(doc_id, limit=10)
    assert len(chunks) == 2
    assert "场景：（无）" in chunks[0]["text"]


@pytest.mark.asyncio
async def test_video_probe_failure_fails_loudly(session_factory, tmp_path, monkeypatch):
    """probe 不可解码 → 文档 failed（响亮失败，对齐 EmptyParseResultError），视频腿全 failed。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(monkeypatch, probe_error=VideoUndecodableError("文件不可解码为视频"))
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "failed"
    assert "不可解码" in (doc["error"] or "")
    # 硬失败时未达终态的视频腿标 failed（对齐现有 failed_legs 逻辑）
    assert doc["path_status"]["asr"] == "failed"
    assert doc["path_status"]["segment"] == "failed"
    assert await VideoShotStore(session_factory).list_shots(doc_id) == []  # 未 materialize


@pytest.mark.asyncio
async def test_video_empty_shot_produces_no_chunk(session_factory, tmp_path, monkeypatch):
    """三路全空镜头 → caption_status=empty、不产 chunk（计数可视），其余镜头照常。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(
        monkeypatch,
        transcript=[TranscriptSegment(start_ms=0, end_ms=4000, text="只有前镜")],  # 镜头1 无 asr
        keyframes={0: "frames/shot_0000.jpg", 1: None},  # 镜头1 抽帧失败 → 无 ocr
        caption=CaptionOutcome(captions={0: "场景0", 1: ""}, failed=0, degraded=False),  # 镜头1 无 caption
    )
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert shots[1]["caption_status"] == "empty"
    chunks = await store.list_chunks(doc_id, limit=10)
    assert len(chunks) == 1  # 只镜头0 产卡
    assert chunks[0]["chunk_id"] == f"{doc_id}#0000"


@pytest.mark.asyncio
async def test_video_all_empty_shots_fail_as_no_indexable_content(session_factory, tmp_path, monkeypatch):
    """全镜头三路俱空 → 零切片 ⇒ 文档 failed（「无可索引内容」，RFC §5.2
    表行 4），不再静默 ready；空镜头行保留、wiki 不启动。"""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    _fake_legs(
        monkeypatch,
        transcript=[],
        keyframes={0: None, 1: None},
        caption=CaptionOutcome(captions={0: "", 1: ""}, failed=0, degraded=False),
    )
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "failed"
    assert "无可索引内容" in (doc["error"] or "")
    assert doc["chunk_count"] in (None, 0)
    assert await store.list_chunks(doc_id, limit=10) == []
    assert doc["path_status"] == {"asr": "done", "segment": "done", "caption": "done", "vector": "failed", "graph": "done"}
    shots = await VideoShotStore(session_factory).list_shots(doc_id)
    assert all(shot["caption_status"] == "empty" for shot in shots)


# ── resume：重入只跑 pending 镜头（spec §2 caption_status 状态机）───────────────


@pytest.mark.asyncio
async def test_video_resume_only_reruns_pending_shots(session_factory, tmp_path, monkeypatch):
    """video_shots 骨架已在（镜头0 done、镜头1 pending）→ 重入跳过 probe/asr/segment/
    keyframe，只对 pending 镜头跑 caption，materialize 重建全量 chunks。"""
    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    # 模拟上次崩溃在 caption 腿中途：镜头0 已 caption done，镜头1 仍 pending
    await vstore.bulk_upsert_shots(
        doc_id,
        kb_id="kb-1",
        shots=[
            {"shot_index": 0, "start_ms": 0, "end_ms": 5000, "keyframe_path": "frames/shot_0000.jpg", "asr_text": "你好", "ocr_text": "屏幕A", "caption": "场景0", "caption_status": "done"},
            {"shot_index": 1, "start_ms": 5000, "end_ms": 10000, "keyframe_path": "frames/shot_0001.jpg", "asr_text": "世界", "ocr_text": "屏幕B", "caption": "", "caption_status": "pending"},
        ],
    )
    await store.update_document_status(doc_id, "parsing")  # 崩溃时状态未进 indexing

    seen_caption_indexes: list[int] = []

    async def _caption_spy(shot_frames, **kw):
        seen_caption_indexes.extend(sorted(shot_frames.keys()))
        return CaptionOutcome(captions={i: "场景1新" for i in shot_frames}, failed=0, degraded=False)

    calls = _fake_legs(monkeypatch)
    import deerflow.knowledge.worker as w

    monkeypatch.setattr(w, "caption_shots", _caption_spy)
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "ready"
    # 前置腿（probe/asr/segment/keyframe）全部跳过——骨架已持久化
    assert calls["probe"] == 0
    assert calls["asr"] == 0
    assert calls["cuts"] == 0
    assert calls["keyframes"] == 0
    # caption 只对 pending 的镜头1 跑
    assert seen_caption_indexes == [1]
    shots = await vstore.list_shots(doc_id)
    assert shots[0]["caption"] == "场景0"  # done 镜头未被重跑覆盖
    assert shots[1]["caption"] == "场景1新"
    assert shots[1]["caption_status"] == "done"
    # materialize 用 video_shots 全量数据重建两镜头卡
    chunks = await store.list_chunks(doc_id, limit=10)
    assert len(chunks) == 2
    assert chunks[0]["text"] == "场景：场景0\n口述：你好\n屏幕文字：屏幕A"
    assert chunks[1]["text"] == "场景：场景1新\n口述：世界\n屏幕文字：屏幕B"


# ── 删除级联（spec §9 存储膨胀缓解：video_shots 随文档删除）────────────────────


@pytest.mark.asyncio
async def test_delete_document_cascades_video_shots(session_factory, tmp_path):
    """store.delete_document 级联删 video_shots 行（帧目录由 service 层 _remove_dir 覆盖）。"""
    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-v", kb_id="kb-1", uploader_id="user-1", name="clip.mp4", size_bytes=17, storage_path=str(tmp_path / "clip.mp4"))
    await vstore.bulk_upsert_shots("doc-v", kb_id="kb-1", shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000}, {"shot_index": 1, "start_ms": 5000, "end_ms": 9000}])
    await store.insert_chunks([{"chunk_id": "doc-v#0000", "doc_id": "doc-v", "kb_id": "kb-1", "chunk_index": 0, "text": "场景：x", "heading_path": [], "page": None, "token_count": 3}])

    assert await store.delete_document("doc-v") is True

    assert await vstore.list_shots("doc-v") == []  # video_shots 级联删
    assert await store.list_chunks("doc-v", limit=10) == []
    assert await store.get_document("doc-v") is None


@pytest.mark.asyncio
async def test_delete_kb_cascades_video_shots(session_factory):
    """删 KB 也级联清 video_shots（避免孤儿行，与 delete_document 对称）。"""
    store = KnowledgeStore(session_factory)
    vstore = VideoShotStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    await store.create_document(doc_id="doc-v", kb_id="kb-1", uploader_id="user-1", name="clip.mp4", size_bytes=17, storage_path="/tmp/clip.mp4")
    await vstore.bulk_upsert_shots("doc-v", kb_id="kb-1", shots=[{"shot_index": 0, "start_ms": 0, "end_ms": 5000}])

    assert await store.delete_kb("kb-1") is True

    assert await vstore.list_shots("doc-v") == []


@pytest.mark.asyncio
async def test_video_asr_model_missing_fails_loudly(session_factory, tmp_path, monkeypatch):
    """A-1 (spec 2026-09-30 D1): an undeclared asr_model is a configuration error, not a
    silent vendor pick — the leg entry refuses before any transcription attempt."""
    store = KnowledgeStore(session_factory)
    await store.create_kb(kb_id="kb-1", owner_id="user-1", name="k")
    doc_id, _storage, _doc_dir = await _video_doc(store, tmp_path)
    calls = _fake_legs(monkeypatch, config=_video_config(asr_model=None))
    worker = _worker(store)

    await worker.process_document(doc_id)

    doc = await store.get_document(doc_id)
    assert doc["status"] == "failed"
    assert "asr_model" in (doc["error"] or "")
    assert calls["asr"] == 0  # the refusal precedes any transcription attempt
