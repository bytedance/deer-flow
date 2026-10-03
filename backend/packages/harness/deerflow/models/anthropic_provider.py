"""Anthropic adapters used by DeerFlow's model factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from typing import Any, NamedTuple

import anthropic
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableConfig
from pydantic import PrivateAttr


class _AsyncClientContext(NamedTuple):
    task: asyncio.Task[Any]
    client: anthropic.AsyncClient
    open_streams: list[AsyncIterator[Any]]


class LoopIsolatedChatAnthropic(ChatAnthropic):
    """Use and close a private Anthropic async transport for each model operation.

    langchain-anthropic caches its default HTTPX async client process-wide by
    URL/timeout/proxy. That client can outlive the asyncio loop that first used
    it, while Anthropic child agents run in separate loops. This adapter owns
    and closes its SDK transport around async invocations and both streaming
    entrypoints, while preserving the inherited payload, tool and sync paths.
    Same-task nested calls reuse the client; child tasks that inherited the
    ContextVar do not. See https://github.com/anthropics/anthropic-sdk-python#managing-http-resources.
    """

    _active_async_client: ContextVar[_AsyncClientContext | None] = PrivateAttr(default_factory=lambda: ContextVar("deerflow_anthropic_async_client", default=None))

    @property
    def _async_client(self) -> anthropic.AsyncClient:
        context = self._active_async_client.get()
        if context is None or context.task is not asyncio.current_task():
            raise RuntimeError("Anthropic async client is only available during model invocation")
        return context.client

    def _create_async_client(self) -> anthropic.AsyncClient:
        client_params = self._client_params
        http_client_params: dict[str, Any] = {}
        if client_params.get("base_url") is not None:
            http_client_params["base_url"] = client_params["base_url"]
        if "timeout" in client_params:
            http_client_params["timeout"] = client_params["timeout"]
        if self.anthropic_proxy is not None:
            http_client_params["proxy"] = self.anthropic_proxy
        http_client = anthropic.DefaultAsyncHttpxClient(**http_client_params)
        return anthropic.AsyncClient(**client_params, http_client=http_client)

    @asynccontextmanager
    async def _async_client_scope(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Anthropic async client scope requires an asyncio task")
        active = self._active_async_client.get()
        if active is not None and active.task is task:
            yield
            return

        client_context = _AsyncClientContext(task, self._create_async_client(), [])
        token: Token[_AsyncClientContext | None] = self._active_async_client.set(client_context)
        try:
            yield
        finally:
            try:
                for upstream in client_context.open_streams:
                    await upstream.aclose()
            finally:
                try:
                    self._active_async_client.reset(token)
                finally:
                    client_context.open_streams.clear()
                    await client_context.client.close()

    async def _agenerate_with_cache(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        async with self._async_client_scope():
            return await super()._agenerate_with_cache(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _stream_with_client(
        self,
        upstream: AsyncIterator[Any],
        client: anthropic.AsyncClient,
        open_streams: list[AsyncIterator[Any]],
        *,
        close_client: bool,
    ) -> AsyncIterator[Any]:
        try:
            while True:
                task = asyncio.current_task()
                if task is None:
                    raise RuntimeError("Anthropic streaming requires an asyncio task")
                token: Token[_AsyncClientContext | None] = self._active_async_client.set(_AsyncClientContext(task, client, open_streams))
                try:
                    chunk = await anext(upstream)
                except StopAsyncIteration:
                    break
                finally:
                    self._active_async_client.reset(token)
                yield chunk
        finally:
            try:
                await upstream.aclose()
            finally:
                if close_client:
                    await client.close()

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        *,
        stream_usage: bool | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        upstream = super()._astream(messages, stop=stop, run_manager=run_manager, stream_usage=stream_usage, **kwargs).__aiter__()
        task = asyncio.current_task()
        active = self._active_async_client.get()
        if task is not None and active is not None and active.task is task:
            active.open_streams.append(upstream)
            try:
                async for chunk in upstream:
                    yield chunk
            finally:
                await upstream.aclose()
            return

        client = self._create_async_client()
        stream = self._stream_with_client(upstream, client, [], close_client=True)
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()

    async def astream(
        self,
        input: LanguageModelInput,
        config: RunnableConfig | None = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[AIMessageChunk]:
        client = self._create_async_client()
        upstream = super().astream(input, config=config, stop=stop, **kwargs).__aiter__()
        open_streams: list[AsyncIterator[Any]] = []
        stream = self._stream_with_client(upstream, client, open_streams, close_client=False)
        try:
            async for chunk in stream:
                yield chunk
        finally:
            try:
                await stream.aclose()
            finally:
                try:
                    for open_stream in open_streams:
                        await open_stream.aclose()
                finally:
                    await client.close()
