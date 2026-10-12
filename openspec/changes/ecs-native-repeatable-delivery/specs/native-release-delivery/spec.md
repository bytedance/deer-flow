## ADDED Requirements

### Requirement: Immutable release identity
The operator release entry SHALL require a clean full Git commit and SHALL bind source archive digest, backend image ID, image archive digest and both schema revisions in an immutable release lock.

#### Scenario: Different source checkout
- **WHEN** the selected commit differs from the checkout or the checkout is dirty
- **THEN** the build SHALL refuse before starting the builder

### Requirement: Same-schema guarded rollout
The release entry SHALL require drained admission, zero unsettled reservations, zero active native Runs and confirmed owned physical cleanup before activation. It SHALL fence controller admission before stopping the worker, update controller applications and reload the retained proxy before starting the worker, and SHALL preserve PostgreSQL, Redis, frontend and proxy container identity.

#### Scenario: Worker physical stop is unconfirmed
- **WHEN** the worker stop phase fails
- **THEN** the entry SHALL retain completed phase evidence and SHALL NOT activate the new controller or worker generation

### Requirement: Receipt and recovery ownership
Each phase receipt SHALL bind the release image/archive and private environment digest. The entry SHALL preserve partial failure evidence and SHALL NOT automatically resume admission or replay an interrupted deployment.

#### Scenario: Target environment changes after transfer
- **WHEN** deployment receives a transfer receipt for a different private environment digest
- **THEN** it SHALL refuse before remote deployment mutations

### Requirement: Explicit validation boundaries
Delivery documentation SHALL distinguish prepared implementation and static verification from actual Jenkins/ECS acceptance.

#### Scenario: ECS machines are powered off
- **WHEN** only static checks have completed
- **THEN** the change SHALL keep actual release validation pending and SHALL NOT claim cloud deployment success
