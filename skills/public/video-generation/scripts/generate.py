import base64
import json
import os
import time
import urllib.request

import requests


# ---------------------------------------------------------------------------
# Auto model selection
# ---------------------------------------------------------------------------

def auto_select_model(prompt_file: str) -> str:
    """
    Pick the best model based on prompt content signals.

    Priority order:
      1. Veo3  — if dialogue / lip-sync is needed
      2. Kling — if premium / cinematic quality is requested
      3. Seedance — default (cheapest)
    """
    try:
        with open(prompt_file, "r") as f:
            content = f.read().lower()
    except Exception:
        return "seedance"

    dialogue_signals = [
        "says:", "say:", "speaks:", "speak:", "talks", "talking",
        "dialogue", "lip sync", "lip-sync", "interview", "monologue",
        "speech", "narrates", "narrating",
    ]
    if any(s in content for s in dialogue_signals):
        print("[Auto] Detected dialogue/lip-sync — selecting Veo3")
        return "veo3"

    quality_signals = [
        "cinematic", "film", "commercial", "premium", "high quality",
        "high-quality", "photorealistic", "hyperrealistic",
    ]
    if any(s in content for s in quality_signals):
        print("[Auto] Detected quality signal — selecting Kling")
        return "kling"

    print("[Auto] No special signals — selecting Seedance (default)")
    return "seedance"


# ---------------------------------------------------------------------------
# Prompt loading helper
# ---------------------------------------------------------------------------

def load_prompt(prompt_file: str) -> str:
    """
    Load prompt from file. Supports two formats:
      - Plain text: returned as-is
      - JSON: extracts the "prompt" key; falls back to full JSON string
    """
    with open(prompt_file, "r") as f:
        raw = f.read().strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "prompt" in data:
            return data["prompt"]
        # No "prompt" key — serialise the whole object as the prompt
        return json.dumps(data)
    except json.JSONDecodeError:
        return raw


# ---------------------------------------------------------------------------
# Kling 3.0
# ---------------------------------------------------------------------------

def generate_video_kling(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    generate_audio: bool = True,
) -> str:
    """Generate video using Kling 3.0 via Fal.ai."""
    import fal_client

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        return "FAL_KEY is not set"
    os.environ["FAL_KEY"] = fal_key

    prompt = load_prompt(prompt_file)

    # Validate aspect ratio
    valid_ratios = ("16:9", "9:16", "1:1")
    if aspect_ratio not in valid_ratios:
        print(f"[Kling] Unsupported aspect ratio '{aspect_ratio}', falling back to 16:9")
        aspect_ratio = "16:9"

    # Validate duration
    if duration not in ("5", "10"):
        print(f"[Kling] Unsupported duration '{duration}', falling back to 5s")
        duration = "5"

    if reference_images:
        ref_path = reference_images[0]
        image_url = fal_client.upload_file(ref_path)
        print(f"[Kling] image-to-video | ref: {ref_path} | {aspect_ratio} | {duration}s | audio={generate_audio}")
        result = fal_client.subscribe(
            "fal-ai/kling-video/v3/pro/image-to-video",
            arguments={
                "prompt": prompt,
                "image_url": image_url,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "negative_prompt": "blur, distort, and low quality",
                "generate_audio": generate_audio,
            },
        )
    else:
        print(f"[Kling] text-to-video | {aspect_ratio} | {duration}s | audio={generate_audio}")
        result = fal_client.subscribe(
            "fal-ai/kling-video/v3/pro/text-to-video",
            arguments={
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": aspect_ratio,
                "negative_prompt": "blur, distort, and low quality",
                "generate_audio": generate_audio,
            },
        )

    video_url = result.get("video", {}).get("url") if isinstance(result, dict) else None
    if not video_url:
        raise Exception(f"No video URL in Kling response: {result}")

    print(f"[Kling] Downloading → {output_file}")
    urllib.request.urlretrieve(video_url, output_file)
    return f"Video generated successfully: {output_file}"


# ---------------------------------------------------------------------------
# Seedance v1.5
# ---------------------------------------------------------------------------

def generate_video_seedance(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    generate_audio: bool = True,
) -> str:
    """Generate video using Seedance v1.5 Pro via Fal.ai (most affordable)."""
    import fal_client

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        return "FAL_KEY is not set"
    os.environ["FAL_KEY"] = fal_key

    prompt = load_prompt(prompt_file)

    # Validate aspect ratio
    valid_ratios = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
    if aspect_ratio not in valid_ratios:
        print(f"[Seedance] Unsupported aspect ratio '{aspect_ratio}', falling back to 16:9")
        aspect_ratio = "16:9"

    # Validate duration (4–12 seconds)
    try:
        dur_int = int(duration)
        if dur_int < 4 or dur_int > 12:
            print(f"[Seedance] Duration {dur_int}s out of range [4-12], falling back to 5s")
            dur_int = 5
    except ValueError:
        print(f"[Seedance] Invalid duration '{duration}', falling back to 5s")
        dur_int = 5

    if reference_images:
        ref_path = reference_images[0]
        image_url = fal_client.upload_file(ref_path)
        print(f"[Seedance] image-to-video | ref: {ref_path} | {aspect_ratio} | {dur_int}s | audio={generate_audio}")
        result = fal_client.subscribe(
            "fal-ai/bytedance/seedance/v1.5/pro/image-to-video",
            arguments={
                "prompt": prompt,
                "image_url": image_url,
                "duration": dur_int,
                "aspect_ratio": aspect_ratio,
                "generate_audio": generate_audio,
            },
        )
    else:
        print(f"[Seedance] text-to-video | {aspect_ratio} | {dur_int}s | audio={generate_audio}")
        result = fal_client.subscribe(
            "fal-ai/bytedance/seedance/v1.5/pro/text-to-video",
            arguments={
                "prompt": prompt,
                "duration": dur_int,
                "aspect_ratio": aspect_ratio,
                "generate_audio": generate_audio,
            },
        )

    video_url = result.get("video", {}).get("url") if isinstance(result, dict) else None
    if not video_url:
        raise Exception(f"No video URL in Seedance response: {result}")

    print(f"[Seedance] Downloading → {output_file}")
    urllib.request.urlretrieve(video_url, output_file)
    return f"Video generated successfully: {output_file}"


# ---------------------------------------------------------------------------
# Veo 3.1
# ---------------------------------------------------------------------------

VEO3_POLL_INTERVAL_SECONDS = 5
VEO3_TIMEOUT_SECONDS = 600  # 10 minutes max


def generate_video_veo3(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    """Generate video using Google Veo 3.1 (premium quality, always has audio)."""
    prompt = load_prompt(prompt_file)

    json_body: dict = {
        "instances": [{"prompt": prompt}],
    }

    if reference_images:
        reference_image_list = []
        for reference_image in reference_images:
            with open(reference_image, "rb") as f:
                image_b64 = base64.b64encode(f.read()).decode("utf-8")
            reference_image_list.append(
                {
                    "image": {"mimeType": "image/jpeg", "bytesBase64Encoded": image_b64},
                    "referenceType": "asset",
                }
            )
        json_body["instances"][0]["referenceImages"] = reference_image_list
        print(f"[Veo3] Using {len(reference_images)} reference image(s)")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"

    print(f"[Veo3] Submitting generation request...")
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning",
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=json_body,
    )
    response.raise_for_status()
    json_data = response.json()
    operation_name = json_data.get("name")
    if not operation_name:
        raise Exception(f"No operation name in Veo3 response: {json_data}")

    print(f"[Veo3] Polling operation: {operation_name}")
    elapsed = 0
    while elapsed < VEO3_TIMEOUT_SECONDS:
        time.sleep(VEO3_POLL_INTERVAL_SECONDS)
        elapsed += VEO3_POLL_INTERVAL_SECONDS

        poll_response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
            headers={"x-goog-api-key": api_key},
        )
        poll_response.raise_for_status()
        poll_data = poll_response.json()

        if poll_data.get("done", False):
            try:
                sample = poll_data["response"]["generateVideoResponse"]["generatedSamples"][0]
                url = sample["video"]["uri"]
            except (KeyError, IndexError) as e:
                raise Exception(f"Unexpected Veo3 response structure: {poll_data}") from e

            print(f"[Veo3] Downloading → {output_file}")
            _download_with_api_key(url, output_file, api_key)
            return f"Video generated successfully: {output_file}"

        print(f"[Veo3] Still processing... ({elapsed}s elapsed)")

    raise Exception(f"Veo3 generation timed out after {VEO3_TIMEOUT_SECONDS}s")


def _download_with_api_key(url: str, output_file: str, api_key: str) -> None:
    response = requests.get(url, headers={"x-goog-api-key": api_key})
    response.raise_for_status()
    with open(output_file, "wb") as f:
        f.write(response.content)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
    model: str = "seedance",
    duration: str = "5",
    generate_audio: bool = True,
) -> str:
    # Resolve auto model before dispatch
    if model == "auto":
        model = auto_select_model(prompt_file)

    if model == "veo3":
        return generate_video_veo3(prompt_file, reference_images, output_file, aspect_ratio)
    elif model == "kling":
        return generate_video_kling(prompt_file, reference_images, output_file, aspect_ratio, duration, generate_audio)
    elif model == "seedance":
        return generate_video_seedance(prompt_file, reference_images, output_file, aspect_ratio, duration, generate_audio)
    else:
        print(f"[Warning] Unknown model '{model}', falling back to Seedance")
        return generate_video_seedance(prompt_file, reference_images, output_file, aspect_ratio, duration, generate_audio)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos using AI video models")
    parser.add_argument(
        "--prompt-file",
        required=True,
        help="Absolute path to prompt file (plain text or JSON with 'prompt' key)",
    )
    parser.add_argument(
        "--reference-images",
        nargs="*",
        default=[],
        help="Absolute paths to reference images (space-separated). Triggers image-to-video mode.",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output path for generated video (.mp4)",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="16:9",
        help="Aspect ratio. Seedance: 21:9 16:9 4:3 1:1 3:4 9:16 | Kling: 16:9 9:16 1:1 | Veo3: 16:9",
    )
    parser.add_argument(
        "--model",
        default="seedance",
        choices=["seedance", "kling", "veo3", "auto"],
        help=(
            "Model to use: "
            "seedance (default, cheapest, 4-12s), "
            "kling (mid-tier, 5 or 10s), "
            "veo3 (premium, dialogue/lip-sync, always has audio), "
            "auto (agent picks based on prompt signals)"
        ),
    )
    parser.add_argument(
        "--duration",
        default="5",
        help="Duration in seconds. Seedance: 4-12 | Kling: 5 or 10 | Veo3: ignored (model decides)",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        default=False,
        help="Disable audio generation. Applies to Seedance and Kling only. Veo3 always generates audio.",
    )

    args = parser.parse_args()
    audio_enabled = not args.no_audio

    try:
        result = generate_video(
            args.prompt_file,
            args.reference_images,
            args.output_file,
            args.aspect_ratio,
            args.model,
            args.duration,
            audio_enabled,
        )
        print(result)
    except Exception as e:
        print(f"Error: {e}")
        raise SystemExit(1)