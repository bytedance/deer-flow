"""App-owned RunSpec builder."""

from __future__ import annotations

import re
import uuid

from langchain_core.messages import HumanMessage

from deerflow.runtime.runs.types import CheckpointRequest, RunScope, RunSpec
from deerflow.runtime.stream_bridge import JSONValue

from .request_adapter import AdaptedRunRequest

type JSONMapping = dict[str, JSONValue]
type GraphInput = dict[str, object]
type RunnableConfigDict = dict[str, object]


class UnsupportedRunFeatureError(ValueError):
    """Raised when a phase1-unsupported feature is requested."""

    pass


class RunSpecBuilder:
    """
    Build RunSpec from AdaptedRunRequest.

    Phase 1 rules:
    1. messages-tuple normalized to messages
    2. enqueue not supported
    3. rollback not supported
    4. after_seconds not supported
    5. stream_resumable accepted
    6. stateless auto-generates temporary thread
    """

    # Phase 1 unsupported features
    UNSUPPORTED_MULTITASK_STRATEGIES = {"enqueue"}
    UNSUPPORTED_ACTIONS = {"rollback"}

    # Default stream modes
    DEFAULT_STREAM_MODES = ["values", "messages"]
    CONTEXT_CONFIGURABLE_KEYS = frozenset({
        "model_name",
        "mode",
        "thinking_enabled",
        "reasoning_effort",
        "is_plan_mode",
        "subagent_enabled",
        "max_concurrent_subagents",
    })
    DEFAULT_ASSISTANT_ID = "lead_agent"

    @staticmethod
    def _as_json_mapping(value: JSONValue | None) -> JSONMapping | None:
        return value if isinstance(value, dict) else None

    @staticmethod
    def _as_string_list(value: JSONValue | None) -> list[str] | None:
        if not isinstance(value, list):
            return None
        return [item for item in value if isinstance(item, str)]

    def build(self, request: AdaptedRunRequest) -> RunSpec:
        """Build RunSpec from adapted request."""
        body = request.body

        # Validate phase1 constraints
        self._validate_constraints(body)

        # Build scope
        scope = self._build_scope(request)

        # Normalize stream modes
        stream_modes = self._normalize_stream_modes(body.get("stream_mode"))

        # Build checkpoint request
        checkpoint_request = self._build_checkpoint_request(body)

        config = self._build_runnable_config(
            thread_id=scope.thread_id,
            request_config=self._as_json_mapping(body.get("config")),
            metadata=self._as_json_mapping(body.get("metadata")),
            assistant_id=body.get("assistant_id"),
            context=self._as_json_mapping(body.get("context")),
        )

        return RunSpec(
            intent=request.intent,
            scope=scope,
            assistant_id=body.get("assistant_id") if isinstance(body.get("assistant_id"), str) else None,
            input=self._normalize_input(self._as_json_mapping(body.get("input"))),
            command=self._as_json_mapping(body.get("command")),
            runnable_config=config,
            context=self._as_json_mapping(body.get("context")),
            metadata=self._as_json_mapping(body.get("metadata")) or {},
            stream_modes=stream_modes,
            stream_subgraphs=bool(body.get("stream_subgraphs", False)),
            stream_resumable=bool(body.get("stream_resumable", False)),
            on_disconnect=body.get("on_disconnect", "cancel") if body.get("on_disconnect") in {"cancel", "continue"} else "cancel",
            on_completion=body.get("on_completion", "keep") if body.get("on_completion") in {"delete", "keep"} else "keep",
            multitask_strategy=body.get("multitask_strategy", "reject") if body.get("multitask_strategy") in {"reject", "interrupt"} else "reject",
            interrupt_before="*" if body.get("interrupt_before") == "*" else self._as_string_list(body.get("interrupt_before")),
            interrupt_after="*" if body.get("interrupt_after") == "*" else self._as_string_list(body.get("interrupt_after")),
            checkpoint_request=checkpoint_request,
            follow_up_to_run_id=body.get("follow_up_to_run_id") if isinstance(body.get("follow_up_to_run_id"), str) else None,
            webhook=body.get("webhook") if isinstance(body.get("webhook"), str) else None,
            feedback_keys=self._as_string_list(body.get("feedback_keys")),
        )

    def _validate_constraints(self, body: JSONMapping) -> None:
        """Validate phase1 constraints, raise UnsupportedRunFeatureError if violated."""
        # Check multitask_strategy
        strategy = body.get("multitask_strategy", "reject")
        if strategy in self.UNSUPPORTED_MULTITASK_STRATEGIES:
            raise UnsupportedRunFeatureError(
                f"multitask_strategy '{strategy}' is not supported in phase1. "
                f"Supported: reject, interrupt"
            )

        # Check for rollback action
        command = self._as_json_mapping(body.get("command")) or {}
        if command.get("action") in self.UNSUPPORTED_ACTIONS:
            raise UnsupportedRunFeatureError(
                f"action '{command.get('action')}' is not supported in phase1"
            )

        # Check for after_seconds
        if body.get("after_seconds") is not None:
            raise UnsupportedRunFeatureError("after_seconds is not supported in phase1")

    def _build_scope(self, request: AdaptedRunRequest) -> RunScope:
        """Build RunScope from request."""
        if request.is_stateless:
            # Stateless: generate temporary thread
            return RunScope(
                kind="stateless",
                thread_id=str(uuid.uuid4()),
                temporary=True,
            )
        else:
            assert request.thread_id is not None
            return RunScope(
                kind="stateful",
                thread_id=request.thread_id,
                temporary=False,
            )

    def _normalize_stream_modes(self, stream_mode: JSONValue | None) -> list[str]:
        """Normalize stream_mode to list, convert messages-tuple to messages."""
        if stream_mode is None:
            return self.DEFAULT_STREAM_MODES.copy()

        if isinstance(stream_mode, str):
            modes = [stream_mode]
        elif isinstance(stream_mode, list):
            modes = [mode for mode in stream_mode if isinstance(mode, str)]
        else:
            return self.DEFAULT_STREAM_MODES.copy()

        return ["messages" if m == "messages-tuple" else m for m in modes]

    def _build_checkpoint_request(self, body: JSONMapping) -> CheckpointRequest | None:
        """Build CheckpointRequest if checkpoint data is provided."""
        checkpoint_id = body.get("checkpoint_id")
        checkpoint = self._as_json_mapping(body.get("checkpoint"))

        if not isinstance(checkpoint_id, str) and checkpoint is None:
            return None

        return CheckpointRequest(
            checkpoint_id=checkpoint_id if isinstance(checkpoint_id, str) else None,
            checkpoint=checkpoint,
        )

    def _normalize_input(self, raw_input: JSONMapping | None) -> GraphInput | None:
        """Convert HTTP-friendly message dicts into LangChain message objects."""
        if raw_input is None:
            return None

        messages = raw_input.get("messages")
        if not messages or not isinstance(messages, list):
            return raw_input

        converted: list[object] = []
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", msg.get("type", "user"))
                content = msg.get("content", "")
                if role in ("user", "human"):
                    converted.append(HumanMessage(content=content))
                else:
                    converted.append(HumanMessage(content=content))
            else:
                converted.append(msg)
        return {**raw_input, "messages": converted}

    def _build_runnable_config(
        self,
        *,
        thread_id: str,
        request_config: JSONMapping | None,
        metadata: JSONMapping | None,
        assistant_id: str | None,
        context: JSONMapping | None,
    ) -> RunnableConfigDict:
        """Build RunnableConfig from request payload and app-side rules."""
        config: RunnableConfigDict = {"recursion_limit": 100}

        if request_config:
            if "context" in request_config:
                config["context"] = request_config["context"]
            else:
                configurable = {"thread_id": thread_id}
                raw_configurable = request_config.get("configurable")
                if isinstance(raw_configurable, dict):
                    configurable.update(raw_configurable)
                config["configurable"] = configurable

            for key, value in request_config.items():
                if key not in ("configurable", "context"):
                    config[key] = value
        else:
            config["configurable"] = {"thread_id": thread_id}

        configurable = config.get("configurable")
        if (
            assistant_id
            and assistant_id != self.DEFAULT_ASSISTANT_ID
            and isinstance(configurable, dict)
            and "agent_name" not in configurable
        ):
            normalized = assistant_id.strip().lower().replace("_", "-")
            if not normalized or not re.fullmatch(r"[a-z0-9-]+", normalized):
                raise ValueError(
                    f"Invalid assistant_id {assistant_id!r}: must contain only letters, digits, and hyphens after normalization."
                )
            configurable["agent_name"] = normalized

        if metadata:
            existing_metadata = config.get("metadata")
            if isinstance(existing_metadata, dict):
                existing_metadata.update(metadata)
            else:
                config["metadata"] = dict(metadata)

        if context and isinstance(configurable, dict):
            for key in self.CONTEXT_CONFIGURABLE_KEYS:
                if key in context:
                    configurable.setdefault(key, context[key])

        return config
