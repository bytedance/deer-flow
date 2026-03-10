import base64
import os
import time
import urllib.request

import requests


def generate_video_kling(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
    duration: str = "5",
    generate_audio: bool = True,
) -> str:
    """Generate video using Kling 3.0 via Fal.ai (default, cost-effective)."""
    import fal_client

    fal_key = os.getenv("FAL_KEY")
    if not fal_key:
        return "FAL_KEY is not set"
    os.environ["FAL_KEY"] = fal_key

    with open(prompt_file, "r") as f:
        prompt = f.read()

    # Validate aspect ratio for Kling
    valid_ratios = ("16:9", "9:16", "1:1")
    if aspect_ratio not in valid_ratios:
        aspect_ratio = "16:9"

    # Validate duration
    if duration not in ("5", "10"):
        duration = "5"

    if reference_images:
        # Image-to-video: use first reference image
        ref_path = reference_images[0]
        # Upload image to fal storage
        image_url = fal_client.upload_file(ref_path)

        print(f"Using image-to-video with reference: {ref_path}")
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
        # Text-to-video
        print("Using text-to-video")
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
        raise Exception(f"No video URL in response: {result}")

    # Download video
    print(f"Downloading video to {output_file}")
    urllib.request.urlretrieve(video_url, output_file)

    return f"The video has been generated successfully to {output_file}"


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

    with open(prompt_file, "r") as f:
        prompt = f.read()

    # Validate aspect ratio for Seedance
    valid_ratios = ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
    if aspect_ratio not in valid_ratios:
        aspect_ratio = "16:9"

    # Validate duration (4-12 seconds)
    try:
        dur_int = int(duration)
        if dur_int < 4 or dur_int > 12:
            dur_int = 5
    except ValueError:
        dur_int = 5

    if reference_images:
        # Image-to-video: use first reference image
        ref_path = reference_images[0]
        image_url = fal_client.upload_file(ref_path)

        print(f"Using Seedance image-to-video with reference: {ref_path}")
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
        # Text-to-video
        print("Using Seedance text-to-video")
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
        raise Exception(f"No video URL in response: {result}")

    # Download video
    print(f"Downloading video to {output_file}")
    urllib.request.urlretrieve(video_url, output_file)

    return f"The video has been generated successfully to {output_file}"


def generate_video_veo3(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
) -> str:
    """Generate video using Google Veo 3.1 (higher quality, higher cost)."""
    with open(prompt_file, "r") as f:
        prompt = f.read()
    referenceImages = []
    i = 0
    json_body = {
        "instances": [{"prompt": prompt}],
    }
    for reference_image in reference_images:
        i += 1
        with open(reference_image, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        referenceImages.append(
            {
                "image": {"mimeType": "image/jpeg", "bytesBase64Encoded": image_b64},
                "referenceType": "asset",
            }
        )
    if i > 0:
        json_body["instances"][0]["referenceImages"] = referenceImages
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/models/veo-3.1-generate-preview:predictLongRunning",
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json=json_body,
    )
    json_data = response.json()
    operation_name = json_data["name"]
    while True:
        response = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/{operation_name}",
            headers={
                "x-goog-api-key": api_key,
            },
        )
        json_data = response.json()
        if json_data.get("done", False):
            sample = json_data["response"]["generateVideoResponse"]["generatedSamples"][0]
            url = sample["video"]["uri"]
            download_with_api_key(url, output_file)
            break
        time.sleep(3)
    return f"The video has been generated successfully to {output_file}"


def download_with_api_key(url: str, output_file: str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "GEMINI_API_KEY is not set"
    response = requests.get(
        url,
        headers={
            "x-goog-api-key": api_key,
        },
    )
    with open(output_file, "wb") as f:
        f.write(response.content)


def generate_video(
    prompt_file: str,
    reference_images: list[str],
    output_file: str,
    aspect_ratio: str = "16:9",
    model: str = "seedance",
    duration: str = "5",
    generate_audio: bool = True,
) -> str:
    if model == "veo3":
        # Veo 3 always generates audio (controlled via prompt text, no API toggle)
        return generate_video_veo3(prompt_file, reference_images, output_file, aspect_ratio)
    elif model == "seedance":
        return generate_video_seedance(prompt_file, reference_images, output_file, aspect_ratio, duration, generate_audio)
    else:
        return generate_video_kling(prompt_file, reference_images, output_file, aspect_ratio, duration, generate_audio)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate videos using AI")
    parser.add_argument(
        "--prompt-file",
        required=True,
        help="Absolute path to JSON prompt file",
    )
    parser.add_argument(
        "--reference-images",
        nargs="*",
        default=[],
        help="Absolute paths to reference images (space-separated)",
    )
    parser.add_argument(
        "--output-file",
        required=True,
        help="Output path for generated video",
    )
    parser.add_argument(
        "--aspect-ratio",
        required=False,
        default="16:9",
        help="Aspect ratio of the generated video. Kling: 16:9, 9:16, 1:1. Seedance: 21:9, 16:9, 4:3, 1:1, 3:4, 9:16.",
    )
    parser.add_argument(
        "--model",
        required=False,
        default="seedance",
        choices=["seedance", "kling", "veo3"],
        help="Video model to use: seedance (default, most affordable), kling (mid-tier), or veo3 (premium, requires GEMINI_API_KEY)",
    )
    parser.add_argument(
        "--duration",
        required=False,
        default="5",
        help="Video duration in seconds. Seedance: 4-12. Kling: 5 or 10. Default 5.",
    )
    parser.add_argument(
        "--generate-audio",
        action="store_true",
        default=True,
        help="Generate audio with the video (Kling: toggleable, Veo3: always on). Default: enabled.",
    )
    parser.add_argument(
        "--no-audio",
        action="store_true",
        default=False,
        help="Disable audio generation (Kling only). Veo3 always generates audio.",
    )

    args = parser.parse_args()

    # --no-audio overrides --generate-audio
    audio_enabled = not args.no_audio

    try:
        print(
            generate_video(
                args.prompt_file,
                args.reference_images,
                args.output_file,
                args.aspect_ratio,
                args.model,
                args.duration,
                audio_enabled,
            )
        )
    except Exception as e:
        print(f"Error while generating video: {e}")
