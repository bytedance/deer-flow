"""RAG knowledge-base subsystem.

Offline indexing (parse → chunk → embed → extract → wiki) and the shared
storage layer (business tables + Qdrant vector store). Online retrieval ships
as builtin agent tools under ``deerflow.tools.builtins`` (Task 7).

Layout:
- ``models.py`` — SQLAlchemy rows for the six knowledge tables.
- ``store.py`` — CRUD over the business tables (``KnowledgeStore``).
- ``vector_store.py`` — Qdrant collections + hybrid query (``KnowledgeVectorStore``).
"""
