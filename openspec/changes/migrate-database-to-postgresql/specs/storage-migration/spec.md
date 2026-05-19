## ADDED Requirements

### Requirement: SQLite to PostgreSQL migration script
The system SHALL provide a migration script to transfer data from SQLite to PostgreSQL.

#### Scenario: Business tables migration
- **WHEN** migration script is executed
- **THEN** script migrates all records from SQLite `users` table to PostgreSQL
- **AND** script migrates all records from SQLite `tenants` table to PostgreSQL
- **AND** script migrates all records from SQLite `threads_meta` table to PostgreSQL
- **AND** script migrates all records from SQLite `runs` table to PostgreSQL
- **AND** script migrates all records from SQLite `knowledge_bases` table to PostgreSQL
- **AND** script migrates all records from SQLite `knowledge_base_documents` table to PostgreSQL

#### Scenario: Migration validation
- **WHEN** migration completes
- **THEN** script validates record counts match between SQLite and PostgreSQL
- **AND** script spot-checks sample records for data integrity
- **AND** script logs any discrepancies found

#### Scenario: Idempotent migration
- **WHEN** migration script is run multiple times
- **THEN** script skips records that already exist in PostgreSQL
- **AND** script updates records that have changed
- **AND** script does not create duplicate records

### Requirement: JSON file to PostgreSQL migration
The system SHALL provide migration scripts to transfer data from JSON files to PostgreSQL tables.

#### Scenario: Token usage migration
- **WHEN** `token_usage.json` migration script is executed
- **THEN** script reads all records from `token_usage.json`
- **AND** script inserts records into PostgreSQL `token_usage` table
- **AND** script validates record count matches

#### Scenario: Memory migration
- **WHEN** `memory.json` migration script is executed
- **THEN** script reads memory data from `memory.json` for each user
- **AND** script writes memory data to LangGraph Store namespace
- **AND** script validates memory data is retrievable from Store

### Requirement: Checkpointer migration
The system SHALL provide a migration script to transfer LangGraph checkpointer data from SQLite to PostgreSQL.

#### Scenario: Checkpointer state migration
- **WHEN** checkpointer migration script is executed
- **THEN** script reads all checkpoint records from SQLite checkpointer
- **AND** script writes checkpoint records to PostgreSQL checkpointer using LangGraph abstraction
- **AND** script validates checkpoint count matches

#### Scenario: Thread state preservation
- **WHEN** checkpointer migration completes
- **THEN** all thread states are accessible from PostgreSQL checkpointer
- **AND** thread history is preserved
- **AND** thread resumption works correctly

### Requirement: Vector storage reindexing
The system SHALL provide a reindexing script to rebuild vector embeddings in pgvector from source documents.

#### Scenario: Knowledge base reindexing
- **WHEN** reindexing script is executed
- **THEN** script iterates through all knowledge base documents
- **AND** script re-chunks document content
- **AND** script generates embeddings for each chunk
- **AND** script inserts chunks into `rag_chunks` table

#### Scenario: Reindexing validation
- **WHEN** reindexing completes
- **THEN** script validates chunk count matches expected
- **AND** script performs spot-check retrieval queries
- **AND** script compares retrieval results against Chroma baseline

#### Scenario: Batch processing with rate limiting
- **WHEN** reindexing processes large document set
- **THEN** script batches embedding requests
- **AND** script respects embedding API rate limits
- **AND** script logs progress periodically

### Requirement: Migration rollback support
The system SHALL support rollback to previous storage backend if migration fails.

#### Scenario: Rollback to SQLite
- **WHEN** PostgreSQL migration fails
- **THEN** administrator can restore SQLite database from backup
- **AND** administrator can restore JSON files from backup
- **AND** administrator can restore Chroma directory from backup
- **AND** system can restart with SQLite configuration

#### Scenario: Rollback validation
- **WHEN** rollback is performed
- **THEN** system verifies thread history is accessible
- **AND** system verifies conversations work correctly
- **AND** system verifies RAG retrieval works correctly
