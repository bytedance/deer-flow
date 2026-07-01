"""Custom rvLLM provider built on top of LangChain ChatOpenAI.

rvLLM (https://github.com/m0at/rvllm) is a native Rust inference server that
speaks the OpenAI-compatible API through ``rvllm-server``. It serves greedy
models with server-side MTP speculative decoding: a small drafter proposes K
tokens, the target verifies them in a single forward pass, and a greedy
accept/reject keeps the emitted tokens *identical* to plain greedy decoding.
Speculation changes throughput only, never the output (rvLLM's "identity
guarantee").

Because rvllm-server is greedy by default, this provider defaults to
deterministic decoding (``temperature=0``) so multi-step agent trajectories are
reproducible across runs. Callers can still opt into sampling by setting
``temperature`` explicitly on the model config. The endpoint is otherwise a
plain OpenAI-compatible chat-completions API, so the rest of ChatOpenAI's
behavior (tool calls, streaming, usage accounting) is inherited unchanged.
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI


class RvllmChatModel(ChatOpenAI):
    """ChatOpenAI variant tuned for rvllm-server's greedy identity guarantee."""

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **kwargs: Any) -> None:
        # rvllm-server is greedy by default and its speculative decode preserves
        # greedy token identity, so default to deterministic decoding unless the
        # caller explicitly opts into sampling. An explicit ``temperature``
        # (including a non-zero value) always wins.
        kwargs.setdefault("temperature", 0.0)
        super().__init__(**kwargs)

    @property
    def _llm_type(self) -> str:
        return "rvllm-openai-compatible"
