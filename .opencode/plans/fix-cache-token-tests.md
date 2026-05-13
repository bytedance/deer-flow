# Fix: Update tests for cache token fields in end event usage

## Problem
PR #2925 added `cache_read_tokens` and `cache_creation_tokens` to the client's cumulative usage. In `client.py:799`, the end event now always includes these cache fields. Two tests expect the old 3-field structure and fail.

## Failing Tests
1. `tests/test_client.py:431` — `test_messages_mode_emits_token_deltas`
2. `tests/test_client.py:714` — `test_messages_mode_golden_event_sequence`

## Fix
1. **Line 431**: Add cache fields to expected usage dict
2. **Line 675, 714**: Define separate `end_usage` variable with cache fields for the golden event sequence test, since `usage_metadata` assertions should NOT include cache fields

## Files to Change
- `tests/test_client.py`
