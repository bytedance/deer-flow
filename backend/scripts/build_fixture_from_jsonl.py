"""Turn a record-through-browser JSONL capture into a replay fixture.

The recording gateway (``record_gateway.py``) appends ``{input_hash, output}``
lines as the frontend drives a real run; the record spec writes a ``.meta.json``
sidecar with ``{scenario, mode, prompt}``. This stitches them into the fixture
the replay provider + tests consume.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jsonl", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="gpt-5.5")
    args = parser.parse_args()

    turns = [json.loads(line) for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines() if line.strip()]
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    fixture = {
        "scenario": meta["scenario"],
        "mode": meta["mode"],
        "model": args.model,
        "prompt": meta["prompt"],
        "context": meta.get("context", {}),
        "turns": turns,
    }
    Path(args.out).write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(turns)} turn(s) -> {args.out}")
    for index, turn in enumerate(turns):
        data = turn["output"].get("data", {})
        tool_calls = [tc.get("name") for tc in (data.get("tool_calls") or [])]
        caller = turn.get("caller", "legacy")
        print(f"  turn {index}: caller={caller} hash={turn['input_hash'][:12]} tool_calls={tool_calls} content={str(data.get('content'))[:50]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
