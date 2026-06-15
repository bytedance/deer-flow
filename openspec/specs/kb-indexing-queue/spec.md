## Purpose

PostgreSQL-based indexing task queue for multi-worker deployments. Replaces in-process `asyncio.create_task` with a database-backed competing-consumer pattern using `SELECT ... FOR UPDATE SKIP LOCKED` for safe task distribution across workers.

## Requirements

### Requirement: PostgreSQL-based indexing task queue

The `IndexingDispatcher` SHALL support a PostgreSQL-based task queue mode where indexing jobs are stored in the `index_jobs` table and workers compete for tasks using `SELECT ... FOR UPDATE SKIP LOCKED`.

#### Scenario: Worker claims an indexing job

- **WHEN** an `IndexingDispatcher` worker polls for jobs
- **AND** the `index_jobs` table has a row with `status='pending'`
- **THEN** the worker SHALL execute `SELECT ... FROM index_jobs WHERE status='pending' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED`
- **AND** SHALL set the row's `status` to `'running'` and `worker_id` to its own identifier
- **AND** SHALL record `started_at=now()` (column already exists in model)
- **AND** SHALL process the job

#### Scenario: Two workers compete for the same job

- **WHEN** Worker A and Worker B both poll for pending jobs simultaneously
- **AND** there is exactly one pending job
- **THEN** exactly one worker SHALL claim the job
- **AND** the other worker SHALL get no rows from the SELECT and return to polling

#### Scenario: Worker crash releases the job

- **WHEN** a worker crashes while processing a job with `status='running'`
- **THEN** after a configurable timeout (default: 5 minutes), another worker SHALL be able to reclaim the job
- **AND** SHALL reset `status` to `'pending'` before processing
- **AND** SHALL increment `retry_count`

### Requirement: Dispatcher mode selection

The `IndexingDispatcher` SHALL support two modes selected by configuration:
- `local` (single-worker default): in-process `asyncio.create_task` workers (existing behavior)
- `queue` (multi-worker mode default): PostgreSQL-based competing consumer pattern

#### Scenario: Queue mode enabled via multi-worker mode

- **WHEN** `deployment.mode: multi_worker` is active
- **AND** `indexing.dispatcher_mode` is not explicitly set
- **THEN** the dispatcher SHALL automatically use `queue` mode
- **AND** SHALL use PostgreSQL `FOR UPDATE SKIP LOCKED` for task claiming

#### Scenario: Explicit config overrides mode default

- **WHEN** `deployment.mode: multi_worker` is active
- **AND** `indexing.dispatcher_mode: local` is explicitly set
- **THEN** the dispatcher SHALL use `local` mode (existing behavior)

#### Scenario: Local mode preserves existing behavior

- **WHEN** `deployment.mode: single_worker` (default)
- **THEN** the dispatcher SHALL use `asyncio.create_task` workers (existing behavior)

### Requirement: Worker identification

Each dispatcher worker SHALL have a unique `worker_id` (UUID hex, 12 chars) that is recorded in `index_jobs.worker_id` when claiming a job. The `worker_id` SHALL be generated at dispatcher startup (e.g. `uuid.uuid4().hex[:12]`) and lives for the process lifetime. No persistence across restarts is required.

#### Scenario: Worker ID recorded in job

- **WHEN** a worker claims and processes a job
- **THEN** the `index_jobs` row SHALL have `worker_id` set to the worker's UUID
- **AND** the `started_at` timestamp SHALL be recorded

### Requirement: Job timeout and retry

Jobs that remain in `status='running'` for longer than `indexing.job_timeout_seconds` (default: 300) SHALL be considered stale and eligible for reclamation by other workers. Maximum retries SHALL be configurable via `indexing.max_retries` (default: 3).

#### Scenario: Stale job reclaimed

- **WHEN** a job has `status='running'` and `started_at` is more than `job_timeout_seconds` ago
- **THEN** another worker SHALL be able to reclaim it by resetting `status` to `'pending'` and incrementing `retry_count`

#### Scenario: Max retries exceeded

- **WHEN** a job's `retry_count` reaches `max_retries`
- **THEN** the job SHALL be marked `status='failed'`
- **AND** SHALL NOT be reclaimed by any worker

### Requirement: Schema migration for index_jobs table

The `index_jobs` table SHALL have `worker_id` (VARCHAR) and `retry_count` (INT, default 0) columns added. Note: `started_at` already exists in the model.

#### Scenario: Migration adds new columns

- **WHEN** the Alembic migration for multi-worker support is applied
- **THEN** the `index_jobs` table SHALL gain a `worker_id` column (VARCHAR, nullable)
- **AND** SHALL gain a `retry_count` column (INT, default 0, not null)
