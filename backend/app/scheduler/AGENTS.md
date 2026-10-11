# Scheduled notification delivery

- Scheduled notification delivery shutdown owns its poller join under the lifecycle lock. Shield that join from repeated caller cancellation, cancel the poller at most once while it cleans up (including timeout cancellation), and retain the generation until cleanup settles. Preserve the first caller cancellation, chaining cleanup errors; the timeout bounds graceful waiting, not arbitrary custom cleanup.
