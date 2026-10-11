"""A malformed provider delay must not abort a recoverable podcast request."""

import base64
import json
import math
import sys
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import load  # noqa: E402

pod = load("podcast-generation")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("-10", None),
        ("nan", None),
        ("inf", None),
        ("-inf", None),
        ("1e309", None),
        ("1e300", None),
        ("86401", None),
        ("not a delay", None),
        ("0", 0.0),
        ("2.5", 2.5),
        (" 10 ", 10.0),
        ("86400", 86400.0),
    ],
)
def test_retry_after_rejects_unsafe_sleep_delays(header, expected):
    response = requests.Response()
    response.headers["Retry-After"] = header
    assert pod._parse_retry_after(response) == expected


@pytest.mark.parametrize("provider", ["minimax", "volcengine"])
@pytest.mark.parametrize(
    ("header", "expected_delay"),
    [("-10", 1.25), ("nan", 1.25), ("inf", 1.25), ("1e300", 1.25), ("0", 0.25)],
)
def test_podcast_recovers_from_rate_limit_with_unusable_or_zero_delay(
    tmp_path, monkeypatch, provider, header, expected_delay
):
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", provider)
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "test-app")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "test-token")
    monkeypatch.setenv("MINIMAX_TTS_MAX_RETRIES", "1")
    monkeypatch.setattr(pod.random, "uniform", lambda *args: 0.25)
    sleeps = []

    def checked_sleep(delay):
        # Reject precisely the values that real time.sleep cannot accept;
        # also keep tests from sleeping or admitting an unbounded delay.
        assert math.isfinite(delay) and 0 <= delay <= 86401
        sleeps.append(delay)

    monkeypatch.setattr(pod.time, "sleep", checked_sleep)
    limited = requests.Response()
    limited.status_code = 429
    limited.headers["Retry-After"] = header
    success = requests.Response()
    success.status_code = 200
    payload = (
        {"base_resp": {"status_code": 0}, "data": {"audio": b"audio".hex()}}
        if provider == "minimax"
        else {"code": 3000, "data": base64.b64encode(b"audio").decode("ascii")}
    )
    success._content = json.dumps(payload).encode("utf-8")
    responses = iter([limited, success])
    monkeypatch.setattr(pod.requests, "post", lambda *args, **kwargs: next(responses))
    script = tmp_path / "script.json"
    script.write_text(
        json.dumps({"lines": [{"speaker": "male", "paragraph": "Hello Deer"}]}),
        encoding="utf-8",
    )
    output = tmp_path / "podcast.mp3"

    result = pod.generate_podcast(str(script), str(output))

    assert output.read_bytes() == b"audio"
    assert "Successfully generated podcast" in result
    assert sleeps == [expected_delay]
