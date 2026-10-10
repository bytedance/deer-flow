# Smol Machines provider

This provider loads the optional `smolmachines` SDK only when selected. A local
VM needs KVM (Linux) or Hypervisor.framework (macOS); a cloud VM uses explicit
Smol credentials or the authenticated CLI session. Each user/thread gets one
scoped sandbox ID and can reclaim its warm VM on the next turn. Release parks
the VM; idle reaping and shutdown delete it.

Commands use fresh shells, a bounded execution timeout, and structured
per-call environment. File transport targets the same image overlay as guest
exec. The only supported `sandbox.network.mode` is `open`; reject other modes
rather than silently discard their outbound policy.

Offline unit tests must import this provider without installing the optional
SDK. `backend/tests/test_smol_sandbox_live.py` opts into local/cloud VM tests
and always deletes its machines.
