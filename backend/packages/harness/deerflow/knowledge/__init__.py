"""RAG knowledge-base subsystem.

Offline indexing (parse → caption → chunk → embed) and the shared storage layer
(business tables + Qdrant vector store). Online retrieval ships as a builtin
agent tool under ``deerflow.tools.builtins`` (Task 7).

Layout:
- ``models.py`` — SQLAlchemy rows for the knowledge tables.
- ``store.py`` — CRUD over the business tables (``KnowledgeStore``).
- ``vector_store.py`` — Qdrant collection + hybrid query (``KnowledgeVectorStore``).
"""
