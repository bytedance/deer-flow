"""Tests for the no-cloud CI's record/replay layer (RFC v3 §8.2).

Pure coverage: key derivation per call kind (both dialects), recording IO
(loud on conflicts), the capture wrapper, the material fingerprint, and the
replay service's serve/miss behavior. No network, no cloud.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # backend/tests
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend (scripts/)

from rag_eval_ci.capture import Recorder, install  # noqa: E402
from rag_eval_ci.replay import (  # noqa: E402
    UnsupportedReplayRequest,
    key_for_request,
    load_recording,
    material_fingerprint,
    remap_rerank_response,
)

DASHSCOPE_EMBED_PATH = "/api/v1/services/embeddings/text-embedding/text-embedding"
RERANK_PATH = "/compatible-api/v1/reranks"
CAPTION_PATH = "/chat/completions"


class TestKeyDerivation:
    def test_embed_dashscope_and_openai_shapes_agree(self):
        dashscope = {"model": "m1", "input": {"texts": ["a", "b"]}, "parameters": {"output_type": "dense&sparse"}}
        openai = {"model": "m1", "input": ["a", "b"]}

        assert key_for_request(DASHSCOPE_EMBED_PATH, dashscope) == key_for_request("/v1/embeddings", openai)

    def test_embed_key_is_order_sensitive(self):
        a = key_for_request(DASHSCOPE_EMBED_PATH, {"model": "m1", "input": {"texts": ["a", "b"]}})
        b = key_for_request(DASHSCOPE_EMBED_PATH, {"model": "m1", "input": {"texts": ["b", "a"]}})

        assert a != b

    def test_rerank_key_uses_deciding_fields(self):
        base = {"model": "r1", "query": "q", "documents": ["d1", "d2"], "top_n": 2, "instruct": None}

        assert key_for_request(RERANK_PATH, base) == key_for_request("/rerank", dict(base))
        assert key_for_request(RERANK_PATH, base) != key_for_request(RERANK_PATH, {**base, "top_n": 1})
        assert key_for_request(RERANK_PATH, base) != key_for_request(RERANK_PATH, {**base, "query": "other"})

    def test_rerank_key_ignores_the_candidate_population(self):
        # 候选集在平分截断处会抖动成员（实测同一查询两次分别给 18/17 个文档），
        # 而重排分是 (query, document) 的独立函数 ⇒ 键不含文档集；
        # 真实漂移由回放侧的重叠率守卫拦截（见 TestRerankRemap）。
        base = {"model": "r1", "query": "q", "documents": ["d1", "d2", "d3"], "top_n": 3, "instruct": None}

        assert key_for_request(RERANK_PATH, base) == key_for_request(RERANK_PATH, {**base, "documents": ["d3", "d1", "d2"]})
        assert key_for_request(RERANK_PATH, base) == key_for_request(RERANK_PATH, {**base, "documents": ["d1", "d2", "d3", "d4"]})

    def test_caption_key_hashes_the_image_payload_not_the_url_flavor(self):
        def body(data_url: str, max_tokens: int = 1024) -> dict:
            return {
                "model": "v1",
                "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}, {"type": "text", "text": "描述"}]}],
                "max_tokens": max_tokens,
                "temperature": 0.15,
            }

        one = key_for_request(CAPTION_PATH, body("data:image/png;base64,AAAA"))
        same = key_for_request(CAPTION_PATH, body("data:image/png;base64,AAAA"))
        other_image = key_for_request(CAPTION_PATH, body("data:image/png;base64,BBBB"))
        other_budget = key_for_request(CAPTION_PATH, body("data:image/png;base64,AAAA", max_tokens=4096))

        assert one == same
        assert one != other_image
        assert one != other_budget

    def test_caption_anthropic_shape_shares_the_key_namespace(self):
        openai = {"model": "v1", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}, {"type": "text", "text": "描述"}]}], "max_tokens": 1024}
        anthropic = {"model": "v1", "messages": [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}, {"type": "text", "text": "描述"}]}], "max_tokens": 1024}

        assert key_for_request("/v1/messages", anthropic) == key_for_request(CAPTION_PATH, openai)

    def test_unknown_path_raises(self):
        with pytest.raises(UnsupportedReplayRequest):
            key_for_request("/v1/chat/messages", {"model": "x"})


class TestRecordingIO:
    def test_load_round_trips_and_conflicts_are_loud(self, tmp_path: Path):
        fixture = tmp_path / "recording.jsonl"
        key = key_for_request(DASHSCOPE_EMBED_PATH, {"model": "m1", "input": {"texts": ["a"]}})
        entry = {"key": key, "path": DASHSCOPE_EMBED_PATH, "digest": {}, "response": {"output": {"embeddings": []}}}
        fixture.write_text(json.dumps(entry) + "\n" + json.dumps(entry) + "\n", encoding="utf-8")
        assert load_recording(fixture) == {key: entry}

        conflicting = {**entry, "response": {"output": {"embeddings": [1]}}}
        fixture.write_text(json.dumps(entry) + "\n" + json.dumps(conflicting) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="conflicting"):
            load_recording(fixture)

    def test_load_recording_reads_gz(self, tmp_path: Path):
        import gzip

        key = key_for_request(DASHSCOPE_EMBED_PATH, {"model": "m1", "input": {"texts": ["a"]}})
        entry = {"key": key, "path": DASHSCOPE_EMBED_PATH, "digest": {}, "response": {"ok": 1}}
        fixture = tmp_path / "recording.jsonl.gz"
        with gzip.GzipFile(fixture, "wb") as handle:
            handle.write((json.dumps(entry) + "\n").encode("utf-8"))

        assert load_recording(fixture) == {key: entry}

    def test_material_fingerprint_tracks_content(self, tmp_path: Path):
        materials = tmp_path / "materials"
        materials.mkdir()
        (materials / "a.md").write_text("hello", encoding="utf-8")
        first = material_fingerprint(materials)

        (materials / "a.md").write_text("hello!", encoding="utf-8")
        assert material_fingerprint(materials) != first

        (materials / "a.md").write_text("hello", encoding="utf-8")
        assert material_fingerprint(materials) == first


class TestRerankRemap:
    def _entry(self, documents: list[str] | None = None) -> dict:
        return {
            "key": "k",
            "documents": documents or ["alpha", "beta", "gamma"],
            "response": {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 2, "relevance_score": 0.5}]},
        }

    def test_remaps_indices_onto_the_request_order(self):
        remapped = remap_rerank_response(self._entry(), ["gamma", "alpha", "beta"])

        assert [item["index"] for item in remapped["results"]] == [1, 0]
        assert [item["relevance_score"] for item in remapped["results"]] == [0.9, 0.5]

    def test_identity_when_orders_agree(self):
        remapped = remap_rerank_response(self._entry(), ["alpha", "beta", "gamma"])

        assert [item["index"] for item in remapped["results"]] == [0, 2]

    def test_recorded_document_absent_from_request_is_skipped(self):
        # 平局截断抖动：录制里有、这次没召回的文档直接跳过（其分数无从锚定）；
        # 重叠率仍在守卫线内（4/5）。
        entry = {
            "key": "k",
            "documents": ["d1", "d2", "d3", "d4", "d5"],
            "response": {"results": [{"index": 0, "relevance_score": 0.9}, {"index": 4, "relevance_score": 0.5}]},
        }

        remapped = remap_rerank_response(entry, ["d1", "d2", "d3", "d4"])

        assert [item["index"] for item in remapped["results"]] == [0]

    def test_collapsed_overlap_is_loud(self):
        with pytest.raises(Exception, match="overlap collapsed"):
            remap_rerank_response(self._entry(["a1", "a2", "a3", "a4", "a5"]), ["b1", "b2"])


class TestCapture:
    @pytest.mark.asyncio
    async def test_observes_recorded_kinds_and_ignores_others(self):
        recorder = Recorder()
        original = httpx.AsyncClient.send

        async def fake_send(self, request, **kwargs):  # noqa: ANN001
            return httpx.Response(200, json={"ok": True}, request=request)

        httpx.AsyncClient.send = fake_send
        try:
            install(recorder)
            async with httpx.AsyncClient(base_url="http://replay.test") as client:
                body = {"model": "m1", "input": {"texts": ["a"]}}
                await client.post(DASHSCOPE_EMBED_PATH, json=body)
                await client.post("/unrelated/path", json={"x": 1})
        finally:
            httpx.AsyncClient.send = original

        assert len(recorder.entries) == 1
        entry = next(iter(recorder.entries.values()))
        assert entry["digest"] == {"kind": "embed", "model": "m1", "n_texts": 1}
        assert entry["response"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_errors_are_not_recorded(self):
        recorder = Recorder()
        original = httpx.AsyncClient.send

        async def fake_send(self, request, **kwargs):  # noqa: ANN001
            return httpx.Response(500, json={"error": "boom"}, request=request)

        httpx.AsyncClient.send = fake_send
        try:
            install(recorder)
            async with httpx.AsyncClient(base_url="http://replay.test") as client:
                await client.post(DASHSCOPE_EMBED_PATH, json={"model": "m1", "input": {"texts": ["a"]}})
        finally:
            httpx.AsyncClient.send = original

        assert recorder.entries == {}


class TestReplayService:
    def _app(self, tmp_path: Path):
        from scripts.rag_eval_replay_server import build_app

        key = key_for_request(DASHSCOPE_EMBED_PATH, {"model": "m1", "input": {"texts": ["a"]}})
        recording = tmp_path / "recording.jsonl"
        recording.write_text(json.dumps({"key": key, "response": {"output": {"embeddings": [{"embedding": [0.1]}]}}}) + "\n", encoding="utf-8")
        return build_app(recording, None)

    def test_serves_recorded_outputs(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(tmp_path))
        response = client.post(DASHSCOPE_EMBED_PATH, json={"model": "m1", "input": {"texts": ["a"]}})

        assert response.status_code == 200
        assert response.json()["output"]["embeddings"][0]["embedding"] == [0.1]

    def test_cache_miss_is_a_loud_500(self, tmp_path: Path):
        from fastapi.testclient import TestClient

        client = TestClient(self._app(tmp_path))
        response = client.post(DASHSCOPE_EMBED_PATH, json={"model": "m1", "input": {"texts": ["unseen"]}})

        assert response.status_code == 500
        assert "re-record" in response.json()["detail"]

    def test_fingerprint_mismatch_refuses_to_start(self, tmp_path: Path):
        from scripts.rag_eval_replay_server import build_app

        out = tmp_path / "ci"
        out.mkdir()
        (out / "manifest.json").write_text(json.dumps({"fingerprint": "deadbeef"}), encoding="utf-8")
        (out / "recording.jsonl").write_text("", encoding="utf-8")
        materials = tmp_path / "materials"
        materials.mkdir()
        (materials / "a.md").write_text("content", encoding="utf-8")

        with pytest.raises(RuntimeError, match="fingerprint mismatch"):
            build_app(out / "recording.jsonl", materials)
