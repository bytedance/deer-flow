"""Recording gateway for *record-through-browser* (Plan A).

Runs the gateway with a REAL model and a callback that appends every model
call's ``(input_hash, output)`` to a JSONL file. Because the run is driven by
the real frontend (Playwright), the captured inputs are EXACTLY what the
frontend produces (date system-reminder, suggestions/title calls, ...), so the
resulting fixture replays cleanly against the browser.

Used by ``frontend/playwright.record.config.ts``. Env:
  OPENAI_API_KEY / OPENAI_API_BASE  - the real upstream (never committed)
  DEERFLOW_RECORD_OUT               - JSONL path to append captured turns to
  RECORD_PORT (default 8012), RECORD_MODEL (default gpt-5.5)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "tests"))


def _install_capture(out_path: Path) -> None:
    from langchain_core.callbacks import BaseCallbackHandler
    from langchain_core.messages import messages_to_dict
    from replay_provider import caller_identity, hash_messages, hash_replay_input

    import deerflow.models.factory as factory_mod

    class Capture(BaseCallbackHandler):
        def __init__(self) -> None:
            self.inputs: dict[str, tuple[list, str]] = {}

        def on_chat_model_start(  # noqa: ANN001
            self,
            serialized,
            messages,
            *,
            run_id=None,
            tags=None,
            name=None,
            **kwargs,
        ):
            self.inputs[str(run_id)] = (
                messages[0] if messages else [],
                caller_identity(name=name, tags=tags),
            )

        def on_llm_end(self, response, *, run_id=None, **kwargs):  # noqa: ANN001
            captured = self.inputs.pop(str(run_id), None)
            if captured is None:
                return
            inp, caller = captured
            for batch in response.generations:
                for gen in batch:
                    message = getattr(gen, "message", None)
                    if message is None:
                        continue
                    record = {
                        "caller": caller,
                        "conversation_hash": hash_messages(inp),
                        "input_hash": hash_replay_input(inp, caller=caller),
                        "output": messages_to_dict([message])[0],
                    }
                    with open(out_path, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        handle.flush()

    cb = Capture()
    original = factory_mod.create_chat_model

    def wrapped(*args, **kwargs):
        model = original(*args, **kwargs)
        model.callbacks = (model.callbacks or []) + [cb]
        return model

    factory_mod.create_chat_model = wrapped
    for module in list(sys.modules.values()):
        if getattr(module, "create_chat_model", None) is original:
            module.create_chat_model = wrapped


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("OPENAI_API_BASE"):
        print("ERROR: set OPENAI_API_KEY and OPENAI_API_BASE (an OpenAI-compatible /v1 endpoint)", file=sys.stderr)
        return 2

    record_out = os.environ.get("DEERFLOW_RECORD_OUT")
    if not record_out:
        print("ERROR: set DEERFLOW_RECORD_OUT to the JSONL path to append captured turns to", file=sys.stderr)
        return 2

    port = int(os.environ.get("RECORD_PORT", "8012"))
    model = os.environ.get("RECORD_MODEL", "gpt-5.5")
    out = Path(record_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("", encoding="utf-8")  # fresh capture per recording run

    from _replay_fixture import build_config_yaml, prepare_hermetic_extras, real_model_block

    home = Path(tempfile.mkdtemp(prefix="record-gw-"))
    cfg = home / "config.yaml"
    cfg.write_text(build_config_yaml(model_block=real_model_block(model), home=home), encoding="utf-8")
    # Override (not setdefault): the recorder must be hermetic, so an outer
    # DEER_FLOW_HOME can't leak in and shift prompt-affecting paths/skills.
    os.environ["DEER_FLOW_HOME"] = str(home)
    os.environ["DEER_FLOW_CONFIG_PATH"] = str(cfg)
    os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(prepare_hermetic_extras(home))
    os.environ.setdefault("AUTH_JWT_SECRET", "record-secret")
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in (str(_BACKEND), str(_BACKEND / "tests"), os.environ.get("PYTHONPATH", "")) if p)

    _install_capture(out)

    import uvicorn

    print(f"[record-gw] model={model} out={out} port={port}", flush=True)
    uvicorn.run("app.gateway.app:app", host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
