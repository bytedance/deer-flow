# JSONL history query memory

The single-process JSONL run-event backend previously decoded and sorted every
record before applying a page limit, event filter, count or identity lookup.
Large trace payloads therefore increased the transient memory of even a five-row
chat-history request.

Queries now consume physical JSONL records off the event loop. Positive-limit
pages retain a bounded heap of candidate records; count and identity queries
retain scalar results. Selection preserves ascending sequence order and stable
file/line encounter order for ties, including legacy files whose physical order
is not sequence order. Both exclusive cursor bounds and all filters apply before
selection. Latest-AI attribution scans every file under its existing snapshot
lock and drains the scan before propagating cancellation.

This changes retained allocations, not the storage format or deployment model:

- JSONL remains a single-process backend. Use database events for multiple workers.
- Queries still scan the relevant log bytes; this does not introduce an index.
- Memory depends on returned payloads, one decoded record, target IDs, and run-file
  enumeration. One huge record or a large requested page can still be expensive.
- Non-positive limits passed directly to the store retain legacy Python slicing
  behavior and can request unbounded results. Gateway pagination uses positive limits.
- Deletion counts and `put_if_absent` checks also stream; mutation fencing,
  sequence watermarks, Unicode framing and incomplete-tail handling are unchanged.

## Reproduce

From `backend/`, using the locked Python environment:

```bash
uv run python scripts/bench_jsonl_history_memory.py \
  --events 2000 --payload-bytes 32768 --runs 4 --page-size 5
```

The script creates temporary logs and removes them on exit. It needs no network,
model credentials or existing user data. Run the same script against both
revisions, with identical arguments. It prints total log bytes, result counts,
peak Python allocations from `tracemalloc`, and elapsed time per query. Allocation
peaks are neither process RSS nor disk-cache measurements; timings are descriptive,
not latency guarantees. Other simultaneous Python work can affect measurements.

A macOS / CPython 3.12.15 run used 2,000 trace records with 32,768-byte ASCII
payloads and 20 small messages spread across four files, totaling 65,734,093 bytes.
The baseline implementation is from main `17f774b442141a3da20c377dc4da1b33f5f465f8`.

| Query | Result count | Before peak Python bytes | After peak Python bytes |
| --- | ---: | ---: | ---: |
| Latest thread messages | 5 | 66,909,587 | 158,529 |
| Forward thread messages | 5 | 66,898,613 | 152,524 |
| Latest run messages | 5 | 16,766,691 | 144,643 |
| Run events | 5 | 16,766,667 | 310,887 |
| Filtered run events | 5 | 16,766,651 | 144,923 |
| Message count | 20 | 66,898,333 | 147,550 |
| Earliest identity sequences | 1 | 66,898,864 | 148,057 |
| Latest valid AI run attribution | 1 | 66,901,014 | 149,287 |
| Last visible AI sequence per run | 4 | 16,783,048 | 143,699 |

The exact byte figures vary by interpreter and run. The regression suite uses a
more generous space bound: thirteen real-file query/mutation cases each operate on
more than 16 MiB of logs with a small result and must remain below 2 MiB of traced
peak allocation. Ordering, filtering, cursor windows, identity selection and
mid-iteration snapshot cancellation have separate behavioral assertions.

```bash
uv run pytest tests/test_jsonl_event_store_bounded_reads.py \
  tests/test_jsonl_event_store_cancellation.py \
  tests/test_jsonl_event_store_unicode.py \
  tests/test_jsonl_event_store_seq_watermark.py -q
```
