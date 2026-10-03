# Agent teams extension

Keep team business logic in this independently installable package. Runtime code
imports public `deerflow_extension_api` contracts and its declared LangChain
dependency; do not import host `app.*` or `deerflow.*` internals. Browser code is a
manifest-listed native module with no host React dependency.

Every storage operation is owner-scoped. Native mentions use Gateway's stamped
runtime identity and delegated capability, never an owner from mention content.
Thread sharing is not team sharing. Keep peer content on human-message channels.

Persist run input and idempotency keys before admission. Serialize by thread and
record a terminal result and its follow-up receipt in one SQLite transaction.
Unknown admission outcomes must retain ownership of the pending job. Never
automatically approve interruptions, infer success from a terminal run alone, or
serialize a host capability. Only an authenticated action or native mention
rebinds after restart.

Run the backend plugin tests and the browser check documented in README.md after
changes. The preview fixture has synthetic authentication and must remain
loopback-only; never use it as a deployed Gateway.
