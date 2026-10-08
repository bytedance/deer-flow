# Router contracts

Custom Agent packages are strict, versioned definition-only JSON documents.
Export explicitly projects the caller's portable `AgentConfig` fields and SOUL;
exclude `github` installation bindings, memory contents, conversations and
credentials. Import may rename locally but must remain owner-scoped and
create-only: collisions return 409, never overwrite or upsert. Ordinary creation
and import share `_persist_new_agent`, which uses `run_drained_write` so a
cancelled request still drains the owned persistence worker.

### Saved native batch reports

`subagent_batches.get_batch_item_result` reuses `threads:read` owner admission
and `_owned_batch`. It reads one immutable submission position (0–99999), checks
the returned position and projects through `deerflow.subagents.batch_results`
off the event loop. Repository availability is sufficient: worker shutdown does
not remove historical read access. JSONL export and compact item paging stay
independent; never expose raw result artifacts, prompts, leases or execution specs
through this selected-report response. Real SQLite HTTP admission and denied
owner/permission regressions live in `tests/test_batch_results_http.py`.
