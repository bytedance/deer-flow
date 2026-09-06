# MiniMax 接入生成类 Skill 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 image/video/podcast 三个现有 skill 中按环境变量自动接入 MiniMax 作为可选 provider，并用 skill-creator 新建一个 MiniMax 音乐生成 skill。

**Architecture:** 每个 skill 是 `skills/public/<name>/` 下的自包含脚本（`SKILL.md` + `scripts/generate.py`，纯 `requests`）。沙箱内目录隔离，故 MiniMax 代码在每个脚本内各自内联。`generate.py` 顶层用 `_resolve_provider()` 选 provider：`<SKILL>_PROVIDER` 覆盖 > 现有 provider 凭证存在 > `MINIMAX_API_KEY` 回退。测试放仓库根 `tests/skills/`，用 `importlib` 按路径加载脚本并 mock `requests`，不打真实 API。

**Tech Stack:** Python 3 + `requests`；测试用 pytest（通过 `uv run --no-project --with pytest --with requests --with Pillow` 运行）；新 skill 用 `skills/public/skill-creator/scripts/init_skill.py` 脚手架。

**测试运行命令（全程统一用这条）:**
```bash
uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/ -v
```

**关键事实（来自 MiniMax 官方文档，已核实）:**
- Base URL `https://api.minimaxi.com`，Header `Authorization: Bearer $MINIMAX_API_KEY` + `Content-Type: application/json`。
- 错误判定：响应体 `base_resp.status_code != 0` 即失败。
- 图像 `POST /v1/image_generation` 同步，`response_format:"base64"` → `data.image_base64[0]`（base64）。参考图放 `subject_reference:[{type:"character",image_file:"data:image/jpeg;base64,..."}]`。
- 视频三步：`POST /v1/video_generation`→`task_id`；`GET /v1/query/video_generation?task_id`→`status`(`Success`/`Fail`/...)+`file_id`；`GET /v1/files/retrieve?file_id`→`file.download_url`；下载 mp4（download_url 无需鉴权）。参考图放 `first_frame_image`（data URL）。
- 语音 `POST /v1/t2a_v2` 同步 → `data.audio` 是 **hex** → `bytes.fromhex`。
- 音乐 `POST /v1/music_generation` 同步 → `data.audio` 是 **hex** → mp3。无歌词非纯音乐时 `lyrics_optimizer:true`；纯音乐 `is_instrumental:true`。
- 已核实可用 voice_id：`male-qn-qingse`、`female-tianmei`（官方 t2a 文档示例中出现）。

---

## File Structure

**新建：**
- `tests/skills/skill_loader.py` — 按路径加载某 skill 的 `generate.py` 为模块。
- `tests/skills/test_image_generation.py`
- `tests/skills/test_video_generation.py`
- `tests/skills/test_podcast_generation.py`
- `tests/skills/test_music_generation.py`
- `skills/public/music-generation/SKILL.md`（脚手架后替换）
- `skills/public/music-generation/scripts/generate.py`（脚手架后替换）

**修改：**
- `skills/public/image-generation/scripts/generate.py`（整文件替换）
- `skills/public/image-generation/SKILL.md`（追加 MiniMax 说明段）
- `skills/public/video-generation/scripts/generate.py`（整文件替换）
- `skills/public/video-generation/SKILL.md`（追加 MiniMax 说明段）
- `skills/public/podcast-generation/scripts/generate.py`（整文件替换）
- `skills/public/podcast-generation/SKILL.md`（追加 MiniMax 说明段）
- `frontend/src/app/mock/api/skills/route.ts`（新增 music-generation 条目）

---

## Task 0: 测试加载器

**Files:**
- Create: `tests/skills/skill_loader.py`

- [ ] **Step 1: 写加载器**

`tests/skills/skill_loader.py`:
```python
"""Load a skill's scripts/generate.py as an importable module, by file path.

Skills live in skills/public/<name>/scripts/generate.py and are NOT a package,
so tests load them via importlib. Tests then mock the module's `requests`.
"""
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load(skill_name: str):
    """Return the generate.py module for skills/public/<skill_name>."""
    path = REPO_ROOT / "skills" / "public" / skill_name / "scripts" / "generate.py"
    mod_name = skill_name.replace("-", "_") + "_generate"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, json_data=None, content=b"", status_code=200):
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def json(self):
        return self._json
```

- [ ] **Step 2: 冒烟验证加载器可加载现有脚本**

Run:
```bash
uv run --no-project --with pytest --with requests --with Pillow python -c "import sys; sys.path.insert(0,'tests/skills'); from skill_loader import load; m=load('image-generation'); print('loaded', hasattr(m,'generate_image'))"
```
Expected: 输出 `loaded True`（注意：此步要求 Task 1 尚未执行也能加载——当前 image generate.py 顶层 `from PIL import Image` 需 Pillow，已在命令里 `--with Pillow`）。

- [ ] **Step 3: Commit**

```bash
git add tests/skills/skill_loader.py
git commit -m "test(skills): add importlib loader + FakeResp for skill tests"
```

---

## Task 1: image-generation 接入 MiniMax

**Files:**
- Modify: `skills/public/image-generation/scripts/generate.py`（整文件替换）
- Modify: `skills/public/image-generation/SKILL.md`
- Test: `tests/skills/test_image_generation.py`

- [ ] **Step 1: 写失败测试**

`tests/skills/test_image_generation.py`:
```python
import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

img = load("image-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["GEMINI_API_KEY", "MINIMAX_API_KEY", "IMAGE_GENERATION_PROVIDER",
              "MINIMAX_API_HOST", "MINIMAX_IMAGE_MODEL"]:
        monkeypatch.delenv(k, raising=False)


def test_resolve_prefers_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini",
                                 bool(__import__("os").getenv("GEMINI_API_KEY"))) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override_wins(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("IMAGE_GENERATION_PROVIDER", "MiniMax")
    assert img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_resolve_errors_when_none(monkeypatch):
    with pytest.raises(ValueError):
        img._resolve_provider("IMAGE_GENERATION_PROVIDER", "gemini", False)


def test_minimax_builds_payload_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    raw = b"PNGBYTES"
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(raw).decode()]},
                         "base_resp": {"status_code": 0, "status_msg": "success"}})

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
    assert "Successfully generated image" in msg


def test_minimax_reference_image_as_data_url(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["json"] = json
        return FakeResp({"data": {"image_base64": [base64.b64encode(b"x").decode()]},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    ref = tmp_path / "ref.jpg"
    ref.write_bytes(b"\xff\xd8refbytes")
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("scene", encoding="utf-8")
    img.generate_image(str(prompt_file), [str(ref)], str(tmp_path / "o.jpg"), "1:1")

    subj = captured["json"]["subject_reference"]
    assert subj[0]["type"] == "character"
    assert subj[0]["image_file"].startswith("data:image/jpeg;base64,")


def test_minimax_raises_on_base_resp_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"base_resp": {"status_code": 1004, "status_msg": "auth failed"}})

    monkeypatch.setattr(img.requests, "post", fake_post)
    prompt_file = tmp_path / "p.json"
    prompt_file.write_text("x", encoding="utf-8")
    with pytest.raises(Exception) as e:
        img.generate_image(str(prompt_file), [], str(tmp_path / "o.jpg"), "1:1")
    assert "1004" in str(e.value)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_image_generation.py -v`
Expected: FAIL（`_resolve_provider` / minimax 行为尚不存在）。

- [ ] **Step 3: 整文件替换 generate.py**

`skills/public/image-generation/scripts/generate.py`:
```python
import base64
import os

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


def validate_image(image_path: str) -> bool:
    """Validate if an image file can be opened and is not corrupted."""
    from PIL import Image  # lazy import: keeps module importable without Pillow

    try:
        with Image.open(image_path) as image:
            image.verify()
        with Image.open(image_path) as image:
            image.load()
        return True
    except Exception as exc:
        print(f"Warning: Image '{image_path}' is invalid or corrupted: {exc}")
        return False


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    """Pick the generation provider.

    1. Explicit <SKILL>_PROVIDER override wins.
    2. Otherwise prefer the existing provider when its credentials are present.
    3. Otherwise fall back to MiniMax when MINIMAX_API_KEY is set.
    """
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set GEMINI_API_KEY for {existing_provider}, "
        f"or MINIMAX_API_KEY for minimax (optionally force with {override_env})."
    )


def _minimax_host() -> str:
    return os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")


def _check_base_resp(payload: dict) -> None:
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(
            f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}"
        )


def _to_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _generate_image_minimax(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"
    body = {
        "model": os.getenv("MINIMAX_IMAGE_MODEL", "image-01"),
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "response_format": "base64",
        "n": 1,
        "prompt_optimizer": True,
    }
    if reference_images:
        body["subject_reference"] = [
            {"type": "character", "image_file": _to_data_url(p)} for p in reference_images
        ]
    response = requests.post(
        f"{_minimax_host()}/v1/image_generation",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    images = (payload.get("data") or {}).get("image_base64") or []
    if not images:
        raise Exception("MiniMax returned no image data")
    with open(output_file, "wb") as f:
        f.write(base64.b64decode(images[0]))
    return f"Successfully generated image to {output_file}"


def _generate_image_gemini(
    prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str
) -> str:
    parts = []
    valid_reference_images = []
    for ref_img in reference_images:
        if validate_image(ref_img):
            valid_reference_images.append(ref_img)
        else:
            print(f"Skipping invalid reference image: {ref_img}")
    if len(valid_reference_images) < len(reference_images):
        skipped = len(reference_images) - len(valid_reference_images)
        print(f"Note: {skipped} reference image(s) were skipped due to validation failure.")

    for reference_image in valid_reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_b64}})

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={
            "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio}},
            "contents": [{"parts": [*parts, {"text": prompt}]}],
        },
    )
    response.raise_for_status()
    data = response.json()
    response_parts: list[dict] = data["candidates"][0]["content"]["parts"]
    image_parts = [part for part in response_parts if part.get("inlineData", False)]
    if len(image_parts) == 1:
        base64_image = image_parts[0]["inlineData"]["data"]
        with open(output_file, "wb") as f:
            f.write(base64.b64decode(base64_image))
        return f"Successfully generated image to {output_file}"
    raise Exception("Failed to generate image")


def generate_image(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider(
        "IMAGE_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY"))
    )
    if provider == "minimax":
        return _generate_image_minimax(prompt, reference_images, output_file, aspect_ratio)
    return _generate_image_gemini(prompt, reference_images, output_file, aspect_ratio)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate images using Gemini or MiniMax API")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to JSON prompt file")
    parser.add_argument("--reference-images", nargs="*", default=[],
                        help="Absolute paths to reference images (space-separated)")
    parser.add_argument("--output-file", required=True, help="Output path for generated image")
    parser.add_argument("--aspect-ratio", required=False, default="16:9",
                        help="Aspect ratio of the generated image")
    args = parser.parse_args()

    try:
        print(generate_image(args.prompt_file, args.reference_images,
                             args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating image: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_image_generation.py -v`
Expected: PASS（7 个用例全过）。

- [ ] **Step 5: 更新 SKILL.md（追加 provider 说明）**

在 `skills/public/image-generation/SKILL.md` 的 `## Notes` 段之前插入新段落：
```markdown
## Providers (Gemini / MiniMax)

This skill auto-selects the provider by environment variables (no CLI change):

- `GEMINI_API_KEY` set → use Gemini (default, unchanged).
- Only `MINIMAX_API_KEY` set → use MiniMax (`/v1/image_generation`, model `image-01`).
- Force one explicitly with `IMAGE_GENERATION_PROVIDER=gemini|minimax`.

MiniMax optional overrides: `MINIMAX_API_HOST` (default `https://api.minimaxi.com`),
`MINIMAX_IMAGE_MODEL` (default `image-01`). Reference images are sent as the MiniMax
`subject_reference` character image. The CLI and `--prompt-file` / `--reference-images`
/ `--output-file` / `--aspect-ratio` arguments are identical for both providers.
```

- [ ] **Step 6: Commit**

```bash
git add skills/public/image-generation/scripts/generate.py skills/public/image-generation/SKILL.md tests/skills/test_image_generation.py
git commit -m "feat(image-generation): add MiniMax provider with env auto-detect"
```

---

## Task 2: video-generation 接入 MiniMax

**Files:**
- Modify: `skills/public/video-generation/scripts/generate.py`（整文件替换）
- Modify: `skills/public/video-generation/SKILL.md`
- Test: `tests/skills/test_video_generation.py`

- [ ] **Step 1: 写失败测试**

`tests/skills/test_video_generation.py`:
```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["GEMINI_API_KEY", "MINIMAX_API_KEY", "VIDEO_GENERATION_PROVIDER",
              "MINIMAX_API_HOST", "MINIMAX_VIDEO_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(vid.time, "sleep", lambda *_: None)


def test_resolve_prefers_gemini():
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override(monkeypatch):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "minimax")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_minimax_full_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        posts["url"] = url
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        if url.endswith("/v1/query/video_generation"):
            assert params["task_id"] == "T1"
            return FakeResp({"status": "Success", "file_id": "F1",
                             "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            assert params["file_id"] == "F1"
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"},
                             "base_resp": {"status_code": 0}})
        return FakeResp(content=b"MP4DATA")  # the actual download

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)

    out = tmp_path / "v.mp4"
    pf = tmp_path / "p.json"
    pf.write_text("a cat runs", encoding="utf-8")
    msg = vid.generate_video(str(pf), [], str(out), "16:9")

    assert out.read_bytes() == b"MP4DATA"
    assert posts["url"].endswith("/v1/video_generation")
    assert posts["json"]["model"] == "MiniMax-Hailuo-2.3"
    assert "successfully" in msg.lower()


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
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"}, "base_resp": {"status_code": 0}})
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_video_generation.py -v`
Expected: FAIL。

- [ ] **Step 3: 整文件替换 generate.py**

`skills/public/video-generation/scripts/generate.py`:
```python
import base64
import os
import time

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    """Pick the provider: <SKILL>_PROVIDER override > existing creds > MiniMax fallback."""
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set GEMINI_API_KEY for {existing_provider}, "
        f"or MINIMAX_API_KEY for minimax (optionally force with {override_env})."
    )


def _minimax_host() -> str:
    return os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")


def _check_base_resp(payload: dict) -> None:
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")


def _to_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def _poll_video_task(host: str, auth: str, task_id: str,
                     max_attempts: int = 120, interval: int = 3) -> str:
    for _ in range(max_attempts):
        response = requests.get(
            f"{host}/v1/query/video_generation",
            headers={"Authorization": auth},
            params={"task_id": task_id},
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status == "Success":
            return payload["file_id"]
        if status == "Fail":
            base = payload.get("base_resp") or {}
            raise Exception(
                f"MiniMax video task {task_id} failed: "
                f"{base.get('status_code')} {base.get('status_msg')}"
            )
        time.sleep(interval)
    raise Exception(f"MiniMax video task {task_id} timed out after {max_attempts} polls")


def _retrieve_file_url(host: str, auth: str, file_id: str) -> str:
    response = requests.get(
        f"{host}/v1/files/retrieve",
        headers={"Authorization": auth},
        params={"file_id": file_id},
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    return payload["file"]["download_url"]


def _download(url: str, output_file: str) -> None:
    response = requests.get(url)
    response.raise_for_status()
    with open(output_file, "wb") as f:
        f.write(response.content)


def _generate_video_minimax(
    prompt: str, reference_images: list[str], output_file: str
) -> str:
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"
    host = _minimax_host()
    auth = f"Bearer {api_key}"
    body = {"model": os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-2.3"), "prompt": prompt}
    if reference_images:
        body["first_frame_image"] = _to_data_url(reference_images[0])
    response = requests.post(
        f"{host}/v1/video_generation",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    task_id = payload["task_id"]
    file_id = _poll_video_task(host, auth, task_id)
    download_url = _retrieve_file_url(host, auth, file_id)
    _download(download_url, output_file)
    return f"The video has been generated successfully to {output_file}"


def download(url: str, output_file: str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.get(url, headers={"x-goog-api-key": api_key})
    with open(output_file, "wb") as f:
        f.write(response.content)


def _generate_video_gemini(
    prompt: str, reference_images: list[str], output_file: str
) -> str:
    reference_payload = []
    request_json = {"instances": [{"prompt": prompt}]}
    for reference_image in reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        reference_payload.append(
            {"image": {"mimeType": "image/jpeg", "bytesBase64Encoded": image_b64},
             "referenceType": "asset"}
        )
    if reference_payload:
        request_json["instances"][0]["referenceImages"] = reference_payload
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning",
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=request_json,
    )
    data = response.json()
    operation_name = data["name"]
    while True:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
            headers={"x-goog-api-key": api_key},
        )
        data = response.json()
        if data.get("done", False):
            sample = data["response"]["generateVideoResponse"]["generatedSamples"][0]
            download(sample["video"]["uri"], output_file)
            break
        time.sleep(3)
    return f"The video has been generated successfully to {output_file}"


def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    with open(prompt_file, "r", encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider(
        "VIDEO_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY"))
    )
    if provider == "minimax":
        # MiniMax video uses resolution/duration, not aspect_ratio; aspect_ratio ignored.
        return _generate_video_minimax(prompt, reference_images, output_file)
    return _generate_video_gemini(prompt, reference_images, output_file)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos using Gemini or MiniMax API")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to JSON prompt file")
    parser.add_argument("--reference-images", nargs="*", default=[],
                        help="Absolute paths to reference images (space-separated)")
    parser.add_argument("--output-file", required=True, help="Output path for generated video")
    parser.add_argument("--aspect-ratio", required=False, default="16:9",
                        help="Aspect ratio of the generated video (Gemini only)")
    args = parser.parse_args()

    try:
        print(generate_video(args.prompt_file, args.reference_images,
                             args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating video: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_video_generation.py -v`
Expected: PASS（6 个用例全过）。

- [ ] **Step 5: 更新 SKILL.md**

在 `skills/public/video-generation/SKILL.md` 末尾追加：
```markdown
## Providers (Gemini / MiniMax)

Auto-selected by environment variables (CLI unchanged):

- `GEMINI_API_KEY` set → Gemini Veo (default, unchanged).
- Only `MINIMAX_API_KEY` set → MiniMax video (`/v1/video_generation`, async 3-step poll/download).
- Force with `VIDEO_GENERATION_PROVIDER=gemini|minimax`.

MiniMax overrides: `MINIMAX_API_HOST` (default `https://api.minimaxi.com`),
`MINIMAX_VIDEO_MODEL` (default `MiniMax-Hailuo-2.3`). The first reference image is used
as MiniMax `first_frame_image`. MiniMax ignores `--aspect-ratio` (it uses resolution/duration).
```

- [ ] **Step 6: Commit**

```bash
git add skills/public/video-generation/scripts/generate.py skills/public/video-generation/SKILL.md tests/skills/test_video_generation.py
git commit -m "feat(video-generation): add MiniMax provider with async poll/download"
```

---

## Task 3: podcast-generation 接入 MiniMax

**Files:**
- Modify: `skills/public/podcast-generation/scripts/generate.py`（整文件替换）
- Modify: `skills/public/podcast-generation/SKILL.md`
- Test: `tests/skills/test_podcast_generation.py`

- [ ] **Step 1: 写失败测试**

`tests/skills/test_podcast_generation.py`:
```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

pod = load("podcast-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["VOLCENGINE_TTS_APPID", "VOLCENGINE_TTS_ACCESS_TOKEN", "VOLCENGINE_TTS_CLUSTER",
              "MINIMAX_API_KEY", "PODCAST_GENERATION_PROVIDER", "MINIMAX_API_HOST",
              "MINIMAX_TTS_MODEL", "MINIMAX_TTS_VOICE_MALE", "MINIMAX_TTS_VOICE_FEMALE"]:
        monkeypatch.delenv(k, raising=False)


def test_resolve_prefers_volcengine(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    assert pod._resolve_tts_provider() == "volcengine"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert pod._resolve_tts_provider() == "minimax"


def test_resolve_override(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "minimax")
    assert pod._resolve_tts_provider() == "minimax"


def test_minimax_tts_decodes_hex(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"data": {"audio": b"audiobytes".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hello", "male-qn-qingse")
    assert out == b"audiobytes"
    assert captured["url"].endswith("/v1/t2a_v2")
    assert captured["json"]["voice_setting"]["voice_id"] == "male-qn-qingse"
    assert captured["json"]["output_format"] == "hex"


def test_process_line_minimax_voice_mapping(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    seen = {}

    def fake_tts(text, voice_id):
        seen["voice_id"] = voice_id
        return b"x"

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    line = pod.ScriptLine(speaker="female", paragraph="hi")
    idx, audio = pod._process_line((0, line, 1, "minimax"))
    assert audio == b"x"
    assert seen["voice_id"] == "female-tianmei"


def test_generate_podcast_minimax_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"data": {"audio": b"chunk".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    script = tmp_path / "s.json"
    script.write_text(
        '{"title":"T","locale":"en","lines":[{"speaker":"male","paragraph":"a"},'
        '{"speaker":"female","paragraph":"b"}]}',
        encoding="utf-8",
    )
    out = tmp_path / "o.mp3"
    msg = pod.generate_podcast(str(script), str(out), None)
    assert out.read_bytes() == b"chunkchunk"
    assert "Successfully generated podcast" in msg
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_podcast_generation.py -v`
Expected: FAIL。

- [ ] **Step 3: 整文件替换 generate.py**

`skills/public/podcast-generation/scripts/generate.py`:
```python
import argparse
import base64
import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Literal, Optional

import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


class ScriptLine:
    def __init__(self, speaker: Literal["male", "female"] = "male", paragraph: str = ""):
        self.speaker = speaker
        self.paragraph = paragraph


class Script:
    def __init__(self, locale: Literal["en", "zh"] = "en", lines: Optional[list[ScriptLine]] = None):
        self.locale = locale
        self.lines = lines or []

    @classmethod
    def from_dict(cls, data: dict) -> "Script":
        script = cls(locale=data.get("locale", "en"))
        for line in data.get("lines", []):
            script.lines.append(
                ScriptLine(speaker=line.get("speaker", "male"),
                           paragraph=line.get("paragraph", ""))
            )
        return script


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(
        f"No credentials found. Set VOLCENGINE_TTS_APPID + VOLCENGINE_TTS_ACCESS_TOKEN "
        f"for {existing_provider}, or MINIMAX_API_KEY for minimax "
        f"(optionally force with {override_env})."
    )


def _resolve_tts_provider() -> str:
    has_volc = bool(
        os.getenv("VOLCENGINE_TTS_APPID") and os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    )
    return _resolve_provider("PODCAST_GENERATION_PROVIDER", "volcengine", has_volc)


def text_to_speech_volcengine(text: str, voice_type: str) -> Optional[bytes]:
    """Convert text to speech using Volcengine TTS (returns base64-decoded mp3 bytes)."""
    app_id = os.getenv("VOLCENGINE_TTS_APPID")
    access_token = os.getenv("VOLCENGINE_TTS_ACCESS_TOKEN")
    cluster = os.getenv("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
    url = "https://openspeech.bytedance.com/api/v1/tts"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer;{access_token}"}
    payload = {
        "app": {"appid": app_id, "token": "access_token", "cluster": cluster},
        "user": {"uid": "podcast-generator"},
        "audio": {"voice_type": voice_type, "encoding": "mp3", "speed_ratio": 1.2},
        "request": {"reqid": str(uuid.uuid4()), "text": text,
                    "text_type": "plain", "operation": "query"},
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            logger.error(f"TTS API error: {response.status_code} - {response.text}")
            return None
        result = response.json()
        if result.get("code") != 3000:
            logger.error(f"TTS error: {result.get('message')} (code: {result.get('code')})")
            return None
        audio_data = result.get("data")
        if audio_data:
            return base64.b64decode(audio_data)
    except Exception as e:
        logger.error(f"TTS error: {str(e)}")
    return None


def text_to_speech_minimax(text: str, voice_id: str) -> Optional[bytes]:
    """Convert text to speech using MiniMax t2a_v2 (returns hex-decoded mp3 bytes)."""
    api_key = os.getenv("MINIMAX_API_KEY")
    host = os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")
    payload = {
        "model": os.getenv("MINIMAX_TTS_MODEL", "speech-2.6-hd"),
        "text": text,
        "voice_setting": {"voice_id": voice_id, "speed": 1.0, "vol": 1.0, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
        "output_format": "hex",
    }
    try:
        response = requests.post(
            f"{host}/v1/t2a_v2",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if response.status_code != 200:
            logger.error(f"MiniMax TTS error: {response.status_code} - {response.text}")
            return None
        result = response.json()
        if (result.get("base_resp") or {}).get("status_code", 0) != 0:
            base = result.get("base_resp") or {}
            logger.error(f"MiniMax TTS error {base.get('status_code')}: {base.get('status_msg')}")
            return None
        audio_hex = (result.get("data") or {}).get("audio")
        if audio_hex:
            return bytes.fromhex(audio_hex)
    except Exception as e:
        logger.error(f"MiniMax TTS error: {str(e)}")
    return None


def _process_line(args: tuple[int, ScriptLine, int, str]) -> tuple[int, Optional[bytes]]:
    """Process a single script line for TTS. Returns (index, audio_bytes)."""
    i, line, total, provider = args
    logger.info(f"Processing line {i + 1}/{total} ({line.speaker}) via {provider}")
    if provider == "minimax":
        if line.speaker == "male":
            voice = os.getenv("MINIMAX_TTS_VOICE_MALE", "male-qn-qingse")
        else:
            voice = os.getenv("MINIMAX_TTS_VOICE_FEMALE", "female-tianmei")
        audio = text_to_speech_minimax(line.paragraph, voice)
    else:
        if line.speaker == "male":
            voice = "zh_male_yangguangqingnian_moon_bigtts"
        else:
            voice = "zh_female_sajiaonvyou_moon_bigtts"
        audio = text_to_speech_volcengine(line.paragraph, voice)
    if not audio:
        logger.warning(f"Failed to generate audio for line {i + 1}")
    return (i, audio)


def tts_node(script: Script, max_workers: int = 4) -> list[bytes]:
    """Convert script lines to audio chunks using TTS with multi-threading."""
    total = len(script.lines)
    if total == 0:
        raise ValueError("Script contains no lines to process")

    provider = _resolve_tts_provider()
    logger.info(f"Converting script to audio using {max_workers} workers (provider={provider})...")
    tasks = [(i, line, total, provider) for i, line in enumerate(script.lines)]

    results: dict[int, Optional[bytes]] = {}
    failed_indices: list[int] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_line, task): task[0] for task in tasks}
        for future in as_completed(futures):
            idx, audio = future.result()
            results[idx] = audio
            if not audio:
                failed_indices.append(idx)

    if failed_indices:
        logger.warning(
            f"Failed to generate audio for {len(failed_indices)}/{total} lines: "
            f"line numbers {sorted(i + 1 for i in failed_indices)}"
        )

    audio_chunks = []
    for i in range(total):
        audio = results.get(i)
        if audio:
            audio_chunks.append(audio)

    logger.info(f"Generated {len(audio_chunks)}/{total} audio chunks successfully")
    if not audio_chunks:
        raise ValueError(f"TTS generation failed for all {total} lines.")
    return audio_chunks


def mix_audio(audio_chunks: list[bytes]) -> bytes:
    """Combine audio chunks into a single audio file."""
    if not audio_chunks:
        raise ValueError("No audio chunks to mix - TTS generation may have failed")
    output = b"".join(audio_chunks)
    if len(output) == 0:
        raise ValueError("Mixed audio is empty - TTS generation may have failed")
    logger.info(f"Audio mixing complete: {len(output)} bytes")
    return output


def generate_markdown(script: Script, title: str = "Podcast Script") -> str:
    lines = [f"# {title}", ""]
    for line in script.lines:
        speaker_name = "**Host (Male)**" if line.speaker == "male" else "**Host (Female)**"
        lines.append(f"{speaker_name}: {line.paragraph}")
        lines.append("")
    return "\n".join(lines)


def generate_podcast(script_file: str, output_file: str,
                     transcript_file: Optional[str] = None) -> str:
    with open(script_file, "r", encoding="utf-8") as f:
        script_json = json.load(f)
    if "lines" not in script_json:
        raise ValueError(
            f"Invalid script format: missing 'lines' key. Got keys: {list(script_json.keys())}"
        )
    script = Script.from_dict(script_json)
    logger.info(f"Loaded script with {len(script.lines)} lines")

    if transcript_file:
        title = script_json.get("title", "Podcast Script")
        markdown_content = generate_markdown(script, title)
        transcript_dir = os.path.dirname(transcript_file)
        if transcript_dir:
            os.makedirs(transcript_dir, exist_ok=True)
        with open(transcript_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated transcript to {transcript_file}")

    audio_chunks = tts_node(script)
    if not audio_chunks:
        raise Exception("Failed to generate any audio")
    output_audio = mix_audio(audio_chunks)

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(output_audio)

    result = f"Successfully generated podcast to {output_file}"
    if transcript_file:
        result += f" and transcript to {transcript_file}"
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate podcast from script JSON file")
    parser.add_argument("--script-file", required=True, help="Absolute path to script JSON file")
    parser.add_argument("--output-file", required=True, help="Output path for generated podcast MP3")
    parser.add_argument("--transcript-file", required=False,
                        help="Output path for transcript markdown file (optional)")
    args = parser.parse_args()

    try:
        result = generate_podcast(args.script_file, args.output_file, args.transcript_file)
        print(result)
    except Exception as e:
        import traceback
        print(f"Error generating podcast: {e}")
        traceback.print_exc()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_podcast_generation.py -v`
Expected: PASS（6 个用例全过）。

- [ ] **Step 5: 更新 SKILL.md**

在 `skills/public/podcast-generation/SKILL.md` 末尾追加：
```markdown
## Providers (Volcengine / MiniMax)

Auto-selected by environment variables (CLI unchanged):

- `VOLCENGINE_TTS_APPID` + `VOLCENGINE_TTS_ACCESS_TOKEN` set → Volcengine TTS (default).
- Only `MINIMAX_API_KEY` set → MiniMax TTS (`/v1/t2a_v2`).
- Force with `PODCAST_GENERATION_PROVIDER=volcengine|minimax`.

MiniMax overrides: `MINIMAX_API_HOST` (default `https://api.minimaxi.com`),
`MINIMAX_TTS_MODEL` (default `speech-2.6-hd`), `MINIMAX_TTS_VOICE_MALE`
(default `male-qn-qingse`), `MINIMAX_TTS_VOICE_FEMALE` (default `female-tianmei`).
```

- [ ] **Step 6: Commit**

```bash
git add skills/public/podcast-generation/scripts/generate.py skills/public/podcast-generation/SKILL.md tests/skills/test_podcast_generation.py
git commit -m "feat(podcast-generation): add MiniMax t2a_v2 provider with env auto-detect"
```

---

## Task 4: 新建 music-generation skill（用 skill-creator）

**Files:**
- Create: `skills/public/music-generation/SKILL.md`
- Create: `skills/public/music-generation/scripts/generate.py`
- Modify: `frontend/src/app/mock/api/skills/route.ts`
- Test: `tests/skills/test_music_generation.py`

- [ ] **Step 1: 用 skill-creator 脚手架生成骨架**

Run:
```bash
uv run --no-project --with pytest python skills/public/skill-creator/scripts/init_skill.py music-generation --path skills/public
```
Expected: 生成 `skills/public/music-generation/`（含 `SKILL.md` 占位 + `scripts/` + `references/` + `assets/`）。随后删除不需要的目录：
```bash
rm -rf skills/public/music-generation/references skills/public/music-generation/assets
rm -f skills/public/music-generation/scripts/example_script.py
```
（若脚手架生成的示例脚本名不同，删除 `scripts/` 下除将创建的 `generate.py` 外的占位文件。）

- [ ] **Step 2: 写失败测试**

`tests/skills/test_music_generation.py`:
```python
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

mus = load("music-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["MINIMAX_API_KEY", "MINIMAX_API_HOST", "MINIMAX_MUSIC_MODEL"]:
        monkeypatch.delenv(k, raising=False)


def _post_ok(captured):
    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp({"data": {"audio": b"songbytes".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})
    return fake_post


def test_with_lyrics_payload_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"title":"X","prompt":"pop, happy","lyrics":"[verse]\\nla la"}',
                    encoding="utf-8")
    out = tmp_path / "o.mp3"
    msg = mus.generate_music(str(spec), str(out))
    assert out.read_bytes() == b"songbytes"
    assert captured["url"].endswith("/v1/music_generation")
    assert captured["headers"]["Authorization"] == "Bearer m"
    assert captured["json"]["model"] == "music-2.6-free"
    assert captured["json"]["lyrics"] == "[verse]\nla la"
    assert captured["json"]["output_format"] == "hex"
    assert "Successfully generated music" in msg


def test_instrumental_sets_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"lofi beats","is_instrumental":true}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["is_instrumental"] is True
    assert "lyrics" not in captured["json"]
    assert "lyrics_optimizer" not in captured["json"]


def test_no_lyrics_uses_optimizer(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"sad ballad"}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["lyrics_optimizer"] is True
    assert "lyrics" not in captured["json"]


def test_model_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("MINIMAX_MUSIC_MODEL", "music-2.6")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz","lyrics":"[verse]\\nhi"}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["model"] == "music-2.6"


def test_raises_on_base_resp_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"base_resp": {"status_code": 1008, "status_msg": "no balance"}})

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x","lyrics":"[verse]\\ny"}', encoding="utf-8")
    with pytest.raises(Exception) as e:
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "1008" in str(e.value)


def test_missing_api_key_returns_message(monkeypatch, tmp_path):
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x"}', encoding="utf-8")
    msg = mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "MINIMAX_API_KEY" in msg
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_music_generation.py -v`
Expected: FAIL（`generate_music` 不存在）。

- [ ] **Step 4: 写实现 generate.py**

`skills/public/music-generation/scripts/generate.py`:
```python
import argparse
import json
import os

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"


def _check_base_resp(payload: dict) -> None:
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")


def generate_music(prompt_file: str, output_file: str) -> str:
    """Generate a song from a JSON spec via MiniMax /v1/music_generation.

    Spec JSON: {"title": str, "prompt": str, "lyrics"?: str, "is_instrumental"?: bool}
    - lyrics given        -> use them (supports [Verse]/[Chorus] structure tags, \\n lines)
    - is_instrumental true -> pure music, no lyrics needed
    - otherwise           -> lyrics_optimizer auto-writes lyrics from prompt
    """
    with open(prompt_file, "r", encoding="utf-8") as f:
        spec = json.load(f)

    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        return "MINIMAX_API_KEY is not set"

    prompt = spec.get("prompt", "")
    lyrics = spec.get("lyrics")
    is_instrumental = bool(spec.get("is_instrumental", False))

    body = {
        "model": os.getenv("MINIMAX_MUSIC_MODEL", "music-2.6-free"),
        "prompt": prompt,
        "output_format": "hex",
        "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
    }
    if lyrics:
        body["lyrics"] = lyrics
    elif is_instrumental:
        body["is_instrumental"] = True
    else:
        body["lyrics_optimizer"] = True

    host = os.getenv("MINIMAX_API_HOST", MINIMAX_DEFAULT_HOST).rstrip("/")
    response = requests.post(
        f"{host}/v1/music_generation",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    audio_hex = (payload.get("data") or {}).get("audio")
    if not audio_hex:
        raise Exception("MiniMax returned no audio data")

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_file, "wb") as f:
        f.write(bytes.fromhex(audio_hex))
    return f"Successfully generated music to {output_file}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate music using MiniMax API")
    parser.add_argument("--prompt-file", required=True,
                        help="Absolute path to JSON spec file {title, prompt, lyrics?, is_instrumental?}")
    parser.add_argument("--output-file", required=True, help="Output path for generated MP3")
    args = parser.parse_args()

    try:
        print(generate_music(args.prompt_file, args.output_file))
    except Exception as e:
        print(f"Error while generating music: {e}")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/test_music_generation.py -v`
Expected: PASS（6 个用例全过）。

- [ ] **Step 6: 写 SKILL.md**

整文件替换 `skills/public/music-generation/SKILL.md`:
```markdown
---
name: music-generation
description: Use this skill when the user requests to generate, create, compose, or produce music or songs — background music, theme songs, jingles, or instrumental tracks. Generates a song from a style/mood prompt and optional lyrics via the MiniMax music API.
---

# Music Generation Skill

## Overview

This skill generates songs (vocal or instrumental) from a structured JSON spec using the
MiniMax music generation API (`/v1/music_generation`). You describe the style/mood/scene in
`prompt`, optionally provide `lyrics`, and the script returns an MP3.

## Workflow

### Step 1: Understand Requirements

Identify the desired style, mood, scene, language, and whether the user wants vocals or a
pure instrumental track. Decide whether to supply lyrics or let the model write them.

### Step 2: Create the Spec JSON

Write a JSON file in `/mnt/user-data/workspace/` named `{descriptive-name}.json`:

```json
{
  "title": "Rainy Night Cafe",
  "prompt": "indie folk, melancholic, introspective, walking alone, cafe",
  "lyrics": "[verse]\nStreetlights glow the night wind sighs\n[chorus]\nPush the wooden door warm air inside"
}
```

Fields:
- `title` (optional): a human-readable name.
- `prompt` (required): style, mood, and scene. Drives the musical character.
- `lyrics` (optional): song lyrics. Use `\n` between lines and structure tags such as
  `[Intro]`, `[Verse]`, `[Pre Chorus]`, `[Chorus]`, `[Bridge]`, `[Outro]`.
- `is_instrumental` (optional, bool): set `true` for a pure instrumental track (no lyrics needed).

Behavior:
- `lyrics` provided → those lyrics are sung.
- `is_instrumental: true` → instrumental, no vocals.
- neither → the model auto-writes lyrics from `prompt` (`lyrics_optimizer`).

### Step 3: Execute Generation

```bash
python /mnt/skills/public/music-generation/scripts/generate.py \
  --prompt-file /mnt/user-data/workspace/rainy-night-cafe.json \
  --output-file /mnt/user-data/outputs/rainy-night-cafe.mp3
```

Parameters:
- `--prompt-file`: Absolute path to the JSON spec (required).
- `--output-file`: Absolute path for the output MP3 (required).

[!NOTE]
Do NOT read the python file, just call it with the parameters.

## Environment

- `MINIMAX_API_KEY` (required): your MiniMax interface key.
- `MINIMAX_API_HOST` (optional): default `https://api.minimaxi.com`.
- `MINIMAX_MUSIC_MODEL` (optional): default `music-2.6-free` (works for all API-key users);
  paid/Token-Plan users can set `music-2.6` for higher limits.

## Output Handling

- Music is saved as MP3 (typically in `/mnt/user-data/outputs/`).
- Share the generated file with the user using the present_files tool.
- Offer to iterate on style or lyrics if adjustments are needed.

## Notes

- Keep `prompt` focused on style/mood/scene; put the actual sung words in `lyrics`.
- For non-English songs, write `lyrics` in the target language.
```

- [ ] **Step 7: 在前端 mock skills 列表注册 music-generation**

修改 `frontend/src/app/mock/api/skills/route.ts`，在 `image-generation` 条目之后、`podcast-generation` 条目之前插入（保持字母序）：
```typescript
      {
        name: "music-generation",
        description:
          "Use this skill when the user requests to generate, create, compose, or produce music or songs — background music, theme songs, jingles, or instrumental tracks. Generates a song from a style/mood prompt and optional lyrics via the MiniMax music API.",
        license: null,
        category: "public",
        enabled: true,
      },
```

- [ ] **Step 8: 前端类型检查（确认 route.ts 无误）**

Run: `cd frontend && pnpm typecheck`
Expected: PASS（无新增类型错误）。若 `frontend` 依赖未安装，先 `pnpm install` 再 typecheck。

- [ ] **Step 9: Commit**

```bash
git add skills/public/music-generation frontend/src/app/mock/api/skills/route.ts tests/skills/test_music_generation.py
git commit -m "feat(music-generation): new MiniMax music skill via skill-creator"
```

---

## Task 5: 全量回归 + spec 覆盖核对

- [ ] **Step 1: 跑全部 skill 测试**

Run: `uv run --no-project --with pytest --with requests --with Pillow pytest tests/skills/ -v`
Expected: 全部 PASS（image 7 + video 6 + podcast 6 + music 6 = 25 用例）。

- [ ] **Step 2: 核对四个 skill 目录结构**

Run:
```bash
ls skills/public/music-generation skills/public/music-generation/scripts
git status --short
```
Expected: `music-generation/SKILL.md` + `scripts/generate.py` 存在；无意外残留的脚手架占位文件（references/assets 已删）。

- [ ] **Step 3: spec 覆盖自查（对照设计文档）**

逐条确认：image/video/podcast 三个 provider 自动判断 + 覆盖 ✔；music 新 skill ✔；hex 解码（podcast+music）✔；base64（image）✔；video 三步轮询 ✔；参考图 data URL（image subject_reference / video first_frame_image）✔；前端注册 ✔；环境变量齐全 ✔。如发现遗漏，补任务。

- [ ] **Step 4: 最终提交（如有零散改动）**

```bash
git add -A
git commit -m "test(skills): full MiniMax generation regression green" || echo "nothing to commit"
```
