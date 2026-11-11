# GroundRoute (`deerflow/community/groundroute/`)

Shared provider rules are in the [community guide](../AGENTS.md).

- **Both tools are coroutines and use `httpx.AsyncClient`.** A sync client runs
  the whole tool on the default executor and holds one of its threads for the
  network round trip, so providers queried in parallel queue behind each other.
- **The config file read stays off the event loop.** The tool body runs on the
  loop, so a file read in it blocks the loop.
- **A thread assertion alone does not prove the async client.** A mock transport
  runs its handler on the calling thread, so a provider that fell back to a sync
  client would pass. The blocking-I/O test also records which client factory the
  provider used.
- **One config read per call resolves the key and `max_results`.** Do not add a
  second wrapper around that read. A wrapper without a production caller drifts
  from the real call path.
- **`web_search` returns a structured error object and `web_fetch` returns an
  `Error: ...` string.** A result whose leaf fields are not strings still returns
  text.
