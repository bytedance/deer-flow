"""KnowledgeBaseService — business logic for knowledge base operations."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from deerflow.knowledge_base.access_control import KbAccessControl, UserContext
from deerflow.knowledge_base.indexing import IndexingService
from deerflow.persistence.knowledge_base.document_repository import DocumentRepository
from deerflow.persistence.knowledge_base.index_job_repository import IndexJobRepository
from deerflow.persistence.knowledge_base.permission_repository import KbPermissionRepository
from deerflow.persistence.knowledge_base.repository import KnowledgeBaseRepository

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    def __init__(
        self,
        kb_repo: KnowledgeBaseRepository,
        doc_repo: DocumentRepository,
        job_repo: IndexJobRepository,
        permission_repo: KbPermissionRepository | None = None,
        *,
        dispatcher: Any = None,
    ) -> None:
        if permission_repo is None:
            raise ValueError(
                "KnowledgeBaseService requires a KbPermissionRepository. "
                "Pass one explicitly — the previous KbPermissionRepository.__new__ "
                "shortcut left the repository without a session factory and silently "
                "broke any access-control / permission-management code path."
            )
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._job_repo = job_repo
        self._perm_repo = permission_repo
        self._access_control = KbAccessControl(self._perm_repo)
        self._indexing = IndexingService(kb_repo, doc_repo, job_repo)
        self._dispatcher = dispatcher

    def attach_dispatcher(self, dispatcher: Any) -> None:
        """Inject the dispatcher after construction (Gateway lifecycle order)."""
        self._dispatcher = dispatcher

    async def _run_index_job(self, doc: dict[str, Any], kb: dict[str, Any]) -> None:
        """Submit an index job to the dispatcher when available, else run inline.

        Why: Sprint B promises 202 + ``pending`` as the upload contract,
        but legacy code paths (tests, ``indexing_workers=0``) still expect
        synchronous indexing. Routing through here keeps both behaviors
        in a single decision instead of scattering ``if dispatcher`` across
        every caller.
        """
        dispatcher = self._dispatcher
        if dispatcher is not None and getattr(dispatcher, "enabled", False):
            from deerflow.knowledge_base.dispatcher import IndexJobRequest

            await dispatcher.submit(IndexJobRequest(document=doc, knowledge_base=kb))
            return
        # Inline fallback — dispatcher disabled (e.g. indexing_workers=0).
        await self._indexing.execute_index_job(doc, kb)

    # ------------------------------------------------------------------
    # Knowledge Base CRUD
    # ------------------------------------------------------------------

    async def create_knowledge_base(
        self,
        *,
        tenant_id: str,
        owner_user_id: str,
        name: str,
        description: str | None = None,
        visibility: str = "private",
    ) -> dict[str, Any]:
        return await self._kb_repo.create(
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            name=name,
            description=description,
            visibility=visibility,
        )

    async def get_knowledge_base(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        return await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)

    async def list_knowledge_bases(
        self,
        *,
        tenant_id: str,
        user_id: str,
        visibility_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._kb_repo.list_accessible(
            tenant_id=tenant_id,
            user_id=user_id,
            visibility_filter=visibility_filter,
            limit=limit,
            offset=offset,
        )

    async def update_knowledge_base(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any] | None:
        fields: dict[str, Any] = {}
        if name is not None:
            fields["name"] = name
        if description is not None:
            fields["description"] = description
        if not fields:
            return await self._kb_repo.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        return await self._kb_repo.update(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id, **fields)

    async def delete_knowledge_base(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        kb = await self._kb_repo.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if kb is None:
            return False

        # Soft-delete all documents
        await self._doc_repo.soft_delete_by_kb(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

        # Soft-delete the KB
        deleted = await self._kb_repo.soft_delete(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

        # Delete the vector collection
        if deleted:
            try:
                from deerflow.rag.vector_store import get_vector_store
                store = get_vector_store()
                store.delete_collection(kb["collection_name"])
            except Exception as e:
                logger.warning("Failed to delete collection %s: %s", kb["collection_name"], e)

        return deleted

    # ------------------------------------------------------------------
    # Document CRUD
    # ------------------------------------------------------------------

    async def create_document(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        title: str,
        content: str,
        content_format: str = "markdown",
        source_name: str | None = None,
        metadata_json: dict | None = None,
    ) -> dict[str, Any]:
        kb = await self._kb_repo.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        doc = await self._doc_repo.create(
            knowledge_base_id=kb_id,
            tenant_id=tenant_id,
            owner_user_id=owner_user_id,
            title=title,
            content=content,
            content_hash=content_hash,
            content_format=content_format,
            source_name=source_name,
            metadata_json=metadata_json,
        )

        # Trigger indexing
        await self._run_index_job(doc, kb)
        # Re-fetch to get updated index status
        return await self._doc_repo.get(doc["id"], tenant_id=tenant_id, owner_user_id=owner_user_id) or doc

    async def get_document(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        return await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

    async def list_documents(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        return await self._doc_repo.list_by_kb(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id, limit=limit, offset=offset)

    async def update_document(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        title: str | None = None,
        content: str | None = None,
        content_format: str | None = None,
        source_name: str | None = None,
    ) -> dict[str, Any] | None:
        doc = await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if doc is None:
            return None

        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if content_format is not None:
            fields["content_format"] = content_format
        if source_name is not None:
            fields["source_name"] = source_name

        needs_reindex = False
        if content is not None:
            new_hash = hashlib.sha256(content.encode()).hexdigest()
            if new_hash != doc["content_hash"]:
                fields["content"] = content
                fields["content_hash"] = new_hash
                fields["content_length"] = len(content)
                fields["version"] = doc["version"] + 1
                needs_reindex = True

        if not fields:
            return doc

        updated = await self._doc_repo.update(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id, **fields)

        if needs_reindex and updated:
            kb = await self._kb_repo.get(doc["knowledge_base_id"], tenant_id=tenant_id, owner_user_id=owner_user_id)
            if kb:
                await self._run_index_job(updated, kb)
                updated = await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

        return updated

    async def delete_document(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> bool:
        doc = await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if doc is None:
            return False

        deleted = await self._doc_repo.soft_delete(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

        # Remove chunks from vector store
        if deleted and doc.get("chunk_ids"):
            try:
                kb = await self._kb_repo.get_by_id_internal(doc["knowledge_base_id"])
                if kb:
                    from deerflow.rag.vector_store import get_vector_store
                    store = get_vector_store()
                    store.delete(kb["collection_name"], doc["chunk_ids"])
            except Exception as e:
                logger.warning("Failed to delete chunks for doc %s: %s", doc_id, e)

        # Update KB stats
        if deleted:
            await self._indexing._update_kb_stats(doc["knowledge_base_id"])

        return deleted

    async def reindex_document(
        self,
        doc_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
    ) -> dict[str, Any] | None:
        doc = await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if doc is None:
            return None

        kb = await self._kb_repo.get(doc["knowledge_base_id"], tenant_id=tenant_id, owner_user_id=owner_user_id)
        if kb is None:
            return None

        await self._run_index_job(doc, kb)
        return await self._doc_repo.get(doc_id, tenant_id=tenant_id, owner_user_id=owner_user_id)

    # ------------------------------------------------------------------
    # Permission-aware operations (Sprint 2)
    # ------------------------------------------------------------------

    @property
    def access_control(self) -> KbAccessControl:
        return self._access_control

    @property
    def permission_repo(self) -> KbPermissionRepository:
        return self._perm_repo

    async def check_write_permission(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> dict[str, Any]:
        """Check write permission and return the KB dict. Raises ValueError if denied."""
        kb = await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")
        user_ctx = UserContext(user_id=user_id, tenant_id=tenant_id, role=role)
        if not await self._access_control.can_write(user_ctx, kb):
            raise PermissionError("Write access denied")
        return kb

    async def check_admin_permission(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> dict[str, Any]:
        """Check admin permission and return the KB dict. Raises ValueError/PermissionError."""
        kb = await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")
        user_ctx = UserContext(user_id=user_id, tenant_id=tenant_id, role=role)
        if not await self._access_control.can_admin(user_ctx, kb):
            raise PermissionError("Admin access denied")
        return kb

    async def create_document_with_access_check(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
        title: str,
        content: str,
        content_format: str = "markdown",
        source_name: str | None = None,
        metadata_json: dict | None = None,
    ) -> dict[str, Any]:
        """Create a document after verifying write permission on the KB."""
        kb = await self.check_write_permission(kb_id, user_id=user_id, tenant_id=tenant_id, role=role)

        content_hash = hashlib.sha256(content.encode()).hexdigest()
        doc = await self._doc_repo.create(
            knowledge_base_id=kb_id,
            tenant_id=tenant_id,
            owner_user_id=user_id,
            title=title,
            content=content,
            content_hash=content_hash,
            content_format=content_format,
            source_name=source_name,
            metadata_json=metadata_json,
        )

        await self._run_index_job(doc, kb)
        return await self._doc_repo.get_by_id_internal(doc["id"]) or doc

    async def list_documents_with_access_check(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List documents after verifying read access on the KB."""
        kb = await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")
        return await self._doc_repo.list_by_kb_accessible(kb_id, limit=limit, offset=offset)

    async def get_document_with_access_check(
        self,
        kb_id: str,
        doc_id: str,
        *,
        user_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """Get a document after verifying read access on the KB."""
        kb = await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)
        if kb is None:
            return None
        return await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)

    async def update_document_with_access_check(
        self,
        kb_id: str,
        doc_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
        title: str | None = None,
        content: str | None = None,
        content_format: str | None = None,
        source_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Update a document after verifying write permission on the KB."""
        kb = await self.check_write_permission(kb_id, user_id=user_id, tenant_id=tenant_id, role=role)

        doc = await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)
        if doc is None:
            return None

        fields: dict[str, Any] = {}
        if title is not None:
            fields["title"] = title
        if content_format is not None:
            fields["content_format"] = content_format
        if source_name is not None:
            fields["source_name"] = source_name

        needs_reindex = False
        if content is not None:
            new_hash = hashlib.sha256(content.encode()).hexdigest()
            if new_hash != doc["content_hash"]:
                fields["content"] = content
                fields["content_hash"] = new_hash
                fields["content_length"] = len(content)
                fields["version"] = doc["version"] + 1
                needs_reindex = True

        if not fields:
            return doc

        updated = await self._doc_repo.update_by_kb(doc_id, knowledge_base_id=kb_id, **fields)

        if needs_reindex and updated:
            await self._run_index_job(updated, kb)
            updated = await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)

        return updated

    async def delete_document_with_access_check(
        self,
        kb_id: str,
        doc_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> bool:
        """Delete a document after verifying write permission on the KB."""
        kb = await self.check_write_permission(kb_id, user_id=user_id, tenant_id=tenant_id, role=role)

        doc = await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)
        if doc is None:
            return False

        deleted = await self._doc_repo.soft_delete_by_kb_doc(doc_id, knowledge_base_id=kb_id)

        if deleted and doc.get("chunk_ids"):
            try:
                from deerflow.rag.vector_store import get_vector_store
                store = get_vector_store()
                store.delete(kb["collection_name"], doc["chunk_ids"])
            except Exception as e:
                logger.warning("Failed to delete chunks for doc %s: %s", doc_id, e)

        if deleted:
            await self._indexing._update_kb_stats(kb_id)

        return deleted

    async def reindex_document_with_access_check(
        self,
        kb_id: str,
        doc_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> dict[str, Any] | None:
        """Reindex a document after verifying write permission on the KB."""
        kb = await self.check_write_permission(kb_id, user_id=user_id, tenant_id=tenant_id, role=role)

        doc = await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)
        if doc is None:
            return None

        await self._run_index_job(doc, kb)
        return await self._doc_repo.get_by_kb(doc_id, knowledge_base_id=kb_id)

    async def get_kb_with_permissions(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> dict[str, Any] | None:
        """Get a KB with additional permission fields (my_role, can_write, can_admin)."""
        kb = await self._kb_repo.get_accessible(kb_id, tenant_id=tenant_id, user_id=user_id)
        if kb is None:
            return None
        user_ctx = UserContext(user_id=user_id, tenant_id=tenant_id, role=role)
        kb["my_role"] = await self._access_control.get_user_kb_role(user_ctx, kb)
        kb["can_write"] = await self._access_control.can_write(user_ctx, kb)
        kb["can_admin"] = await self._access_control.can_admin(user_ctx, kb)
        return kb

    # ------------------------------------------------------------------
    # Permission Management (Sprint 3)
    # ------------------------------------------------------------------

    async def grant_permission(
        self,
        kb_id: str,
        *,
        grantor_user_id: str,
        grantor_tenant_id: str,
        grantor_role: str,
        target_user_id: str,
        role: str,
    ) -> dict[str, Any]:
        """Grant a permission on a KB. Only admins can grant permissions."""
        kb = await self.check_admin_permission(
            kb_id, user_id=grantor_user_id, tenant_id=grantor_tenant_id, role=grantor_role
        )
        if role not in ("viewer", "editor", "admin"):
            raise ValueError(f"Invalid role: {role}. Must be viewer, editor, or admin.")
        return await self._perm_repo.grant(
            knowledge_base_id=kb_id,
            tenant_id=kb["tenant_id"],
            user_id=target_user_id,
            role=role,
            granted_by=grantor_user_id,
        )

    async def revoke_permission(
        self,
        kb_id: str,
        *,
        grantor_user_id: str,
        grantor_tenant_id: str,
        grantor_role: str,
        target_user_id: str,
    ) -> bool:
        """Revoke a permission on a KB. Only admins can revoke permissions."""
        await self.check_admin_permission(
            kb_id, user_id=grantor_user_id, tenant_id=grantor_tenant_id, role=grantor_role
        )
        return await self._perm_repo.revoke(knowledge_base_id=kb_id, user_id=target_user_id)

    async def list_permissions(
        self,
        kb_id: str,
        *,
        user_id: str,
        tenant_id: str,
        role: str,
    ) -> list[dict[str, Any]]:
        """List all permission grants for a KB. Only admins can view permissions."""
        await self.check_admin_permission(kb_id, user_id=user_id, tenant_id=tenant_id, role=role)
        return await self._perm_repo.list_by_kb(kb_id)

    # ------------------------------------------------------------------
    # Admin View (Sprint 3)
    # ------------------------------------------------------------------

    async def list_admin_knowledge_bases(
        self,
        *,
        tenant_id: str,
        role: str,
        visibility_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List all tenant/public KBs for admin users.

        superadmin: sees all tenant + public KBs.
        tenant_admin: sees all tenant KBs in their tenant.
        """
        if role not in ("superadmin", "tenant_admin"):
            raise PermissionError("Admin role required")
        return await self._kb_repo.list_admin(
            tenant_id=tenant_id,
            role=role,
            visibility_filter=visibility_filter,
            limit=limit,
            offset=offset,
        )

    # ------------------------------------------------------------------
    # Reindex-all (admin)
    # ------------------------------------------------------------------

    async def reindex_all_for_kb(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        role: str,
    ) -> dict[str, Any]:
        """Tear down the KB's vector collection and re-queue every doc.

        Why: Chroma collection metadata (``hnsw:space``) is immutable
        once a collection exists. After A.10 flips L2 collections to
        ``vector_metric_stale=true``, the only way to repair them is to
        delete the collection and let the per-doc indexing path recreate
        it with ``metadata={"hnsw:space":"cosine"}`` on first ``add``.
        Per-doc dispatcher jobs keep one bad doc from blocking the rest;
        the KB stays ``vector_metric_stale=true`` until at least one job
        succeeds, so retrieval doesn't briefly serve from an empty
        collection mid-reindex.
        """
        if role not in ("superadmin", "tenant_admin"):
            raise PermissionError("Admin role required")

        kb = await self._kb_repo.get_by_id_internal(kb_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")
        if role == "tenant_admin" and kb.get("tenant_id") != tenant_id:
            raise PermissionError("Cross-tenant reindex not permitted")

        # Mark stale up-front so retrieval skips this KB while we tear
        # down + re-queue. The dispatcher's first successful job clears
        # the flag via update_embedding_binding + a follow-up unstale.
        await self._kb_repo.set_vector_metric_stale(kb_id, stale=True)

        # Drop the existing collection. Failure here is not fatal: the
        # collection may not exist yet, or the backend may already be
        # in the desired state. Log and continue.
        try:
            from deerflow.rag.vector_store import get_vector_store

            store = get_vector_store()
            store.delete_collection(kb["collection_name"])
        except Exception as e:
            logger.warning(
                "reindex_all_for_kb: delete_collection failed for kb=%s: %s",
                kb_id, e,
            )

        # Dim binding may have shifted if the operator is migrating to a
        # different embedding model — clear so the first successful job
        # backfills via the lazy path.
        await self._kb_repo.update_embedding_binding(kb_id, embedding_dim=0)

        docs = await self._doc_repo.list_by_kb_accessible(
            kb_id, limit=10_000, offset=0
        )

        queued = 0
        failed: list[str] = []
        for doc in docs:
            # Bump version so any in-flight job for this doc gets
            # cancelled by the version-guard in execute_index_job.
            try:
                next_version = int(doc.get("version") or 1) + 1
                await self._doc_repo.update(
                    doc["id"],
                    tenant_id=doc["tenant_id"],
                    owner_user_id=doc["owner_user_id"],
                    version=next_version,
                )
                bumped = dict(doc)
                bumped["version"] = next_version
                # Clear chunk_ids so the version guard in indexing path
                # doesn't try to delete chunks that no longer exist.
                bumped["chunk_ids"] = []
                await self._run_index_job(bumped, kb)
                queued += 1
            except Exception as e:
                logger.warning(
                    "reindex_all_for_kb: failed to queue doc %s: %s",
                    doc.get("id"), e,
                )
                failed.append(str(doc.get("id")))

        return {
            "kb_id": kb_id,
            "collection_name": kb.get("collection_name"),
            "doc_total": len(docs),
            "doc_queued": queued,
            "doc_failed": failed,
        }

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        kb_id: str,
        *,
        tenant_id: str,
        owner_user_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        from deerflow.rag.retrieval import DocumentRetriever

        kb = await self._kb_repo.get(kb_id, tenant_id=tenant_id, owner_user_id=owner_user_id)
        if kb is None:
            raise ValueError(f"Knowledge base {kb_id} not found")

        retriever = DocumentRetriever()
        result = retriever.retrieve(query, collection=kb["collection_name"], top_k=top_k)

        return [
            {"chunk_id": r.chunk_id, "content": r.content, "score": r.score, "metadata": r.metadata}
            for r in result.results
        ]

    # ------------------------------------------------------------------
    # Startup hooks
    # ------------------------------------------------------------------

    async def startup_consistency_check(self) -> dict[str, Any]:
        """Mark KBs whose underlying vector collection uses the wrong metric.

        Why: Sprint A enforces ``hnsw:space=cosine`` on every newly created
        Chroma collection (see ``CHROMA_COSINE_METADATA``). Pre-existing
        collections from before that enforcement are typically L2 — the
        old retrieval code "looked correct" because it always applied a
        cosine→similarity formula, which silently produced wrong scores.

        We don't auto-rebuild here (Chroma's metric is immutable; the user
        decides when to ``reindex-all``). Instead we flag the KB so the
        retrieval path can skip it with a clear ``vector_metric_stale``
        reason rather than serve garbage.
        """
        from deerflow.rag.backends.chroma import ChromaVectorStore
        from deerflow.config.tenant import reset_tenant_id, set_current_tenant_id, validate_tenant_id

        store = ChromaVectorStore()
        try:
            kbs = await self._kb_repo.list_all_active_internal()
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("startup_consistency_check: failed to list KBs: %s", exc)
            return {"checked": 0, "marked_stale": 0, "errors": 1}

        marked = 0
        errors = 0
        for kb in kbs:
            kb_id = kb.get("id")
            tid = str(kb.get("tenant_id", "") or "")
            collection = str(kb.get("collection_name", "") or "")
            already_stale = bool(kb.get("vector_metric_stale", False))
            if not kb_id or not tid or not collection:
                continue
            try:
                validate_tenant_id(tid)
            except ValueError:
                continue
            token = set_current_tenant_id(tid)
            try:
                client = store._get_client()
                col_name = store._collection_name(collection)
                try:
                    col = client.get_collection(name=col_name)
                except Exception:
                    continue
                metric = store._resolve_metric(col)
                if metric != "cosine" and not already_stale:
                    try:
                        await self._kb_repo.set_vector_metric_stale(kb_id, stale=True)
                        marked += 1
                        logger.warning(
                            "KB %s (collection=%s) uses metric=%r — flagged vector_metric_stale; "
                            "run reindex-all to rebuild as cosine",
                            kb_id,
                            col_name,
                            metric,
                        )
                    except Exception as exc:  # pragma: no cover — defensive
                        errors += 1
                        logger.warning(
                            "Failed to mark KB %s stale: %s", kb_id, exc
                        )
            finally:
                reset_tenant_id(token)
        return {"checked": len(kbs), "marked_stale": marked, "errors": errors}
