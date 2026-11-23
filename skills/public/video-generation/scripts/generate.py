import base64
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import requests

MINIMAX_DEFAULT_HOST = "https://api.minimaxi.com"
GEMINI_API_HOST = "generativelanguage.googleapis.com"
MINIMAX_VIDEO_HOSTS = {
    "api.minimaxi.com",
    "api.minimax.io",
    "api.minimax.cn",
    "filecdn.minimax.chat",
    "cdn.hailuoai.video",
    "video-product.cdn.minimax.io",
}
MINIMAX_OSS_ENDPOINTS = {"oss-cn-wulanchabu.aliyuncs.com", "oss-cn-shanghai.aliyuncs.com"}
MAX_DOWNLOAD_REDIRECTS = 5
MAX_MINIMAX_API_REDIRECTS = 5


def _resolve_provider(override_env: str, existing_provider: str, has_existing_creds: bool) -> str:
    """Pick the provider: <SKILL>_PROVIDER override > existing creds > MiniMax fallback."""
    override = os.getenv(override_env)
    if override:
        return override.strip().lower()
    if has_existing_creds:
        return existing_provider
    if os.getenv("MINIMAX_API_KEY"):
        return "minimax"
    raise ValueError(f"No credentials found. Set GEMINI_API_KEY for {existing_provider}, or MINIMAX_API_KEY for minimax (optionally force with {override_env}).")


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


def _require_success(response: requests.Response) -> None:
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError(f"Unexpected HTTP status {response.status_code} from video provider")


def _api_origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("Invalid MiniMax API redirect origin")
    port = parsed.port
    # Check the entire authority, including brackets for an IPv6 literal.
    # hostname/port alone would discard user information or stray delimiters.
    host_field = parsed.netloc if port is None else parsed.netloc.rsplit(":", 1)[0]
    expected = f"[{host}]" if ":" in host else host
    if host_field.lower() != expected.lower():
        raise ValueError("Invalid MiniMax API redirect authority")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme, host, default_port if port is None else port


def _minimax_api_request(send, url: str, *, timeout: int, **kwargs) -> requests.Response:
    response = send(url, timeout=timeout, allow_redirects=False, **kwargs)
    if response.status_code in (307, 308):
        origin = _api_origin(response.request.url)
        with requests.Session() as session:
            for _ in range(MAX_MINIMAX_API_REDIRECTS):
                # Requests prepares the redirect with the original method and body,
                # and resolves Location against the full URL (including GET params).
                target = response.next
                if target is None:
                    raise ValueError("MiniMax API redirect has no destination")
                if _api_origin(target.url) != origin:
                    raise ValueError("MiniMax API redirect changes origin")
                settings = session.merge_environment_settings(target.url, {}, None, None, None)
                response = session.send(target, timeout=timeout, allow_redirects=False, **settings)
                if response.status_code not in (307, 308):
                    break
            else:
                raise ValueError("Too many MiniMax API redirects")
    _require_success(response)
    return response


def _guess_mime(image_path: str) -> str:
    ext = os.path.splitext(image_path)[1].lower()
    mime_types = {
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    try:
        return mime_types[ext]
    except KeyError:
        supported = ", ".join(mime_types)
        raise ValueError(f"Unsupported reference image extension for {image_path!r}. Supported extensions: {supported}") from None


def _to_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{_guess_mime(image_path)};base64,{b64}"


def _poll_video_task(host: str, auth: str, task_id: str, max_attempts: int = 120, interval: int = 3) -> str:
    for _ in range(max_attempts):
        response = _minimax_api_request(
            requests.get,
            f"{host}/v1/query/video_generation",
            headers={"Authorization": auth},
            params={"task_id": task_id},
            timeout=30,
        )
        payload = response.json()
        status = payload.get("status")
        if status == "Success":
            return payload["file_id"]
        if status == "Fail":
            base = payload.get("base_resp") or {}
            raise Exception(f"MiniMax video task {task_id} failed: {base.get('status_code')} {base.get('status_msg')}")
        # Surface query-level errors (bad task_id, auth) that arrive as a non-zero
        # base_resp without a terminal status, then keep polling.
        _check_base_resp(payload)
        time.sleep(interval)
    raise Exception(f"MiniMax video task {task_id} timed out after {max_attempts} polls")


def _poll_gemini_operation(api_key: str, operation_name: str, max_attempts: int = 240, interval: int = 3) -> str:
    """Wait for a Veo long-running operation and return the generated video URI.

    Bounded like ``_poll_video_task`` so a stuck or rejected operation fails with a
    diagnosis instead of polling forever. The default budget (12 minutes) leaves
    room for queueing, which routinely outlasts a short generation.
    """
    for _ in range(max_attempts):
        response = requests.get(
            f"https://{GEMINI_API_HOST}/v1beta/{operation_name}",
            headers={"x-goog-api-key": api_key},
            timeout=30,
            allow_redirects=False,
        )
        _require_success(response)
        payload = response.json()
        if not payload.get("done", False):
            time.sleep(interval)
            continue
        error = payload.get("error") or {}
        if error:
            raise Exception(f"Gemini video operation {operation_name} failed: {error.get('code')} {error.get('message')}")
        video_response = (payload.get("response") or {}).get("generateVideoResponse") or {}
        samples = video_response.get("generatedSamples") or []
        if not samples:
            # A filtered prompt finishes successfully without any sample.
            reasons = "; ".join(video_response.get("raiMediaFilteredReasons") or [])
            detail = f": {reasons}" if reasons else ""
            raise Exception(f"Gemini video operation {operation_name} returned no generated sample{detail}")
        uri = (samples[0].get("video") or {}).get("uri")
        if not uri:
            raise Exception(f"Gemini video operation {operation_name} returned a sample without a video URI")
        return uri
    raise Exception(f"Gemini video operation {operation_name} timed out after {max_attempts} polls")


def _retrieve_file_url(host: str, auth: str, file_id: str) -> str:
    response = _minimax_api_request(
        requests.get,
        f"{host}/v1/files/retrieve",
        headers={"Authorization": auth},
        params={"file_id": file_id},
        timeout=30,
    )
    payload = response.json()
    _check_base_resp(payload)
    return payload["file"]["download_url"]


def _download_host(url: str, *, gemini: bool) -> str:
    if not isinstance(url, str) or re.search(r"[\x00-\x20\x7f\\]", url):
        raise ValueError("Invalid video download URL")
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != "https" or not host or parsed.netloc.lower() not in {host, f"{host}:443"}:
        raise ValueError("Video downloads require an HTTPS host on port 443 without user information")
    if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z][a-z0-9-]*", host):
        raise ValueError("Invalid video download hostname")

    # Only the storage provider controls DNS for bucket endpoints under these
    # exact suffixes. A bucket name is one DNS label.
    endpoint = host.partition(".")[2]
    if gemini:
        trusted = host in {GEMINI_API_HOST, "storage.googleapis.com"}
        storage_endpoints = {"storage.googleapis.com"}
    else:
        extra_hosts = os.getenv("MINIMAX_VIDEO_DOWNLOAD_HOSTS", "").split(",")
        trusted = host in MINIMAX_VIDEO_HOSTS or host in {name.strip().lower() for name in extra_hosts}
        storage_endpoints = MINIMAX_OSS_ENDPOINTS
    if trusted or endpoint in storage_endpoints:
        return host
    raise ValueError(f"Video download host {host!r} is outside the provider allowlist")


def _download(url: str, output_file: str, *, gemini_api_key: str = "") -> None:
    headers = {"x-goog-api-key": gemini_api_key} if gemini_api_key else {}
    for _ in range(MAX_DOWNLOAD_REDIRECTS + 1):
        host = _download_host(url, gemini=bool(gemini_api_key))
        if host != GEMINI_API_HOST:
            headers = {}
        response = requests.get(url, headers=headers, timeout=300, allow_redirects=False)
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location")
            if not location:
                raise ValueError("Video download redirect has no destination")
            url = urljoin(url, location)
            continue
        _require_success(response)
        _ensure_output_dir(output_file)
        with open(output_file, "wb") as f:
            f.write(response.content)
        return
    raise ValueError("Too many video download redirects")


def _generate_video_minimax(prompt: str, reference_images: list[str], output_file: str) -> str:
    minimax_api_key = os.getenv("MINIMAX_API_KEY")
    if not minimax_api_key:
        raise ValueError("MINIMAX_API_KEY is not set")
    host = _minimax_host()
    auth = f"Bearer {minimax_api_key}"
    body = {"model": os.getenv("MINIMAX_VIDEO_MODEL", "MiniMax-Hailuo-2.3"), "prompt": prompt}
    # Hailuo models take explicit resolution/duration in the request body. Values pass
    # through unvalidated (beyond the integer check) so newer tiers with different
    # allowlists — e.g. H3's per-second 4-15s durations — stay usable without a script
    # change; the API rejects invalid combinations via base_resp.
    resolution = os.getenv("MINIMAX_VIDEO_RESOLUTION", "").strip()
    if resolution:
        body["resolution"] = resolution
    duration = os.getenv("MINIMAX_VIDEO_DURATION", "").strip()
    if duration:
        error = f"MINIMAX_VIDEO_DURATION must be an integer number of seconds (e.g. 6 or 10), got {duration!r}"
        if not duration.isdecimal():
            raise ValueError(error)
        try:
            body["duration"] = int(duration)
        except ValueError as exc:
            raise ValueError(error) from exc
    if reference_images:
        body["first_frame_image"] = _to_data_url(reference_images[0])
    response = _minimax_api_request(
        requests.post,
        f"{host}/v1/video_generation",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        json=body,
        timeout=60,
    )
    payload = response.json()
    _check_base_resp(payload)
    task_id = payload["task_id"]
    file_id = _poll_video_task(host, auth, task_id)
    download_url = _retrieve_file_url(host, auth, file_id)
    _download(download_url, output_file)
    return f"The video has been generated successfully to {output_file}"


def download(url: str, output_file: str) -> None:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    _download(url, output_file, gemini_api_key=gemini_api_key)


def _generate_video_gemini(prompt: str, reference_images: list[str], output_file: str, aspect_ratio: str = "16:9") -> str:
    reference_payload = []
    request_json = {
        "instances": [{"prompt": prompt}],
        "parameters": {"aspectRatio": aspect_ratio},
    }
    for reference_image in reference_images:
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        reference_payload.append({"image": {"mimeType": _guess_mime(reference_image), "bytesBase64Encoded": image_b64}, "referenceType": "asset"})
    if reference_payload:
        request_json["instances"][0]["referenceImages"] = reference_payload
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not set")
    response = requests.post(
        f"https://{GEMINI_API_HOST}/v1beta/models/veo-3.1-generate-preview:predictLongRunning",
        headers={"x-goog-api-key": gemini_api_key, "Content-Type": "application/json"},
        json=request_json,
        timeout=60,
        allow_redirects=False,
    )
    _require_success(response)
    data = response.json()
    operation_name = data["name"]
    download_url = _poll_gemini_operation(gemini_api_key, operation_name)
    download(download_url, output_file)
    return f"The video has been generated successfully to {output_file}"


def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    with open(prompt_file, encoding="utf-8") as f:
        prompt = f.read()
    provider = _resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", bool(os.getenv("GEMINI_API_KEY")))
    if provider == "minimax":
        # MiniMax video uses resolution/duration, not aspect_ratio; aspect_ratio ignored.
        return _generate_video_minimax(prompt, reference_images, output_file)
    if provider in ("gemini", "google"):
        return _generate_video_gemini(prompt, reference_images, output_file, aspect_ratio)
    raise ValueError(f"Unknown video provider: {provider!r} (use 'gemini' or 'minimax')")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos using Gemini or MiniMax API")
    parser.add_argument("--prompt-file", required=True, help="Absolute path to JSON prompt file")
    parser.add_argument("--reference-images", nargs="*", default=[], help="Absolute paths to reference images (space-separated)")
    parser.add_argument("--output-file", required=True, help="Output path for generated video")
    parser.add_argument("--aspect-ratio", required=False, default="16:9", help="Aspect ratio of the generated video (Gemini only)")
    args = parser.parse_args()

    try:
        print(generate_video(args.prompt_file, args.reference_images, args.output_file, args.aspect_ratio))
    except Exception as e:
        print(f"Error while generating video: {e}", file=sys.stderr)
        sys.exit(1)
