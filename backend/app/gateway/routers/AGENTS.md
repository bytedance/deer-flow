# Gateway routers (`app/gateway/routers/`)

One module per API area. The parent [Gateway guide](../AGENTS.md) covers trust
boundaries and run admission; this file covers what every route handler has to do.

## Verify

```bash
cd backend
python -m pytest tests -q -k "<area>_router"     # e.g. threads_router, console_router
make test-blocking-io                            # after adding any file, config or network read
```

## Rules for a route handler

- **Authorize first.** Check the session, role or permission before the handler
  reads credentials, parses an upload or makes an outbound request. An
  unauthorized caller must not be able to trigger that work.
- **Fixed text in 5xx responses.** Exceptions from storage, config loading and
  subprocesses contain host paths. Log the exception on the server and return a
  fixed detail string.
- **No blocking calls on the event loop.** `get_app_config()` stats and hashes the
  config files on every call, and storage backends do file I/O. Call both through
  `asyncio.to_thread`. The blocking-I/O suite fails the build otherwise.
- **Writes survive disconnects.** Wrap a persistent write in
  `app.gateway.persistent_writes.run_drained_write`. A cancelled request then
  still waits for the worker that owns the write, and no half-written state stays
  behind.
- **Catalog responses are projections.** A listing endpoint returns names and
  display fields. Provider paths, credentials and raw tool or server configuration
  stay on the server.
- **Provenance comes from the session.** Values that say who or what triggered an
  action (for example the plugin `ActionContext.interaction`) are set from the
  authenticated request only. Ignore the same field in a request body.
- **Unreadable configuration is not default configuration.** When a policy cannot
  be read, skip the optional work (cleanup, sweep) and keep serving. Applying a
  default policy can delete data the operator wanted to keep.
- **Imports create, they do not overwrite.** Agent and skill imports are scoped to
  the caller and return 409 on a name collision. Exports leave out credentials,
  memory, conversations and installation bindings.
- **Memory backup imports** replace the selected facts and require an explicit
  `facts` array. Omitting it returns 422. An empty array clears that bucket.
- **Outbound requests from a route** (model discovery, connection tests) have a
  time limit and a size limit, do not follow redirects, and return redacted
  provider errors.
- **Locks that several Gateway processes share** are file locks beside the data,
  taken off the event loop. A process mutex alone does not order writes between
  workers.
- **Path segments from clients.** A name that becomes a directory (agent name,
  skill name, file name) is validated when it is created, including Windows
  reserved device names. Read and delete routes stay permissive so that data
  stored by an older release can still be exported and removed.
