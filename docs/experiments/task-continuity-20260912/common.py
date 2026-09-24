from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import tiktoken

ROOT = Path(__file__).resolve().parent
ENC = tiktoken.get_encoding("cl100k_base")
PROTOCOL = json.loads((ROOT / "protocol.json").read_text())


def stable(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(stable(value).encode()).hexdigest()


def tokens(text: str) -> int:
    return len(ENC.encode(text, disallowed_special=()))


def clip(text: str, limit: int, *, tail: bool = False) -> str:
    ids = ENC.encode(text, disallowed_special=())
    return ENC.decode(ids[-limit:] if tail else ids[:limit]) if limit > 0 else ""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temp.replace(path)


class CallFailure(RuntimeError):
    pass


class LiveClient:
    """Endpoint values/credentials live only in a private external runtime file.

    Cache identity binds the entire request, model and endpoint hash. Logs contain
    public/synthetic request data and sanitized outcomes, never endpoint/auth data.
    """

    def __init__(self, config_path: str, concurrency: int = 6):
        self.settings = json.loads(Path(config_path).read_text())
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(180, connect=20), trust_env=False)
        self.chat_sem = asyncio.Semaphore(concurrency)
        self.embed_sem = asyncio.Semaphore(2)
        self.cache = ROOT / "cache"
        self.cache.mkdir(exist_ok=True)
        self.calls: list[dict] = []

    async def close(self) -> None:
        await self.http.aclose()

    async def chat(self, messages: list[dict], *, max_tokens: int, tag: str,
                   tools: list[dict] | None = None, seed: int = 20260912, require_cached: bool = False) -> dict:
        payload: dict = {"model": self.settings["llm_model"], "messages": messages,
                         "max_tokens": max_tokens, "temperature": 0,
                         "reasoning_effort": "none", "seed": seed, "stream": False}
        if tools:
            payload.update(tools=tools, tool_choice="auto", parallel_tool_calls=False)
        key = digest({"payload": payload, "endpoint_hash": digest(self.settings["llm_base"])})
        dest = self.cache / "chat" / f"{key}.json"
        if dest.exists():
            result = json.loads(dest.read_text())
            self.calls.append({"tag": tag, "key": key, "cached": True, **result["metrics"]})
            return result
        if require_cached:
            raise CallFailure(f"Missing cached prefix for {tag}; refusing to rerun original call")
        start = time.monotonic()
        attempts = []
        async with self.chat_sem:
            for attempt in range(3):
                try:
                    r = await self.http.post(self.settings["llm_base"] + "/chat/completions", json=payload)
                    if r.status_code != 200:
                        attempts.append({"status": r.status_code})
                        if r.status_code == 429 or r.status_code >= 500:
                            await asyncio.sleep(1 + attempt)
                            continue
                        raise CallFailure(f"HTTP {r.status_code}")
                    data = r.json()
                    choice = data["choices"][0]
                    message = choice["message"]
                    # Only final text/tool calls; do not retain hidden reasoning.
                    clean_message = {k: message[k] for k in ("role", "content", "tool_calls") if k in message}
                    metrics = {"seconds": time.monotonic() - start, "usage": data.get("usage", {}),
                               "finish_reason": choice.get("finish_reason"), "attempts": attempt + 1,
                               "response_model": data.get("model"), "prior_errors": attempts}
                    result = {"message": clean_message, "metrics": metrics, "request_hash": key}
                    write_json(dest, result)
                    self.calls.append({"tag": tag, "key": key, "cached": False, **metrics})
                    return result
                except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                    attempts.append({"error_type": type(exc).__name__})
                    await asyncio.sleep(1 + attempt)
        error = {"tag": tag, "key": key, "errors": attempts, "seconds": time.monotonic() - start}
        write_json(self.cache / "errors" / f"{key}.json", error)
        raise CallFailure(f"Provider failed for {tag}: {stable(attempts)}")

    async def embed(self, texts: list[str], *, query: bool = False, tag: str = "embed") -> np.ndarray:
        if not texts:
            return np.empty((0, 1024), dtype=np.float32)
        instruction = "Instruct: Retrieve relevant historical messages and tool records that provide evidence for the current question or task.\nQuery: "
        inputs = [instruction + t if query else t for t in texts]
        payload = {"model": self.settings["embedding_model"], "input": inputs, "encoding_format": "float"}
        key = digest({"payload": payload, "endpoint_hash": digest(self.settings["embedding_base"])})
        dest = self.cache / "embeddings" / f"{key}.npz"
        if dest.exists():
            with np.load(dest) as blob:
                vectors = blob["vectors"]
            meta = json.loads(dest.with_suffix(".json").read_text())
            self.calls.append({"tag": tag, "key": key, "cached": True, **meta})
            return vectors
        start = time.monotonic()
        errors = []
        async with self.embed_sem:
            for attempt in range(3):
                try:
                    r = await self.http.post(self.settings["embedding_base"] + "/embeddings",
                        headers={"Authorization": "Bearer " + self.settings["embedding_key"]}, json=payload)
                    if r.status_code != 200:
                        errors.append({"status": r.status_code})
                        if r.status_code == 429 or r.status_code >= 500:
                            await asyncio.sleep(1 + attempt)
                            continue
                        raise CallFailure(f"Embedding HTTP {r.status_code}")
                    data = r.json()
                    items = sorted(data["data"], key=lambda x: x["index"])
                    if [x["index"] for x in items] != list(range(len(inputs))):
                        raise CallFailure("Embedding response indices/count mismatch")
                    vectors = np.asarray([x["embedding"] for x in items], dtype=np.float32)
                    if vectors.shape != (len(inputs), 1024) or not np.isfinite(vectors).all():
                        raise CallFailure("Embedding shape/nonfinite validation failed")
                    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                    if np.any(norms == 0):
                        raise CallFailure("Zero embedding")
                    vectors = vectors / norms
                    dest.parent.mkdir(exist_ok=True)
                    np.savez_compressed(dest, vectors=vectors)
                    metrics = {"seconds": time.monotonic() - start, "count": len(inputs),
                               "input_tokens_proxy": sum(tokens(x) for x in inputs), "attempts": attempt + 1,
                               "usage": data.get("usage") or {}}
                    write_json(dest.with_suffix(".json"), metrics)
                    self.calls.append({"tag": tag, "key": key, "cached": False, **metrics})
                    return vectors
                except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                    errors.append({"error_type": type(exc).__name__})
                    await asyncio.sleep(1 + attempt)
        write_json(self.cache / "errors" / f"{key}.json", {"tag": tag, "errors": errors})
        raise CallFailure(f"Embedding failed: {stable(errors)}")


def usage_sum(calls: list[dict]) -> dict:
    return {"calls": len(calls), "prompt_tokens": sum(c.get("usage", {}).get("prompt_tokens", 0) for c in calls),
            "completion_tokens": sum(c.get("usage", {}).get("completion_tokens", 0) for c in calls),
            "request_seconds": sum(c.get("seconds", 0) for c in calls),
            "truncated_generations": sum(c.get("finish_reason") == "length" for c in calls)}
