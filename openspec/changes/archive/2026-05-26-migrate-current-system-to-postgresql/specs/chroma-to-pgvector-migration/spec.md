## ADDED Requirements

### Requirement: Reindex Chroma vectors to pgvector with KB-bound embedding

The system SHALL provide a reindexing script (`scripts/reindex_rag_to_pgvector.py`) that migrates vector embeddings from Chroma to pgvector. The script SHALL respect the KB-bound embedding architecture introduced in Sprint B:

- Each `KnowledgeBase` has its own `embedding_model` and `embedding_dim`
- The script SHALL use the KB's configured embedding model to regenerate embeddings
- The script SHALL validate that the generated embedding dimension matches the KB's `embedding_dim`

The script SHALL support resuming from the last successfully processed knowledge base if interrupted.

#### Scenario: Successful reindexing of all knowledge bases

- **WHEN** the reindexing script is executed with valid Chroma and PostgreSQL connection parameters
- **AND** the system contains 3 knowledge bases with different embedding models
- **THEN** the script SHALL iterate through each knowledge base
- **AND** for each KB, the script SHALL:
  - Retrieve all documents from Chroma
  - Re-chunk the documents using the current chunking strategy
  - Generate embeddings using the KB's configured `embedding_model`
  - Validate that embedding dimension matches the KB's `embedding_dim`
  - Insert chunks and embeddings into the `rag_chunks` table in PostgreSQL
- **AND** the script SHALL exit with status code 0
- **AND** the script SHALL output a reindexing report

#### Scenario: Resume after interruption

- **WHEN** the reindexing script is interrupted after processing 2 out of 5 knowledge bases
- **AND** the script is re-executed with the `--resume` flag
- **THEN** the script SHALL skip the 2 already-processed knowledge bases
- **AND** the script SHALL continue with the 3rd knowledge base
- **AND** the script SHALL complete the remaining 3 knowledge bases

#### Scenario: Single KB failure does not block others

- **WHEN** the reindexing script encounters an error while processing KB #3 (e.g., embedding API rate limit)
- **THEN** the script SHALL log the error and mark KB #3 as failed
- **AND** the script SHALL continue processing KB #4 and KB #5
- **AND** the script SHALL exit with status code 1 (partial failure)
- **AND** the reindexing report SHALL list KB #3 as failed with the error message

### Requirement: Validate embedding dimension consistency

The reindexing script SHALL validate that the generated embedding dimension matches the KB's configured `embedding_dim` before inserting into pgvector. A dimension mismatch SHALL cause the KB to be marked as failed.

#### Scenario: Dimension mismatch causes KB failure

- **WHEN** KB #1 has `embedding_dim=1536` configured
- **AND** the embedding model generates vectors with dimension 768
- **THEN** the script SHALL NOT insert the vectors into pgvector
- **AND** the script SHALL mark KB #1 as failed with error "Embedding dimension mismatch: expected 1536, got 768"
- **AND** the script SHALL continue with the next KB

#### Scenario: Dimension match allows insertion

- **WHEN** KB #2 has `embedding_dim=768` configured
- **AND** the embedding model generates vectors with dimension 768
- **THEN** the script SHALL insert the vectors into pgvector
- **AND** the script SHALL mark KB #2 as successful

### Requirement: Support batch processing and rate limiting

The reindexing script SHALL support batch processing to control embedding API usage and avoid rate limits. The batch size and rate limit SHALL be configurable via command-line arguments.

#### Scenario: Batch processing with rate limiting

- **WHEN** the reindexing script is executed with `--batch-size 100 --rate-limit 10`
- **THEN** the script SHALL process documents in batches of 100 chunks
- **AND** the script SHALL wait 1 second between batches (10 batches per minute)
- **AND** the script SHALL log progress for each batch (e.g., "Processed batch 5/50: 100 chunks")

#### Scenario: Default batch size and rate limit

- **WHEN** the reindexing script is executed without specifying batch size or rate limit
- **THEN** the script SHALL use the default batch size of 50 chunks
- **AND** the script SHALL use the default rate limit of 20 batches per minute (3 seconds between batches)

### Requirement: Provide reindexing report

The reindexing script SHALL output a detailed report at the end of reindexing, including:
- Total number of knowledge bases processed
- Number of knowledge bases successful, failed, and skipped (resumed)
- Number of chunks and embeddings inserted per KB
- Validation results (chunk count, dimension consistency)
- Total reindexing duration
- Estimated embedding API cost (if applicable)

#### Scenario: Reindexing report includes all details

- **WHEN** the reindexing completes (successfully or with partial failures)
- **THEN** the script SHALL output a report in the following format:
  ```
  Reindexing Report
  =================
  Knowledge bases: 5 total, 3 successful, 1 failed, 1 skipped (resumed)
  Duration: 6 hours 23 minutes
  
  KB Breakdown:
  - KB #1 (daily-reports): 1200 chunks, 1200 embeddings, SUCCESS
  - KB #2 (fault-diagnosis): 800 chunks, 800 embeddings, SUCCESS
  - KB #3 (corrosion-data): FAILED (Embedding dimension mismatch: expected 1536, got 768)
  - KB #4 (maintenance-logs): 500 chunks, 500 embeddings, SUCCESS
  - KB #5 (safety-manuals): SKIPPED (already processed in previous run)
  
  Total chunks inserted: 2500
  Total embeddings inserted: 2500
  Estimated embedding cost: $2.50 (based on 1.25M tokens at $2/1M tokens)
  ```

### Requirement: Support dry-run mode

The reindexing script SHALL support a dry-run mode that estimates the reindexing cost and duration without actually generating embeddings or inserting data.

#### Scenario: Dry-run mode estimates cost

- **WHEN** the reindexing script is executed with the `--dry-run` flag
- **THEN** the script SHALL:
  - Count the total number of documents and chunks across all KBs
  - Estimate the total number of tokens to be embedded
  - Calculate the estimated embedding API cost (based on model pricing)
  - Output the estimate without generating embeddings or inserting data
- **AND** the script SHALL exit with status code 0
