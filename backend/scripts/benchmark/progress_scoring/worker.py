"""Replay public middleware hooks in a process isolated to one source checkout.

No tools execute, model is called, or policy implementation is copied here.
The entire fixed trace is replayed even after a stop: later decisions are
counterfactual and must not be presented as an actual continued agent run.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace


def expand_case(case: dict) -> list[dict]:
    """Expand versioned synthetic templates, with no randomness or clock reads."""
    steps = []
    for index in range(1, case["steps"] + 1):
        value = index if case["vary_args"] else 0
        result = case["result"].format(step=index)
        if index == case.get("noisy_step"):
            result += " timestamp=synthetic-noise"
        steps.append(
            {
                "name": case["tools"][(index - 1) % len(case["tools"])],
                "args": {key: text.format(step=value) for key, text in case["args"].items()},
                "result": result,
                "meta": case["meta"],
                "evaluation": case["evaluation"],
            }
        )
    return steps


@dataclass
class ModelRequestView:
    """The request fields used by production request wrappers, without a model."""

    messages: list
    runtime: object

    def override(self, **updates):
        return replace(self, **updates)


class Recorder:
    def __init__(self):
        self.step = 0
        self.events = []

    def record_middleware(self, **event):
        self.events.append({"step": self.step, "action": event["action"], "changes": event["changes"]})


def replay(policy: str, case: dict, parameters: dict, encoding=None) -> dict:
    """Call the real hooks, observing audit transitions and injected messages."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    module_name, class_name = {
        "loop_detection": ("loop_detection_middleware", "LoopDetectionMiddleware"),
        "tool_progress": ("tool_progress_middleware", "ToolProgressMiddleware"),
        "progress_scoring": ("progress_scoring_middleware", "ProgressScoringMiddleware"),
    }[policy]
    module = importlib.import_module(f"deerflow.agents.middlewares.{module_name}")
    middleware = getattr(module, class_name)(**parameters)
    recorder = Recorder()
    runtime = SimpleNamespace(context={"thread_id": case["id"], "run_id": "synthetic-run", "__run_journal": recorder})
    messages = [HumanMessage(content=case["goal"])]
    protocol_texts = []
    hint_texts = []
    score_texts = []

    def model_boundary():
        captured = []

        def handler(request):
            captured.extend(request.messages[len(messages) :])
            return SimpleNamespace(result=[])

        middleware.wrap_model_call(ModelRequestView(list(messages), runtime), handler)
        for message in captured:
            text = message.content
            if policy == "progress_scoring":
                # Separate fixed protocol from episode-dependent intervention.
                instruction = module._INSTRUCTION_TEXT
                if not text.startswith(instruction):
                    raise ValueError("Candidate injection no longer begins with its protocol")
                protocol_texts.append(instruction)
                if remainder := text[len(instruction) :].strip():
                    hint_texts.append(remainder)
            else:
                hint_texts.append(text)

    model_boundary()  # Initial call also receives the candidate protocol.
    for index, step in enumerate(expand_case(case), 1):
        recorder.step = index
        call = {"id": f"call-{index}", "name": step["name"], "args": step["args"]}
        proposal = AIMessage(content="", tool_calls=[call], id=f"proposal-{index}")
        messages.append(proposal)
        if policy == "loop_detection":
            middleware.after_model({"messages": list(messages)}, runtime)
        result = ToolMessage(
            content=step["result"],
            name=step["name"],
            tool_call_id=call["id"],
            status="error" if step["meta"]["status"] == "error" else "success",
            additional_kwargs={"deerflow_tool_meta": step["meta"]},
        )
        if policy == "tool_progress":
            middleware.wrap_tool_call(SimpleNamespace(tool_call=call, runtime=runtime), lambda request, result=result: result)
        messages.append(result)
        answer = "Continuing the synthetic trace."
        if policy == "progress_scoring" and step["evaluation"] is not None:
            block = f"```{module.PROGRESS_EVAL_TAG}\n{json.dumps(step['evaluation'], separators=(',', ':'))}\n```"
            score_texts.append(block)
            answer += "\n" + block
        messages.append(AIMessage(content=answer, id=f"answer-{index}"))
        if policy == "progress_scoring":
            update = middleware.after_model({"messages": list(messages)}, runtime)
            if update:
                messages[-1] = update["messages"][0]
        model_boundary()  # Drains hints through the real model-request wrapper.

    interventions = [event for event in recorder.events if event["action"] in {"warn", "block", "hard_stop", "replan_required"}]
    stops = [event for event in recorder.events if event["action"] in {"block", "hard_stop"}]
    return {
        "case_id": case["id"],
        "scenario": case["scenario"],
        "synthetic": True,
        "score_origin": "hand_authored",
        "stalled": case["stalled"],
        "policy": policy,
        "steps": case["steps"],
        "first_intervention_step": interventions[0]["step"] if interventions else None,
        "first_hard_stop_step": stops[0]["step"] if stops else None,
        "events": recorder.events,
        "protocol_model_calls": len(protocol_texts),
        "protocol_input_bytes": sum(len(text.encode("utf-8")) for text in protocol_texts),
        "score_output_bytes": sum(len(text.encode("utf-8")) for text in score_texts),
        "hint_input_bytes": sum(len(text.encode("utf-8")) for text in hint_texts),
        "protocol_tokens_per_call": len(encoding.encode(protocol_texts[0])) if encoding is not None and protocol_texts else (0 if not protocol_texts else None),
        "protocol_input_tokens": sum(len(encoding.encode(text)) for text in protocol_texts) if encoding is not None else None,
        "score_output_tokens": sum(len(encoding.encode(text)) for text in score_texts) if encoding is not None else None,
        "hint_input_tokens": sum(len(encoding.encode(text)) for text in hint_texts) if encoding is not None else None,
        "middleware_source_sha256": hashlib.sha256(Path(module.__file__).read_text(encoding="utf-8").encode()).hexdigest(),
    }


def local_encoding(tokenizer_file: Path, expected_hash: str):
    """Provision a verified local tiktoken cache; the benchmark never downloads."""
    payload = tokenizer_file.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_hash:
        raise ValueError("Tokenizer SHA-256 mismatch")
    import tiktoken

    url = "https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
    with tempfile.TemporaryDirectory(prefix="progress-bench-tokenizer-") as directory:
        Path(directory, hashlib.sha1(url.encode()).hexdigest()).write_bytes(payload)
        previous = os.environ.get("TIKTOKEN_CACHE_DIR")
        os.environ["TIKTOKEN_CACHE_DIR"] = directory
        try:
            return tiktoken.get_encoding("cl100k_base")
        finally:
            if previous is None:
                os.environ.pop("TIKTOKEN_CACHE_DIR", None)
            else:
                os.environ["TIKTOKEN_CACHE_DIR"] = previous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--policy", choices=["loop_detection", "tool_progress", "progress_scoring"], required=True)
    parser.add_argument("--tokenizer-file", type=Path)
    args = parser.parse_args()
    # Resolve imports before loading any DeerFlow module. Separate processes
    # prevent installed editable packages or sys.modules leaking between arms.
    for relative in ("backend", "backend/packages/harness", "backend/packages/extension-api"):
        sys.path.insert(0, str(args.root.resolve() / relative))
    data = json.load(sys.stdin)
    logging.disable(logging.CRITICAL)
    encoding = local_encoding(args.tokenizer_file, data["config"]["tokenizer_sha256"]) if args.tokenizer_file else None
    rows = [replay(args.policy, case, data["config"]["policies"][args.policy], encoding) for case in data["cases"]]
    loaded = []
    for name, module in sorted(sys.modules.items()):
        if (name == "deerflow" or name.startswith(("deerflow.", "deerflow_extension_api"))) and (file := getattr(module, "__file__", None)):
            path = Path(file).resolve()
            if not path.is_relative_to(args.root.resolve()):
                raise ValueError(f"Source isolation failed for {name}")
            loaded.append({"path": path.relative_to(args.root.resolve()).as_posix(), "sha256": hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()})
    print(json.dumps({"rows": rows, "loaded_sources": loaded}, sort_keys=True))


if __name__ == "__main__":
    main()
