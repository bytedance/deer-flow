"""Per-run policy registration for the Feishu channel."""

from __future__ import annotations

from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy


def register_policy() -> None:
    """Register Feishu's queue-same-thread behavior in the shared policy map."""
    CHANNEL_RUN_POLICY["feishu"] = ChannelRunPolicy(
        serialize_thread_runs=True,
    )


register_policy()
