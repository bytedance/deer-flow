import base64
import runpy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

img = load("image-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in [
        "GEMINI_API_KEY",
        "MINIMAX_API_KEY",
        "IMAGE_GENERATION_PROVIDER",
        "MINIMAX_API_HOST",
        "MINIMAX_IMAGE_MODEL",
        "IMAGE_GENERATION_API_KEY",
        "IMAGE_GENERATION_BASE_URL",
        "IMAGE_GENERATION_MODEL",
        "IMAGE_GENERATION_SIZE",
    ]:
        monkeypatch.delenv(k, raising=False)


def test_resolve_prefers_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    assert (
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", True) == "gemini"
    )


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert (
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False) == "minimax"
    )


def test_resolve_falls_back_to_openai_after_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    assert (
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False) == "minimax"
    )


def test_resolve_falls_back_to_openai(monkeypatch):
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    assert (
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False) == "openai"
    )


def test_resolve_override_wins(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "MiniMax")
    assert (
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", True) == "minimax"
    )


def test_resolve_errors_when_none(monkeypatch):
    with pytest.raises(ValueError, match="IMAGE_GENERATION_API_KEY"):
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False)


def test_minimax_builds_payload_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    raw = b"PNGBYTES"
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp(
            {
                "data": {"image_base64": [base64.b64encode(raw).decode()]},
                "base_resp": {"status_code": 0, "status_msg": "success"},
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    out = tmp_path / "o.jpg"
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("a red apple", encoding="utf-8")
    msg = img.generate_image(str(prompt_file), [], str(out), "16:9")

    assert out.read_bytes() == raw
    assert captured["url"].endswith("/v1/image_generation")
    assert captured["headers"]["Authorization"] == "Bearer m"
    assert captured["json"]["model"] == "image-01"
    assert captured["json"]["response_format"] == "base64"
    assert captured["json"]["aspect_ratio"] == "16:9"
    assert captured["json"]["n"] == 1
    assert captured["json"]["prompt_optimizer"] is True
    assert "Successfully generated image" in msg


def test_minimax_reference_image_as_data_url(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return FakeResp(
            {
                "data": {"image_base64": [base64.b64encode(b"x").decode()]},
                "base_resp": {"status_code": 0},
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"\xff\xd8refbytes")
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("scene", encoding="utf-8")
    img.generate_image(str(prompt_file), [str(ref)], str(tmp_path / "o.jpg"), "1:1")

    subj = captured["json"]["subject_reference"]
    assert subj[0]["type"] == "character"
    assert subj[0]["image_file"].startswith("data:image/jpeg;base64,")
    import base64 as _b64

    encoded = subj[0]["image_file"].split(",", 1)[1]
    assert _b64.b64decode(encoded) == b"\xff\xd8refbytes"


def test_minimax_raises_on_base_resp_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(
            {"base_resp": {"status_code": 1004, "status_msg": "auth failed"}}
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("x", encoding="utf-8")
    with pytest.raises(Exception) as e:
        img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "1:1")
    assert "1004" in str(e.value)


def test_minimax_extracts_json_prompt_field(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return FakeResp(
            {
                "data": {"image_base64": [base64.b64encode(b"x").decode()]},
                "base_resp": {"status_code": 0},
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text(
        '{"prompt": "a red barn at dawn", "style": "watercolor", '
        '"composition": "rule of thirds", "negative_prompt": "blurry"}',
        encoding="utf-8",
    )
    img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "16:9")

    # Only the JSON `prompt` field reaches MiniMax — no other fields, no JSON syntax.
    assert captured["json"]["prompt"] == "a red barn at dawn"
    assert captured["json"]["prompt_optimizer"] is True


def test_minimax_plaintext_prompt_passes_through(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return FakeResp(
            {
                "data": {"image_base64": [base64.b64encode(b"x").decode()]},
                "base_resp": {"status_code": 0},
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("a red apple on a table", encoding="utf-8")
    img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "1:1")

    assert captured["json"]["prompt"] == "a red apple on a table"


def test_minimax_rejects_overlong_prompt_without_calling_api(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):  # pragma: no cover
        raise AssertionError("must not call the API when the prompt is over the limit")

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text('{"prompt": "' + "x" * 1600 + '"}', encoding="utf-8")
    out = tmp_path / "o.jpg"
    msg = img.generate_image(str(prompt_file), [], str(out), "16:9")

    assert "1500" in msg
    assert "character" in msg.lower()
    assert not out.exists()


def test_minimax_creates_nested_output_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(
            {
                "data": {"image_base64": [base64.b64encode(b"img").decode()]},
                "base_resp": {"status_code": 0},
            }
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.txt"
    prompt_file.write_text("a cat", encoding="utf-8")
    out = tmp_path / "nested" / "dir" / "o.jpg"
    img.generate_image(str(prompt_file), [], str(out), "1:1")

    assert out.read_bytes() == b"img"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "unknown")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        img.generate_image(str(pf), [], str(tmp_path / "o.jpg"), "1:1")


def test_openai_compatible_generation_writes_base64(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_BASE_URL", "https://models.example/v1/")
    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured.update(url=url, headers=headers, json=json, kwargs=kwargs)
        return FakeResp({"data": [{"b64_json": base64.b64encode(b"image").decode()}]})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "prompt.json"
    prompt_file.write_text('{"prompt": "a red deer"}', encoding="utf-8")
    output_file = tmp_path / "nested" / "image.png"

    result = img.generate_image(str(prompt_file), [], str(output_file), "16:9")

    assert captured["url"] == "https://models.example/v1/images/generations"
    assert captured["headers"]["Authorization"] == "Bearer image-key"
    assert captured["json"]["model"] == "gpt-image-2.5-flare"
    assert captured["json"]["size"] == "1536x1024"
    assert captured["json"]["output_format"] == "png"
    assert "response_format" not in captured["json"]
    assert output_file.read_bytes() == b"image"
    assert "Successfully generated image" in result


@pytest.mark.parametrize("download_host", ["cdn.example", "8.8.8.8"])
def test_openai_compatible_generation_downloads_url(
    monkeypatch, tmp_path, download_host
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")

    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": f"https://{download_host}/image.png"}]}
        ),
    )
    monkeypatch.setattr(
        img.requests,
        "get",
        lambda *args, **kwargs: FakeResp(content=b"downloaded-image"),
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")
    output_file = tmp_path / "image.png"

    img.generate_image(str(prompt_file), [], str(output_file), "1:1")

    assert output_file.read_bytes() == b"downloaded-image"


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.example/image.png",
        "https://user@cdn.example/image.png",
        "https://cdn.example:8443/image.png",
        "https://127.0.0.1/image.png",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.1/image.png",
        "https://localhost/image.png",
        "https://224.0.0.1/image.png",
        "https://[2606:4700::1111]/image.png",
        "https://cdn.example\\@evil.example/image.png",
    ],
    ids=[
        "plain-http",
        "userinfo",
        "non-443-port",
        "loopback-ip",
        "link-local-ip",
        "private-ip",
        "localhost-name",
        "multicast-ip",
        "ipv6-literal",
        "backslash-host",
    ],
)
def test_openai_compatible_download_rejects_unsafe_urls(monkeypatch, tmp_path, url):
    """A provider-supplied URL is untrusted: unsafe targets must not be fetched."""
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp({"data": [{"url": url}]}),
    )

    def fail_get(*args, **kwargs):
        raise AssertionError("an unsafe download URL must not be fetched")

    monkeypatch.setattr(img.requests, "get", fail_get)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")

    with pytest.raises(ValueError):
        img.generate_image(str(prompt_file), [], str(tmp_path / "image.png"), "1:1")


def test_openai_compatible_download_revalidates_each_redirect(monkeypatch, tmp_path):
    """A public host must not be able to redirect the fetch to an internal one."""
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": "https://cdn.example/image.png"}]}
        ),
    )
    monkeypatch.setattr(
        img.requests,
        "get",
        lambda *args, **kwargs: FakeResp(
            status_code=302,
            headers={"Location": "https://169.254.169.254/latest/meta-data"},
        ),
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")

    with pytest.raises(ValueError, match="not a public address"):
        img.generate_image(str(prompt_file), [], str(tmp_path / "image.png"), "1:1")


def test_openai_compatible_download_follows_a_valid_redirect(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": "https://cdn.example/image.png"}]}
        ),
    )
    responses = iter(
        [
            FakeResp(
                status_code=302, headers={"Location": "https://cdn2.example/image.png"}
            ),
            FakeResp(content=b"redirected-image"),
        ]
    )
    monkeypatch.setattr(img.requests, "get", lambda *args, **kwargs: next(responses))
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")
    output_file = tmp_path / "image.png"

    img.generate_image(str(prompt_file), [], str(output_file), "1:1")

    assert output_file.read_bytes() == b"redirected-image"


def test_openai_compatible_download_rejects_a_redirect_without_location(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai-compatible")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": "https://cdn.example/image.png"}]}
        ),
    )
    monkeypatch.setattr(
        img.requests,
        "get",
        lambda *args, **kwargs: FakeResp(status_code=302),
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")

    with pytest.raises(ValueError, match="redirect has no destination"):
        img.generate_image(str(prompt_file), [], str(tmp_path / "image.png"), "1:1")


@pytest.mark.parametrize("status", [300, 304])
@pytest.mark.parametrize("existing", [False, True])
def test_openai_compatible_download_requires_2xx(
    monkeypatch, tmp_path, status, existing
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": "https://cdn.example/image.png"}]}
        ),
    )
    monkeypatch.setattr(
        img.requests,
        "get",
        lambda *args, **kwargs: FakeResp(status_code=status),
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a red deer", encoding="utf-8")
    output = tmp_path / "image.png"
    if existing:
        output.write_bytes(b"previous image")

    with pytest.raises(ValueError, match=f"Unexpected HTTP status {status}"):
        img.generate_image(str(prompt), [], str(output))
    if existing:
        assert output.read_bytes() == b"previous image"
    else:
        assert not output.exists()


@pytest.mark.parametrize(
    ("provider", "key", "edit"),
    [
        ("gemini", "GEMINI_API_KEY", False),
        ("minimax", "MINIMAX_API_KEY", False),
        ("openai", "IMAGE_GENERATION_API_KEY", False),
        ("openai", "IMAGE_GENERATION_API_KEY", True),
    ],
)
def test_generation_rejects_cross_origin_post_redirect(
    monkeypatch, tmp_path, provider, key, edit
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", provider)
    monkeypatch.setenv(key, "offline-key")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        assert kwargs.get("allow_redirects") is False
        return FakeResp(
            status_code=307, headers={"Location": "https://other.example/generate"}
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a red deer", encoding="utf-8")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference image")
    output = tmp_path / "image.png"

    with pytest.raises(ValueError, match="different origin"):
        img.generate_image(str(prompt), [str(reference)] if edit else [], str(output))
    assert len(calls) == 1
    assert not output.exists()


@pytest.mark.parametrize(("status", "edit"), [(307, False), (308, True)])
def test_openai_replays_same_origin_post_with_the_full_body(
    monkeypatch, tmp_path, status, edit
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_BASE_URL", "https://models.example/v1")
    sent = []

    def fake_post(url, **kwargs):
        assert kwargs.get("allow_redirects") is False
        if edit:
            fields = kwargs["data"]
            content = kwargs["files"][0][1][1].read()
        else:
            fields = kwargs["json"]
            content = None
        sent.append((url, dict(kwargs["headers"]), dict(fields), content))
        if len(sent) == 1:
            return FakeResp(status_code=status, headers={"Location": url + "/"})
        return FakeResp({"data": [{"b64_json": "aW1hZ2U="}]})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a red deer", encoding="utf-8")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference image")
    output = tmp_path / "image.png"

    img.generate_image(str(prompt), [str(reference)] if edit else [], str(output))

    assert len(sent) == 2
    assert sent[1][0] == sent[0][0] + "/"
    assert sent[1][1:] == sent[0][1:]
    assert sent[0][1]["Authorization"] == "Bearer image-key"
    assert sent[0][3] == (b"reference image" if edit else None)
    assert output.read_bytes() == b"image"


@pytest.mark.parametrize(
    ("status", "location", "message"),
    [
        (302, "/generate", "Unexpected HTTP status 302"),
        (307, None, "redirect has no destination"),
        (307, "http://models.example/generate", "different origin"),
        (308, "https://models.example:8443/generate", "different origin"),
        (308, "/generate", "Too many image generation redirects"),
    ],
)
def test_generation_post_redirects_are_limited(
    monkeypatch, tmp_path, status, location, message
):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_BASE_URL", "https://models.example/v1")
    calls = []

    def fake_post(url, **kwargs):
        calls.append(url)
        return FakeResp(
            status_code=status, headers={"Location": location} if location else {}
        )

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a red deer", encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        img.generate_image(str(prompt), [], str(tmp_path / "image.png"))
    assert len(calls) == (6 if location == "/generate" and status == 308 else 1)


def test_cli_failed_download_exits_nonzero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"data": [{"url": "https://cdn.example/image.png"}]}
        ),
    )
    monkeypatch.setattr(
        img.requests, "get", lambda *args, **kwargs: FakeResp(status_code=304)
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("a red deer", encoding="utf-8")
    output = tmp_path / "image.png"
    monkeypatch.setattr(
        sys,
        "argv",
        [img.__file__, "--prompt-file", str(prompt), "--output-file", str(output)],
    )

    with pytest.raises(SystemExit) as error:
        runpy.run_path(img.__file__, run_name="__main__")

    assert error.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected HTTP status 304" in captured.err
    assert not captured.out
    assert not output.exists()


def test_openai_compatible_dall_e_uses_response_format(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_MODEL", "dall-e-3")
    captured = {}

    def fake_post(url, headers=None, json=None, **kwargs):
        captured["json"] = json
        return FakeResp({"data": [{"b64_json": base64.b64encode(b"image").decode()}]})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")

    img.generate_image(str(prompt_file), [], str(tmp_path / "image.png"), "1:1")

    assert captured["json"]["response_format"] == "b64_json"
    assert "output_format" not in captured["json"]


@pytest.mark.parametrize(
    ("model", "aspect_ratio", "expected"),
    [
        ("gpt-image-2.5-flare", "16:9", "1536x1024"),
        ("gpt-image-2.5-flare", "9:16", "1024x1536"),
        ("dall-e-3", "16:9", "1792x1024"),
        ("dall-e-3", "9:16", "1024x1792"),
        ("dall-e-2", "16:9", "1024x1024"),
    ],
)
def test_openai_size_matches_model(model, aspect_ratio, expected):
    assert img._openai_size(aspect_ratio, model) == expected


def test_openai_size_override_wins(monkeypatch):
    monkeypatch.setenv("IMAGE_GENERATION_SIZE", "2048x1024")

    assert img._openai_size("1:1", "gpt-image-2.5-flare") == "2048x1024"


def test_openai_dall_e_rejects_invalid_size_override(monkeypatch):
    monkeypatch.setenv("IMAGE_GENERATION_SIZE", "1536x1024")

    with pytest.raises(ValueError, match="dall-e-3 size must be one of"):
        img._openai_size("16:9", "dall-e-3")


@pytest.mark.parametrize("extension", [".jpg", ".webp", ".unknown"])
def test_openai_dall_e_rejects_non_png_output(monkeypatch, tmp_path, extension):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_MODEL", "dall-e-3")
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("a red deer", encoding="utf-8")

    with pytest.raises(ValueError, match=r"\.png extension"):
        img.generate_image(
            str(prompt_file), [], str(tmp_path / f"image{extension}"), "1:1"
        )


@pytest.mark.parametrize("model", ["dall-e-2", "dall-e-3"])
def test_openai_dall_e_rejects_reference_images(monkeypatch, tmp_path, model):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    monkeypatch.setenv("IMAGE_GENERATION_MODEL", model)
    monkeypatch.setattr(
        img.requests,
        "post",
        lambda *args, **kwargs: pytest.fail("request must not be sent"),
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("add snow", encoding="utf-8")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"png")

    with pytest.raises(ValueError, match="reference-image editing is not supported"):
        img.generate_image(
            str(prompt_file), [str(reference)], str(tmp_path / "image.png"), "1:1"
        )


def test_openai_compatible_reference_images_use_edits(monkeypatch, tmp_path):
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("IMAGE_GENERATION_API_KEY", "image-key")
    captured = {}

    def fake_post(url, headers=None, data=None, files=None, **kwargs):
        captured.update(url=url, data=data, files=files)
        return FakeResp({"data": [{"b64_json": base64.b64encode(b"edited").decode()}]})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("add snow", encoding="utf-8")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"png")
    output_file = tmp_path / "image.png"

    img.generate_image(str(prompt_file), [str(reference)], str(output_file), "9:16")

    assert captured["url"].endswith("/images/edits")
    assert captured["data"]["size"] == "1024x1536"
    assert captured["files"][0][0] == "image[]"
    assert output_file.read_bytes() == b"edited"


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("image.png", "png"),
        ("image.jpg", "jpeg"),
        ("image.jpeg", "jpeg"),
        ("image.webp", "webp"),
        ("image.unknown", "png"),
    ],
)
def test_openai_output_format_matches_filename(filename, expected):
    assert img._openai_output_format(filename) == expected


def test_guess_mime_by_extension():
    assert img._guess_mime("/a/b.png") == "image/png"
    assert img._guess_mime("/a/b.webp") == "image/webp"
    assert img._guess_mime("/a/b.jpg") == "image/jpeg"
    assert img._guess_mime("/a/b.unknown") == "image/jpeg"
