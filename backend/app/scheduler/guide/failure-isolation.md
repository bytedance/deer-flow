# Scheduler failure isolation

Scheduled work shares one polling cycle. Treat an individual occurrence as the
failure boundary so one damaged record cannot repeatedly prevent unrelated
owners' work from progressing. Apply this convention to maintenance passes as
well as launches: failing to clean up an older occurrence is not a reason to
withhold admission from a healthy task.

An exception during dispatch does not establish whether Gateway accepted the
run. Leave that uncertainty to durable queue and lease recovery. Eagerly
clearing a lease or starting a replacement from the exception handler can
duplicate work that already started. Cleanup is appropriate only when the
operation's outcome and ownership are known.

Containment preserves progress, not success. Keep failures observable and let
normal recovery retry the affected occurrence. Apply queue age before building
the fair drain batch: expired rows must not consume owner ranks or batch slots,
or a failed timeout sweep can starve healthy work indefinitely. Queue timeout is
enforced again when a waiting row is claimed for launch. If timeout cleanup
fails, the row remains queued for the next recovery pass but is no longer
eligible to start; cleanup failure must never turn expired work into a live run.
Failure to read the queue or claim due work still prevents that stage from
progressing; the next poll retries it.

For user-visible behavior and deployment requirements, see the
[scheduled tasks guide](../../../../docs/guide/scheduled-tasks.md).
