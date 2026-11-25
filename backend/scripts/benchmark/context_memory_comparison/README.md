# Offline memory and project context comparison

This synthetic benchmark for [#7884](https://github.com/bytedance/deer-flow/issues/7884)
starts a disposable Gateway in process with SQLite. It creates projects, shelf
documents, threads and memory through the real API. A fixed model records the
messages passed to it, and DeerMem receives scripted extraction responses.

Run this command from the backend directory of a Git checkout.

```sh
uv run python -m scripts.benchmark.context_memory_comparison run-offline --output-dir /tmp/context-memory
```

The command runs the committed fixtures and writes one `report.json` with
the source revision, benchmark and fixture hashes, and the observations below.

- Two projects and an unassigned thread must see only their own context and
  the default memory bucket. A custom agent must see its own memory bucket.
  The project-only check requires a successful update with exactly one fact
  rejected for scope (`scope_rejections` in the report). The fact must also be
  absent from default memory and from the other thread's prompt.
- Replacement and deletion are observed in the store, in the original thread's
  next turn, and in a fresh thread. A first-turn canary verifies checkpoint reuse.
  The fresh thread is a control. If the original thread keeps a memory block
  from its checkpoint, the report records
  the stale fact and marks that check failed.
- Each recorded turn includes character-based token estimates for the
  `<memory>`, `<project>` and `<documents>` blocks in its actual model request.
  The default and custom-agent observations identify the memory bucket being
  measured. These are estimates for the injected blocks.

The exit code is 0 when all behavioral checks pass and 1 when any fail.
The benchmark uses synthetic data and fixed model responses. Gateway state is
temporary, and the report contains canary IDs and counts rather than full prompts.
