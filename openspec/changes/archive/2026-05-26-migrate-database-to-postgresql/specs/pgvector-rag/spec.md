## ADDED Requirements

### Requirement: pgvector storage backend
The system SHALL use pgvector as the vector storage backend for RAG embeddings when `rag.vector_store_backend` is set to `pgvector`.

#### Scenario: pgvector initialization
- **WHEN** system starts with `rag.vector_store_backend=pgvector`
- **THEN** system creates `rag_chunks` table with vector column
- **AND** system creates HNSW or IVFFlat index on embedding column
- **AND** system verifies `vector` extension is available

#### Scenario: Vector embedding storage
- **WHEN** document is indexed for RAG
- **THEN** system stores chunk content in `rag_chunks` table
- **AND** system stores embedding vector in `embedding` column
- **AND** system stores metadata in JSONB column

### Requirement: Vector similarity search
The system SHALL perform vector similarity search using pgvector distance operators.

#### Scenario: Cosine similarity search
- **WHEN** user performs RAG query
- **THEN** system computes query embedding
- **AND** system performs cosine similarity search using `<=>` operator
- **AND** system returns top-K most similar chunks

#### Scenario: Search with metadata filters
- **WHEN** user performs RAG query with filters
- **THEN** system applies JSONB filters on metadata column
- **AND** system performs vector search on filtered results
- **AND** system returns matching chunks

### Requirement: Tenant and collection isolation
The system SHALL isolate vector embeddings by tenant_id and collection name.

#### Scenario: Tenant isolation
- **WHEN** tenant A queries knowledge base
- **THEN** system only searches chunks where `tenant_id = A`
- **AND** system does not return chunks from other tenants

#### Scenario: Collection isolation
- **WHEN** user queries specific collection
- **THEN** system only searches chunks where `collection = <name>`
- **AND** system does not return chunks from other collections

### Requirement: Index optimization
The system SHALL create appropriate indexes for efficient vector search and metadata filtering.

#### Scenario: Vector index creation
- **WHEN** `rag_chunks` table is created
- **THEN** system creates HNSW or IVFFlat index on `embedding` column
- **AND** system creates B-tree index on `(tenant_id, collection)`
- **AND** system creates GIN index on `metadata` JSONB column

#### Scenario: Index performance validation
- **WHEN** vector search is performed
- **THEN** query execution plan uses vector index
- **AND** query completes within acceptable latency threshold
