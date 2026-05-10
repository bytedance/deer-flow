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
    ) -> None:
        self._kb_repo = kb_repo
        self._doc_repo = doc_repo
        self._job_repo = job_repo
        self._perm_repo = permission_repo or KbPermissionRepository.__new__(KbPermissionRepository)
        self._access_control = KbAccessControl(self._perm_repo)
        self._indexing = IndexingService(kb_repo, doc_repo, job_repo)

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
        await self._indexing.execute_index_job(doc, kb)
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
                await self._indexing.execute_index_job(updated, kb)
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

        await self._indexing.execute_index_job(doc, kb)
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

        await self._indexing.execute_index_job(doc, kb)
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
            await self._indexing.execute_index_job(updated, kb)
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

        await self._indexing.execute_index_job(doc, kb)
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
