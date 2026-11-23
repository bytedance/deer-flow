# boxd sandbox provider (`deerflow/community/boxd_sandbox/`)

Runs sandboxes as isolated boxd machines. General sandbox rules are in the
[sandbox guide](../../sandbox/AGENTS.md); user docs are in [README.md](README.md).

```bash
cd backend && python -m pytest tests -q -k "boxd"
```

- **Address machines by id, never by name.** Names are unique per owner and
  are not free again right after a delete, so every machine generation gets a
  random suffix.
- **Every machine is created with `isolated=True`.** The agent runs untrusted
  code; an isolated machine holds no boxd credentials and joins no private
  network. A test pins it.
- **A stopped machine answers with a conflict.** Start it; repeat file calls
  once, but never a command, which may have been running when it stopped.
  Standby and hibernated machines wake on the call.
- **Every SDK call has a deadline.** Commands run under coreutils `timeout`,
  so exit code 124 and partial output come back. `machines.fs` read streams take
  no deadline, so reads run as `head -c` through exec.
- **Release copies share one deadline.** Pass it through listing and downloads.
  Budgeted calls skip stopped-machine recovery and failure probes because those
  control-plane calls have separate timeouts.
- **Failed-create cleanup stays owned.** A machine found by generation label
  goes through `_close_quietly`, so a failed delete is retried by the reaper
  and shutdown.
- **`MachineFileNotFoundError` is also a `NotFoundError`.** Test for the
  filesystem error, and confirm with `machines.get` before treating a machine
  as gone.
- **Claims decide when a cancelled acquire releases.** Each caller that
  receives a sandbox holds a claim; a cancelled caller gives its claim back
  under the scope serializer, and the last one releases the sandbox.
  Sandbox IDs include the machine generation so stale releases cannot consume
  a replacement's claims. Serialize lifecycle work and find warm machines by
  the stable scope token.
