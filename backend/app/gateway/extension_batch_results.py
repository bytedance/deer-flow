"""Install native result admission without importing unrelated Gateway routes."""

from collections.abc import Callable

from deerflow_extension_api.auth import ExtensionPrincipal
from deerflow_extension_api.batch_results import BATCH_RESULTS_RESOLVER_KEY, BatchResultError, BatchResultReader
from fastapi import FastAPI, Request


def install_batch_result_reader(app: FastAPI, principal_resolver: Callable[[Request], ExtensionPrincipal | None]) -> None:
    """Keep principal projection host-owned and resolve live storage per request."""

    def resolve(request: Request) -> BatchResultReader | None:
        principal = principal_resolver(request)
        auth = getattr(request.state, "auth", None)
        if principal is None or auth is None or not auth.has_permission("threads", "read"):
            raise BatchResultError(403, "Batch results require an authenticated user with threads:read")
        repository = getattr(app.state, "subagent_batch_repo", None)
        thread_store = getattr(app.state, "thread_store", None)
        if repository is None or thread_store is None:
            return None
        from deerflow.extensions.batch_results import RepositoryBatchResultReader

        async def check_thread(thread_id: str) -> bool:
            return await thread_store.check_access(thread_id, principal.user_id)

        return RepositoryBatchResultReader(repository, user_id=principal.user_id, check_thread=check_thread)

    setattr(app.state, BATCH_RESULTS_RESOLVER_KEY, resolve)
