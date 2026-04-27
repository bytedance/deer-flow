import base64
from abc import ABC, abstractmethod
from typing import Literal

import requests
from pydantic import BaseModel, Field


class ImageModelConfig(BaseModel):
    """
    Config for image generation models.
    """

    provider: Literal["gemini", "seedream"] | None = Field(
        default=None,
        description="Explicit image provider (recommended). If unset, DeerFlow infers provider from `name` for backward compatibility.",
    )
    name: str | None = Field(default=None, description="Unique identifier for the image model")
    model: str | None = Field(default=None, description="Name of the image model")
    api_base: str | None = Field(default=None, description="Base URL for the image model API")
    api_key: str | None = Field(default=None, description="API key for authenticating with the image model API")


class BaseImageGenerator(ABC):
    def __init__(self, cfg: ImageModelConfig):
        self.cfg = cfg

    @abstractmethod
    def _generate(
        self,
        prompt: str,
        reference_images: list[dict],
        aspect_ratio: str = "16:9",
    ) -> bytes:
        raise NotImplementedError

    @staticmethod
    def _request_json(method: str, url: str, *, timeout: int, **request_kwargs) -> dict:
        try:
            resp = requests.request(method, url, timeout=timeout, **request_kwargs)
            resp.raise_for_status()
        except Exception as e:
            status = getattr(resp, "status_code", "unknown") if "resp" in locals() else "unknown"
            text = getattr(resp, "text", "") if "resp" in locals() else ""
            error_msg = f"Request failed: {e}\nURL: {url}\nStatus: {status}\nResponse: {text}"
            raise RuntimeError(error_msg) from e
        return resp.json()


class GeminiImageGenerator(BaseImageGenerator):
    def __init__(self, cfg: ImageModelConfig):
        super().__init__(cfg)

    def _generate(
        self,
        prompt: str,
        reference_images: list[dict],
        aspect_ratio: str = "16:9",
    ) -> bytes:
        if not self.cfg.api_key:
            raise ValueError("api_key required")

        model = self.cfg.model or "gemini-3-flash-image"
        base_url = (self.cfg.api_base or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{base_url}/models/{model}:generateContent"

        headers = {"Content-Type": "application/json"}
        params = {"key": self.cfg.api_key}

        payload = {"contents": [{"parts": reference_images + [{"text": prompt}]}], "generationConfig": {"imageConfig": {"aspectRatio": aspect_ratio, "outputMimeType": "image/jpeg"}}}

        data = self._request_json("post", url, timeout=90, headers=headers, params=params, json=payload)

        candidate = data.get("candidates", [{}])[0]
        content_parts = candidate.get("content", {}).get("parts", [])

        for part in content_parts:
            if "inlineData" in part:
                return base64.b64decode(part["inlineData"]["data"])

        # If no inlineData found, raise error
        reason = candidate.get("finishReason", "UNKNOWN")
        raise RuntimeError(f"No image generated. Finish Reason: {reason}")


class VolcengineSeedreamImageGenerator(BaseImageGenerator):
    def __init__(self, cfg: ImageModelConfig):
        super().__init__(cfg)
        self.cfg = cfg

    def _generate(
        self,
        prompt: str,
        reference_images: list[dict],
        aspect_ratio: str = "16:9",
    ) -> bytes:
        if not self.cfg.api_base:
            raise ValueError("api_base required")
        if not self.cfg.api_key:
            raise ValueError("api_key required")
        if not self.cfg.model:
            raise ValueError("model required")

        url = f"{self.cfg.api_base.rstrip('/')}"
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}

        size_map = {"1:1": "1920x1920", "16:9": "2560x1440", "2:3": "1600x2400"}
        size = size_map.get(aspect_ratio, "2560x1440")

        payload = {"model": self.cfg.model, "prompt": prompt, "sequential_image_generation": "disabled", "response_format": "b64_json", "size": size, "stream": False, "watermark": False}
        seedream_reference_images = self._build_seedream_reference_images(reference_images)
        if seedream_reference_images:
            payload["reference_images"] = seedream_reference_images

        data = self._request_json("post", url, timeout=120, headers=headers, json=payload)

        images = data.get("data") or []
        if not images:
            raise RuntimeError("No image in response")

        b64img = images[0].get("b64_json")
        if b64img:
            return base64.b64decode(b64img)

        img_url = images[0].get("url")
        if img_url:
            img_resp = requests.get(img_url, timeout=30)
            img_resp.raise_for_status()
            return img_resp.content

        raise RuntimeError(f"No image data found in response: {data}")

    @staticmethod
    def _build_seedream_reference_images(reference_images: list[dict]) -> list[dict]:
        result = []
        for image in reference_images:
            inline_data = image.get("inlineData", {})
            data = inline_data.get("data")
            if not data:
                continue
            result.append(
                {
                    "image_base64": data,
                    "mime_type": inline_data.get("mimeType", "image/jpeg"),
                }
            )
        return result


def get_image_generate_fn(cfg: ImageModelConfig):
    if cfg.provider == "gemini":
        return GeminiImageGenerator(cfg)._generate
    if cfg.provider == "seedream":
        return VolcengineSeedreamImageGenerator(cfg)._generate

    raw_name = (cfg.name or "").strip()
    if not raw_name:
        raise ValueError("Image model config requires either 'provider' or 'name' for provider selection")
    name = raw_name.lower()
    has_gemini = "gemini" in name
    has_seedream = "seedream" in name
    if has_gemini and has_seedream:
        raise ValueError(f"Ambiguous image provider inferred from name {cfg.name!r}. Set image_generate_model.provider explicitly to one of: 'gemini', 'seedream'.")
    if has_gemini:
        return GeminiImageGenerator(cfg)._generate
    if has_seedream:
        return VolcengineSeedreamImageGenerator(cfg)._generate
    raise ValueError(f"Unsupported image provider inferred from config name: {cfg.name!r}. Set image_generate_model.provider explicitly to one of: 'gemini', 'seedream'.")
