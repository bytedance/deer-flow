Source id: KB-RUNBOOK-ATLAS-FAILOVER
Status: current
Title: Atlas failover runbook

Before declaring readiness, the mitigation guard is to freeze the
`atlas_writer` feature flag and confirm the read replica lag is below 90 seconds.

Use this runbook together with the current incident record when reporting the
readiness decision.
