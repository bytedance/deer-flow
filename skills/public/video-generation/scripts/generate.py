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


def _ensure_output_dir(output_file: str) -> None:
    """Create the output file's parent directory so nested paths don't fail."""
    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)


def _check_base_resp(payload: dict) -> None:
    base = payload.get("base_resp") or {}
    if base.get("status_code", 0) != 0:
        raise Exception(f"MiniMax error {base.get('status_code')}: {base.get('status_msg')}")


def _guess_mime(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    return {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(ext, "image/jpeg")


def _to_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{_guess_mime(image_path)};base64,{b64}"


def _poll_video_task(host: str, auth: str, task_id: str,
                     max_attempts: int = 120, interval: int = 3) -> str:
    for _ in range(max_attempts):
        response = requests.get(
            f"{host}/v1/query/video_generation",
            headers={"Authorization": auth},
            params={"task_id": task_id},
            timeout=30,
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
        # Surface query-level errors (bad task_id, auth) that arrive as a non-zero
        # base_resp without a terminal status, then keep polling.
        _check_base_resp(payload)
        time.sleep(interval)
    raise Exception(f"MiniMax video task {task_id} timed out after {max_attempts} polls")


def _retrieve_file_url(host: str, auth: str, file_id: str) -> str:
    response = requests.get(
        f"{host}/v1/files/retrieve",
        headers={"Authorization": auth},
        params={"file_id": file_id},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    return payload["file"]["download_url"]


def _download(url: str, output_file: str) -> None:
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    _ensure_output_dir(output_file)
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
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()
    _check_base_resp(payload)
    task_id = payload["task_id"]
    file_id = _poll_video_task(host, auth, task_id)
    download_url = _retrieve_file_url(host, auth, file_id)
    _download(download_url, output_file)
    return f"The video has been generated successfully to {output_file}"


def download(url: str, output_file: str) -> None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    response = requests.get(url, headers={"x-goog-api-key": api_key}, timeout=300)
    response.raise_for_status()
    _ensure_output_dir(output_file)
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
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    operation_name = data["name"]
    while True:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
            headers={"x-goog-api-key": api_key},
            timeout=30,
        )
        response.raise_for_status()
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
    if provider in ("gemini", "google"):
        return _generate_video_gemini(prompt, reference_images, output_file)
    raise ValueError(f"Unknown video provider: {provider!r} (use 'gemini' or 'minimax')")


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
