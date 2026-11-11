# Ordinary Task Progress and Result Delivery

Ordinary `task` calls notify the parent when a child publishes new steps, a
running-state change, or a terminal outcome. The parent reads a consistent
snapshot and forwards unread steps in order. It does not wait for a five-second
polling interval. Usage and evidence updates remain available in snapshots but
do not independently notify the parent.

## Waiting Deadline

The main wait has one monotonic deadline, fixed immediately after successful
dispatch. Its budget is `5 * (((timeout_seconds + 60) // 5) + 1)` seconds: for
example, a configured timeout of 1800 seconds gives a main waiting budget of
1865 seconds. This budget includes event handling in the main consumer loop.
Progress does not reset the deadline.

At expiry, the consumer checks the registry and result again. An already
published terminal outcome takes priority. Otherwise, the task retains the
compatible `polling_timed_out` status, requests cancellation, and schedules
deferred cleanup. The deadline does not impose a new timeout on event handlers
or later acceptance checks.

## Result Delivery and Cleanup

Result delivery does not wait for execution cleanup. A hard timeout can return
while stream or sandbox cleanup continues to own capacity and resources. Normal
registry removal still waits for the cleanup fence. Cancellation waits and
deferred cleanup retain their existing polling behavior.

Registry removal does not publish a notification. If an external caller forcibly
removes an entry and no later update is published, the consumer may discover the
missing entry only when the deadline expires.

## Final Usage

Cancelled and timed-out tasks use the existing usage-tail supervisor to report
final cumulative usage on the parent event loop. The usage journal deduplicates
reports by source run ID, so the final report does not count earlier progress
snapshots twice.

Complete accounting requires the parent loop to accept the report and cleanup
to finish within the existing supervision budget. Parent-loop closure or budget
exhaustion retains the existing diagnostics and cleanup behavior; there is no
persistent redelivery mechanism.

For the other execution limits, see the
[English limits reference](../../frontend/src/content/en/harness/subagents/limits.mdx)
or the [Chinese limits reference](../../frontend/src/content/zh/harness/subagents/limits.mdx).
