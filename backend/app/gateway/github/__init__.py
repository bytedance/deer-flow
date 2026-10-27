"""GitHub webhook dispatcher subpackage.

Splits the inbound-webhook → custom-agent → write-back pipeline into small,
single-purpose modules so each piece can be tested in isolation:

* :mod:`identity` — bot-loop prevention and deterministic thread ids.
* :mod:`triggers` — pure logic deciding whether an event fires an agent.
* :mod:`prompts` — payload → user prompt strings.
* :mod:`registry` — scan custom agents and index them by (repo, event).
* :mod:`app_auth` — GitHub App JWT and installation-token minting.
* :mod:`writeback` — POST comments back to GitHub.
* :mod:`run_policy` — ChannelRunPolicy entry registered into ChannelManager.
* :mod:`dispatcher` — orchestrates all of the above and creates a langgraph run.

The router in :mod:`app.gateway.routers.github_webhooks` is the only consumer
of this package.
"""

# Side-effect import: registers the GitHub channel's ChannelRunPolicy
# (non-interactive flag, recursion_limit bump, installation-token
# provider) so the manager finds it on first delivery — and tests that
# build a ChannelManager directly inherit the registration as soon as
# anything inside this subpackage is imported.
from app.gateway.github import run_policy  # noqa: F401
