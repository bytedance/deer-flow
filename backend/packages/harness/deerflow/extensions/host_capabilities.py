"""Gateway-owned capability assembly and plugin-independent recovery lifetime."""

from __future__ import annotations

import asyncio
import logging

from deerflow_extension_api import HostCapabilityError
from sqlalchemy import select

from deerflow.extensions.completed_run_evidence import HostCompletedRunEvidenceReader
from deerflow.extensions.host_access import bind_host_access
from deerflow.persistence.skill_mutations.model import SkillAssetRow, SkillOwnerRow
from deerflow.skills.mutations.guard import SkillMutationRuntime, configure_mutation_runtime
from deerflow.skills.mutations.repository import SkillMutationRepository
from deerflow.skills.mutations.topology import PublicationTopology, mutation_session_factory
from deerflow.skills.mutations.workers import MutationWorkers
from deerflow.utils.file_io import await_drained

logger = logging.getLogger(__name__)


class HostCapabilities:
    """Register close() before start(); extension services must stop before close().

    Grants are restart-bound. Persisted enrollment is intentionally independent
    of the current plugin list: uninstalling a plugin cannot turn off recovery
    or let an old managed writer bypass an unresolved publication.
    """

    def __init__(self, config, run_store, event_store, *, root=None, storage_factory=None, recovery_factory=None, service_factory=None):
        self.config = config
        self.run_store = run_store
        self.event_store = event_store
        self.root = root
        self.storage_factory = storage_factory
        self.recovery_factory = recovery_factory
        self.service_factory = service_factory
        self.bindings = {}
        self.runtime = None
        self.recovery = None
        self.workers = None
        self._engine = None
        self._topology = None
        self._maintenance = None
        self._services = []

    async def start(self):
        access = bind_host_access(getattr(self.config, "plugins", ()))
        mutation_bindings = {source: binding for source, binding in access.items() if binding.access.skill_mutations.owners}
        for binding in mutation_bindings.values():
            if binding.access.skill_mutations.topology != "single_host_local":
                raise HostCapabilityError("UNSUPPORTED_TOPOLOGY", "Skill mutations require an explicit single_host_local operator assertion")
            if not set(binding.access.skill_mutations.owners).issubset(binding.access.evidence.owners):
                raise HostCapabilityError("INVALID_GRANT", "Skill mutation owners must also have completed-evidence access")

        owners = set()
        sf = getattr(self.run_store, "_sf", None)
        if sf is not None:
            async with sf() as session:
                owners.update(await session.scalars(select(SkillOwnerRow.owner_id)))
                owners.update(await session.scalars(select(SkillAssetRow.owner_id).distinct()))
        for binding in mutation_bindings.values():
            owners.update(binding.access.skill_mutations.owners)

        for source, binding in access.items():
            evidence = None
            if binding.access.evidence.owners:
                evidence = HostCompletedRunEvidenceReader(self.run_store, self.event_store, plugin_id=binding.plugin_id, owner_ids=binding.access.evidence.owners)
            if source in mutation_bindings:
                # Refuse a working-looking automatic API on unsupported stores.
                evidence._supported()
            self.bindings[source] = (evidence, None)

        if not owners:
            return
        if self.config.database.backend not in {"sqlite", "postgres"}:
            raise HostCapabilityError("UNSUPPORTED_TOPOLOGY")

        self.workers = MutationWorkers()

        def initialize(_check):
            from deerflow.config.paths import get_paths

            self._topology = PublicationTopology(self.config.database.backend, self.root or get_paths().base_dir)
            self._topology.acquire()
            self._engine, sessions = mutation_session_factory(self.config.database.app_sync_sqlalchemy_url, postgres_schema=self.config.database.postgres_schema)
            self.runtime = SkillMutationRuntime(SkillMutationRepository(sessions), owners=frozenset(owners))
            if self.storage_factory is None:
                from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage

                self.storage_factory = lambda owner: UserScopedSkillStorage(owner, app_config=self.config)
            factory = self.recovery_factory
            if factory is None:
                from deerflow.skills.mutations.recovery import SkillMutationRecovery

                factory = SkillMutationRecovery
            self.recovery = factory(self.runtime, self.storage_factory)
            configure_mutation_runtime(self.runtime)
            self.recovery.recover_all()
            self.recovery.collect_garbage()

        await self.workers.run(initialize)
        if mutation_bindings:
            from deerflow.config import get_app_config
            from deerflow.skills.mutations.scanner import CandidateScanner

            factory = self.service_factory
            if factory is None:
                from deerflow.skills.mutations.service import HostSkillMutationService

                factory = HostSkillMutationService
            scanner = CandidateScanner(get_app_config)
            for source, binding in mutation_bindings.items():
                evidence, _ = self.bindings[source]
                service = factory(binding, runtime=self.runtime, evidence=evidence, storage_factory=self.storage_factory, scanner=scanner, workers=self.workers, recovery=self.recovery)
                self._services.append(service)
                self.bindings[source] = (evidence, service)
        self._maintenance = asyncio.create_task(self._maintain(), name="skill-mutation-recovery")

    async def _maintain(self):
        while True:
            await asyncio.sleep(60)
            try:
                await self.workers.run(lambda _check: (self.recovery.recover_all(), self.recovery.collect_garbage()))
            except Exception:
                # No candidate bytes, model diagnostics, DB parameters or paths.
                logger.warning("Skill mutation maintenance unavailable; owner readiness barriers remain active")

    async def close(self):
        async def drain():
            if self._maintenance is not None:
                self._maintenance.cancel()
                await asyncio.gather(self._maintenance, return_exceptions=True)
                self._maintenance = None
            for service in self._services:
                close = getattr(service, "close", None)
                if close is not None:
                    await close()
            if self.workers is not None:
                await self.workers.close()
            if self.runtime is not None:
                configure_mutation_runtime(None)
            if self._engine is not None:
                await asyncio.to_thread(self._engine.dispose)
                self._engine = None
            if self._topology is not None:
                await asyncio.to_thread(self._topology.close)
                self._topology = None

        await await_drained(drain())
