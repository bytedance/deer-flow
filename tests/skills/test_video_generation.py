import json
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")
GEMINI_VIDEO = "https://generativelanguage.googleapis.com/download/v1beta/files/video"
MINIMAX_VIDEO = "https://filecdn.minimax.chat/v.mp4"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in (
        "GEMINI_API_KEY",
        "MINIMAX_API_KEY",
        "VIDEO_GENERATION_PROVIDER",
        "MINIMAX_API_HOST",
        "MINIMAX_VIDEO_DOWNLOAD_HOSTS",
        "MINIMAX_VIDEO_MODEL",
        "MINIMAX_VIDEO_RESOLUTION",
        "MINIMAX_VIDEO_DURATION",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(vid.time, "sleep", lambda *_: None)


def test_resolve_prefers_gemini():
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override(monkeypatch):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "minimax")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


@pytest.mark.parametrize(
    "video_settings",
    [{}, {"resolution": "1080P", "duration": 6}],
    ids=["defaults", "overrides"],
)
def test_minimax_full_flow(monkeypatch, tmp_path, video_settings):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    for field, value in video_settings.items():
        monkeypatch.setenv(f"MINIMAX_VIDEO_{field.upper()}", str(value))
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        posts["url"] = url
        posts["json"] = json
        assert kw["allow_redirects"] is False
        assert headers["Authorization"] == "Bearer m"
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        assert kw["allow_redirects"] is False
        if url.endswith("/v1/query/video_generation"):
            assert headers["Authorization"] == "Bearer m"
            assert params["task_id"] == "T1"
            return FakeResp({"status": "Success", "file_id": "F1",
                             "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            assert headers["Authorization"] == "Bearer m"
            assert params["file_id"] == "F1"
            return FakeResp({"file": {"download_url": MINIMAX_VIDEO},
                             "base_resp": {"status_code": 0}})
        assert url == MINIMAX_VIDEO
        assert not headers
        return FakeResp(content=b"MP4DATA")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)

    out = tmp_path / "v.mp4"
    pf = tmp_path / "p.json"
    pf.write_text("a cat runs", encoding="utf-8")
    msg = vid.generate_video(str(pf), [], str(out), "16:9")

    assert out.read_bytes() == b"MP4DATA"
    assert posts["url"].endswith("/v1/video_generation")
    assert posts["json"] == {"model": "MiniMax-Hailuo-2.3", "prompt": "a cat runs", **video_settings}
    if "duration" in video_settings:
        assert type(posts["json"]["duration"]) is int
    assert "successfully" in msg.lower()


def mock_http_transport(monkeypatch, responses):
    """Record the prepared requests and return the scripted responses in order."""
    sent = []

    def send(adapter, request, **kwargs):
        assert len(sent) < len(responses), f"Unexpected {request.method} {request.url}"
        status, payload = responses[len(sent)]
        sent.append(request)
        response = requests.Response()
        response.request = request
        response.url = request.url
        response.status_code = status
        if isinstance(payload, str):
            response.headers["Location"] = payload
            payload = b""
        elif isinstance(payload, dict):
            payload = json.dumps(payload).encode()
        response._content = payload
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    return sent


def test_minimax_api_follows_same_origin_redirects_through_generation(monkeypatch, tmp_path):
    host = "https://minimax.example:8443"
    monkeypatch.setenv("MINIMAX_API_HOST", host)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    sent = mock_http_transport(monkeypatch, [
        (307, "submit/next"),
        (308, f"{host}/submit/final"),
        (200, {"task_id": "T1"}),
        (307, "?task_id=T1&step=2"),
        (308, f"{host}/poll/final?cursor=next"),
        (200, {"status": "Success", "file_id": "F1"}),
        (308, "/retrieve?file_id=F1"),
        (307, f"{host}/retrieve/final"),
        (200, {"file": {"download_url": MINIMAX_VIDEO}}),
        (200, b"video"),
    ])
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a cat runs", encoding="utf-8")
    output = tmp_path / "video.mp4"

    vid.generate_video(str(prompt), [], str(output))

    assert [(request.method, request.url) for request in sent] == [
        ("POST", f"{host}/v1/video_generation"),
        ("POST", f"{host}/v1/submit/next"),
        ("POST", f"{host}/submit/final"),
        ("GET", f"{host}/v1/query/video_generation?task_id=T1"),
        ("GET", f"{host}/v1/query/video_generation?task_id=T1&step=2"),
        ("GET", f"{host}/poll/final?cursor=next"),
        ("GET", f"{host}/v1/files/retrieve?file_id=F1"),
        ("GET", f"{host}/retrieve?file_id=F1"),
        ("GET", f"{host}/retrieve/final"),
        ("GET", MINIMAX_VIDEO),
    ]
    assert json.loads(sent[0].body) == {"model": "MiniMax-Hailuo-2.3", "prompt": "a cat runs"}
    for request in sent[:3]:
        assert request.body == sent[0].body
        assert request.headers["Content-Type"] == "application/json"
    assert all(request.body is None for request in sent[3:])
    assert all(request.headers["Authorization"] == "Bearer test-key" for request in sent[:-1])
    assert "Authorization" not in sent[-1].headers
    assert output.read_bytes() == b"video"


@pytest.mark.parametrize("destination", [
    "http://minimax.example/submit",
    "https://minimax.example:8443/submit",
    "https://filecdn.minimax.chat/submit",
    "https://user@minimax.example/submit",
    "https://minimax.example:/submit",
])
def test_minimax_api_rejects_untrusted_redirect_before_sending(monkeypatch, tmp_path, destination):
    host = "https://minimax.example"
    monkeypatch.setenv("MINIMAX_API_HOST", host)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    sent = mock_http_transport(monkeypatch, [(307, "/submit/next"), (308, destination)])
    output = tmp_path / "video.mp4"
    output.write_bytes(b"existing video")

    with pytest.raises(ValueError):
        vid._generate_video_minimax("a cat runs", [], str(output))

    assert [request.url for request in sent] == [f"{host}/v1/video_generation", f"{host}/submit/next"]
    assert output.read_bytes() == b"existing video"


@pytest.mark.parametrize("count", [5, 6])
def test_minimax_api_limits_same_origin_redirects(monkeypatch, count):
    host = "https://minimax.example:443"
    responses = [(307, f"https://minimax.example/step/{i + 1}") for i in range(count)]
    responses.append((200, {"file": {"download_url": MINIMAX_VIDEO}}))
    sent = mock_http_transport(monkeypatch, responses)

    if count == 5:
        assert vid._retrieve_file_url(host, "Bearer test-key", "F1") == MINIMAX_VIDEO
    else:
        with pytest.raises(ValueError):
            vid._retrieve_file_url(host, "Bearer test-key", "F1")
    assert len(sent) == 6


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 305, 306])
def test_minimax_api_rejects_other_3xx(monkeypatch, status):
    host = "https://minimax.example"
    sent = mock_http_transport(monkeypatch, [(status, "/next")])
    with pytest.raises(ValueError, match=str(status)):
        vid._poll_video_task(host, "Bearer test-key", "T1", max_attempts=1)
    assert [request.url for request in sent] == [f"{host}/v1/query/video_generation?task_id=T1"]


@pytest.mark.parametrize("status", [307, 308])
def test_minimax_api_rejects_redirect_without_location(monkeypatch, status):
    host = "https://minimax.example"
    sent = mock_http_transport(monkeypatch, [(status, b"")])
    with pytest.raises(ValueError, match="no destination"):
        vid._retrieve_file_url(host, "Bearer test-key", "F1")
    assert [request.url for request in sent] == [f"{host}/v1/files/retrieve?file_id=F1"]


@pytest.mark.parametrize("duration", ["abc", "2.5", "²"])
def test_minimax_rejects_invalid_duration(monkeypatch, tmp_path, duration):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("MINIMAX_VIDEO_DURATION", duration)

    def fail_if_called(*args, **kwargs):
        pytest.fail("Invalid duration should be rejected before submission")

    monkeypatch.setattr(vid.requests, "post", fail_if_called)
    prompt = tmp_path / "prompt.json"
    prompt.write_text("a cat runs", encoding="utf-8")

    with pytest.raises(
        ValueError, match="MINIMAX_VIDEO_DURATION must be an integer number of seconds"
    ):
        vid.generate_video(str(prompt), [], str(tmp_path / "v.mp4"))


def test_minimax_reference_first_frame(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        if url.endswith("/v1/query/video_generation"):
            return FakeResp({"status": "Success", "file_id": "F1", "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            return FakeResp({"file": {"download_url": MINIMAX_VIDEO}, "base_resp": {"status_code": 0}})
        return FakeResp(content=b"X")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    ref = tmp_path / "f.jpg"
    ref.write_bytes(b"\xff\xd8img")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    vid.generate_video(str(pf), [str(ref)], str(tmp_path / "v.mp4"), "16:9")
    assert posts["json"]["first_frame_image"].startswith("data:image/jpeg;base64,")


def test_minimax_task_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        return FakeResp({"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "blocked"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_minimax_poll_timeout(monkeypatch):
    def fake_get(url, headers=None, params=None, **kw):
        return FakeResp({"status": "Processing", "base_resp": {"status_code": 0}})

    monkeypatch.setattr(vid.requests, "get", fake_get)
    with pytest.raises(Exception) as e:
        vid._poll_video_task("https://h", "Bearer m", "T1", max_attempts=3, interval=0)
    assert "timed out" in str(e.value)


def test_minimax_task_fail_keeps_task_context(monkeypatch, tmp_path):
    # A Fail status takes priority over the generic base_resp check, so the
    # error keeps the task_id and the task-level failure message.
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        return FakeResp({"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "blocked"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception, match="task T1 failed"):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_gemini_download_raises_on_http_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    calls = {}

    def fake_get(url, headers=None, **kw):
        calls["timeout"] = kw.get("timeout")
        return FakeResp(content=b"error page", status_code=500)

    monkeypatch.setattr(vid.requests, "get", fake_get)
    out = tmp_path / "sub" / "v.mp4"
    with pytest.raises(requests.HTTPError):
        vid.download(GEMINI_VIDEO, str(out))
    assert calls["timeout"]  # a timeout is now passed
    assert not out.exists()


@pytest.mark.parametrize(
    ("url", "expected_headers"),
    [(GEMINI_VIDEO, {"x-goog-api-key": "g"}), ("https://storage.googleapis.com:443/example/video.mp4", {})],
)
def test_gemini_download_writes_nested_dir(monkeypatch, tmp_path, url, expected_headers):
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_get(url, headers=None, **kw):
        assert (headers or {}) == expected_headers
        return FakeResp(content=b"VIDEO")

    monkeypatch.setattr(vid.requests, "get", fake_get)
    out = tmp_path / "nested" / "dir" / "v.mp4"
    vid.download(url, str(out))
    assert out.read_bytes() == b"VIDEO"


def redirect(location):
    response = requests.Response()
    response.status_code = 302
    response.headers["Location"] = location
    return response


@pytest.mark.parametrize("provider", ["gemini", "minimax"])
@pytest.mark.parametrize("via_redirect", [False, True], ids=["initial-url", "redirect"])
def test_generation_rejects_untrusted_download(monkeypatch, tmp_path, provider, via_redirect):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", provider)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    untrusted = "https://untrusted.example/video"
    allowed = GEMINI_VIDEO if provider == "gemini" else MINIMAX_VIDEO
    resource_url = allowed if via_redirect else untrusted
    downloads = []

    def post(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        return FakeResp({"name": "operations/test"} if provider == "gemini" else {"task_id": "T1"})

    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        if url.endswith("/operations/test"):
            samples = [{"video": {"uri": resource_url}}]
            return FakeResp({"done": True, "response": {"generateVideoResponse": {"generatedSamples": samples}}})
        if url.endswith("/query/video_generation"):
            return FakeResp({"status": "Success", "file_id": "F1"})
        if url.endswith("/files/retrieve"):
            return FakeResp({"file": {"download_url": resource_url}})
        assert url == allowed
        downloads.append(url)
        return redirect(untrusted)

    monkeypatch.setattr(vid.requests, "post", post)
    monkeypatch.setattr(vid.requests, "get", get)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a cat runs")
    output = tmp_path / "video.mp4"
    output.write_bytes(b"existing video")

    with pytest.raises(ValueError):
        vid.generate_video(str(prompt), [], str(output))
    assert downloads == ([allowed] if via_redirect else [])
    assert output.read_bytes() == b"existing video"


@pytest.mark.parametrize(
    ("download", "url"),
    [
        (vid.download, "http://generativelanguage.googleapis.com/video"),
        (vid.download, "https://user@storage.googleapis.com/video"),
        (vid.download, "https://generativelanguage.googleapis.com:8443/video"),
        (vid._download, "https://127.0.0.1/video"),
        (vid._download, "https://filecdn.minimax.chat.example/video"),
        (vid._download, "https://bucket.oss-cn-wulanchabu-internal.aliyuncs.com/video"),
    ],
)
def test_download_rejects_invalid_destination_before_transport(monkeypatch, tmp_path, download, url):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setattr(vid.requests, "get", lambda *a, **kw: pytest.fail("unexpected network request"))
    output = tmp_path / "video.mp4"
    with pytest.raises(ValueError):
        download(url, str(output))
    assert not output.exists()


@pytest.mark.parametrize(
    ("download", "start", "signed_url", "initial_headers"),
    [
        (vid.download, GEMINI_VIDEO, "https://storage.googleapis.com/example/v.mp4?signature=test", {"x-goog-api-key": "g"}),
        (vid._download, MINIMAX_VIDEO, "https://bucket.oss-cn-wulanchabu.aliyuncs.com/v.mp4?signature=test", {}),
    ],
)
def test_download_checks_redirects_and_scopes_credentials(monkeypatch, tmp_path, download, start, signed_url, initial_headers):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    relative_target = start + "?step=1"
    calls = []
    responses = {start: redirect("?step=1"), relative_target: redirect(signed_url), signed_url: FakeResp(content=b"video")}

    def get(url, *, headers=None, allow_redirects, **kwargs):
        assert allow_redirects is False
        calls.append((url, headers or {}))
        return responses[url]

    monkeypatch.setattr(vid.requests, "get", get)
    output = tmp_path / "video.mp4"
    download(start, str(output))
    assert calls == [(start, initial_headers), (relative_target, initial_headers), (signed_url, {})]
    assert output.read_bytes() == b"video"


def test_gemini_storage_redirect_cannot_reauthorize_download(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    storage = "https://storage.googleapis.com/example/video"
    calls = []

    def get(url, *, headers, **kwargs):
        calls.append((url, headers))
        return redirect(GEMINI_VIDEO) if url == storage else FakeResp(content=b"video")

    monkeypatch.setattr(vid.requests, "get", get)
    vid.download(storage, str(tmp_path / "video.mp4"))
    assert calls == [(storage, {}), (GEMINI_VIDEO, {})]


def test_minimax_custom_download_host_requires_exact_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_HOST", "https://files.example.test")
    monkeypatch.setenv("MINIMAX_VIDEO_DOWNLOAD_HOSTS", "*.example.test")
    url = "https://files.example.test/video"
    calls = []

    def get(url, *, headers, **kwargs):
        calls.append((url, headers))
        return FakeResp(content=b"video")

    monkeypatch.setattr(vid.requests, "get", get)
    out = tmp_path / "video.mp4"
    with pytest.raises(ValueError, match="outside the provider allowlist"):
        vid._download(url, str(out))
    assert calls == []
    monkeypatch.setenv("MINIMAX_VIDEO_DOWNLOAD_HOSTS", "cdn.example.test, Files.Example.Test")
    vid._download(url, str(out))
    assert calls == [(url, {})]
    assert out.read_bytes() == b"video"


@pytest.mark.parametrize("count", [5, 6])
def test_download_limits_redirects(monkeypatch, tmp_path, count):
    calls = []

    def get(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        calls.append(url)
        if len(calls) <= count:
            return redirect(f"?hop={len(calls)}")
        return FakeResp(content=b"video")

    monkeypatch.setattr(vid.requests, "get", get)
    output = tmp_path / "video.mp4"
    if count == 5:
        vid._download(MINIMAX_VIDEO, str(output))
        assert output.read_bytes() == b"video"
    else:
        with pytest.raises(ValueError):
            vid._download(MINIMAX_VIDEO, str(output))
        assert not output.exists()
    assert len(calls) == 6


def test_gemini_post_raises_on_http_error(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(status_code=503)

    monkeypatch.setattr(vid.requests, "post", fake_post)
    pf = tmp_path / "p.json"
    pf.write_text("a cat", encoding="utf-8")
    with pytest.raises(requests.HTTPError):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_gemini_poll_rejects_redirect_even_with_a_valid_response_body(monkeypatch):
    def get(url, **kwargs):
        assert url.endswith("/operations/test")
        assert kwargs["allow_redirects"] is False
        samples = [{"video": {"uri": GEMINI_VIDEO}}]
        result = FakeResp({"done": True, "response": {"generateVideoResponse": {"generatedSamples": samples}}}, status_code=302)
        result.headers = {"Location": "/operations/other"}
        return result

    monkeypatch.setattr(vid.requests, "get", get)
    with pytest.raises(ValueError):
        vid._poll_gemini_operation("g", "operations/test", max_attempts=1)


def test_gemini_poll_is_bounded(monkeypatch):
    # The MiniMax path bounds its polling; the Gemini operation path must too.
    polls = {"count": 0}

    def fake_get(url, headers=None, **kw):
        polls["count"] += 1
        return FakeResp(json_data={"done": False})

    monkeypatch.setattr(vid.requests, "get", fake_get)
    with pytest.raises(Exception, match="timed out"):
        vid._poll_gemini_operation("g", "operations/op", max_attempts=3, interval=0)
    assert polls["count"] == 3


def test_gemini_operation_error_is_reported(monkeypatch, tmp_path):
    # A finished operation carrying an error must not surface as a KeyError on
    # the missing "response" field.
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(json_data={"name": "operations/op"})

    def fake_get(url, headers=None, **kw):
        return FakeResp(json_data={"done": True, "error": {"code": 3, "message": "prompt rejected"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    out = tmp_path / "v.mp4"
    with pytest.raises(Exception, match="prompt rejected"):
        vid.generate_video(str(pf), [], str(out), "16:9")
    assert not out.exists()


def test_gemini_filtered_sample_reports_reason(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    reason = "The generated video was filtered by the safety system."

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(json_data={"name": "operations/op"})

    def fake_get(url, headers=None, **kw):
        return FakeResp(
            json_data={
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "raiMediaFilteredCount": 1,
                        "raiMediaFilteredReasons": [reason],
                    }
                },
            }
        )

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception, match="filtered by the safety system"):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_gemini_sample_without_uri_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(json_data={"name": "operations/op"})

    def fake_get(url, headers=None, **kw):
        return FakeResp(
            json_data={
                "done": True,
                "response": {"generateVideoResponse": {"generatedSamples": [{"video": {}}]}},
            }
        )

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception, match="without a video URI"):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_gemini_forwards_aspect_ratio_to_predict_request(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        assert headers["x-goog-api-key"] == "g"
        return FakeResp(json_data={"name": "operations/op"})

    def fake_get(url, headers=None, **kw):
        assert headers["x-goog-api-key"] == "g"
        if url == GEMINI_VIDEO:
            return FakeResp(content=b"video")
        return FakeResp(
            json_data={
                "done": True,
                "response": {
                    "generateVideoResponse": {
                        "generatedSamples": [
                            {"video": {"uri": GEMINI_VIDEO}}
                        ]
                    }
                },
            },
        )

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("a tall cat", encoding="utf-8")

    vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "9:16")

    assert "predictLongRunning" in captured["url"]
    assert captured["json"]["parameters"]["aspectRatio"] == "9:16"
