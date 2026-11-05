"""Space policy is an additional restriction on the existing management provider."""

import asyncio

from deerflow_extension_knowledge_management.contracts import ManagementContext, ProcessingOptions, ProcessingResult

from .store import RevisionConflict, administrator


class Platform:
    def __init__(self, settings, store, providers):
        self.settings, self.store, self.providers = settings, store, providers

    async def policy(self, principal):
        return await asyncio.to_thread(self.store.read, principal)

    async def replace(self, principal, policy, revision):
        return await asyncio.to_thread(self.store.replace, principal, policy, revision)

    async def spaces(self, principal):
        return await asyncio.to_thread(self.store.spaces, principal)

    async def effective(self, principal, space_id):
        return await asyncio.to_thread(self.store.effective, principal, space_id)

    async def _admit(self, principal, space_id, resource, operation):
        # Keep phase 2's explicit administrator floor; never impersonate a member.
        administrator(principal)
        effective = await self.effective(principal, space_id)
        for item in effective["resources"]:
            if item["resource_id"] == resource and operation in item["operations"]:
                return effective["revision"], item
        raise PermissionError("Space resource operation denied")

    @staticmethod
    def _result(result, item, document=None):
        try:
            result = ProcessingResult.model_validate(result)
        except ValueError:
            raise RuntimeError("Invalid management result") from None
        if (result.provider, result.connection_id, result.dataset_id) != (item["provider"], item["connection_id"], item["dataset_id"]) or (document is not None and result.document_id != document):
            raise RuntimeError("Management result identity does not match space resource")
        return result

    async def invoke(self, principal, space_id, resource, operation, payload=None, *, document=None, filename=None, content=None):
        revision, item = await self._admit(principal, space_id, resource, operation)
        provider = self.providers[item["connection_id"]]
        context = ManagementContext(principal=principal)
        connection, base = item["connection_id"], item["native_base_id"]
        if operation == "status":
            return self._result(await provider.status(context, connection, base, payload), item, payload)
        capabilities = await provider.capabilities(context, connection, base)
        if operation == "capabilities":
            return capabilities.model_copy(update={"operations": capabilities.operations & set(item["operations"])})
        if operation not in capabilities.operations:
            raise NotImplementedError("Provider does not support this operation")
        if operation in {"manual", "url", "upload"}:
            # Defaults are for NEW documents; an empty reprocess preserves upstream policy.
            supplied = payload.processing if operation != "upload" else payload
            options = ProcessingOptions.model_validate({**item["processing"], **supplied.model_dump(exclude_none=True)})
        else:
            options = payload
        if not options.model_dump(exclude_none=True).keys() <= capabilities.processing_options:
            raise NotImplementedError("Provider does not support selected processing options")
        # Capabilities may involve upstream I/O. Recheck all policy before submitting a write.
        latest, _ = await self._admit(principal, space_id, resource, operation)
        if latest != revision:
            raise RevisionConflict("Policy changed during admission; reconcile before retrying")
        if operation in {"manual", "url"}:
            result = await provider.ingest(context, connection, base, payload.model_copy(update={"processing": options}))
            return self._result(result, item)
        if operation == "upload":
            return self._result(await provider.upload(context, connection, base, filename, content, options), item)
        if operation in {"reprocess", "cancel"}:
            return self._result(await provider.process(context, connection, base, document, operation, options), item, document)
        raise ValueError("Unknown management operation")
