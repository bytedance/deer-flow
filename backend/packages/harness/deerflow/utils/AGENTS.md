# Shared utilities (`deerflow/utils/`)

Small helpers that several subsystems share: atomic file publication, advisory
file locks, off-loop assembly, document conversion and outlines, message text
extraction, host path portability, retry hints, port allocation and the proxy
policy for internal HTTP calls. Before you write a local variant of one of these,
use the helper here; each exists because separate copies drifted apart.

## Verify

```bash
cd backend
python -m pytest tests -q -k "atomic or file_lock or host_path or conversion or outline or llm_text or retry_after or port_allocator or http_policy"
make test-blocking-io
```

## Files on disk

- **Publish bytes with `atomic_write.publish_bytes_atomically`.** A reader then
  sees the old file or the new one, never a partial write. On failure, or when you
  discard an owned temporary, call `cleanup_failed_atomic_write`.
- **Do not read the process umask by changing it.** The runtime is threaded, and
  another thread would create a file with the temporary mask.
- **Retry a file lock only on contention**, through
  `file_lock.retry_until_locked`. Other errors propagate at once. Each caller
  keeps its own deadline, and clocks and sleeps are injected, so tests do not
  patch the shared `time` module.
- **Reject Windows device names on every platform** for a path the host will
  create. A workspace written on Linux is opened on Windows later. Compare the
  stem only, and leave the supplied file name unchanged.
- **`extended_length_path()` is a spelling, not a check.** It does not replace
  symlink resolution or confinement, and it is not used for persisted relative
  paths or Docker mount sources.

## Off the event loop

- **Build models, tools and agents through `assembly_io.run_assembly`.** Assembly
  can read credential files and wait on MCP discovery. The dedicated executor
  keeps that work off the event loop and off the default thread pool, and it
  preserves the request context. A new async entry point that assembles an agent
  or a model uses it too.
- **Cancellation during construction must not start inference.**
- **Resolve the agent factory before admission**, so that an import error cannot
  admit a run.
- **Document conversion is always offloaded, and its worker is drained through
  cancellation.** A small compressed Office file can take seconds, and the caller
  deletes the source file right after it returns.

## Text and content

- **Message content can be `None`, a string or a list of blocks.** Use the shared
  extraction helpers, which ignore blocks without string text.
- **Strip only well-formed reasoning tags.** A word that merely starts with
  `think` is ordinary text.
- **Outlines and previews are read as `utf-8-sig`**, so a leading BOM does not
  become part of the first heading.
- **`text_detection` decides which MIME types are active content** for artifact
  and project-document downloads. Keep platform aliases mapped to their standard
  type, and keep the generic `+xml` rule.

## Network

- **`http_policy.control_plane_trust_env` decides whether a client inherits the
  proxy environment.** Loopback, private, container-internal and cluster-local
  hosts bypass the proxy; public hosts keep it. The module has no third-party
  imports, so the Gateway and the channels import it without loading the sandbox
  stack. Keep it that way.
- **Bound every provider retry hint with `retry_after`.** An unbounded
  `Retry-After` value would park a run.
- **`PortAllocator` never probes a port above 65535.** It reports exhaustion.
