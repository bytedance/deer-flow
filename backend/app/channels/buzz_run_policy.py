"""Run-policy registration for the Buzz channel (imported for side effect from manager.py)."""

from app.channels.run_policy import CHANNEL_RUN_POLICY, ChannelRunPolicy


def register_policy() -> None:
    # Same-thread follow-ups queue instead of tripping the busy reply (Feishu precedent);
    # the adapter-level pubkey allowlist is the identity gate, so no bound identity needed.
    CHANNEL_RUN_POLICY["buzz"] = ChannelRunPolicy(serialize_thread_runs=True, requires_bound_identity=False)


register_policy()
