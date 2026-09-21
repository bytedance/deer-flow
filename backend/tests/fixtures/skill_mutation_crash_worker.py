"""Fresh process terminated by SIGKILL at a selected publication boundary."""

import asyncio
import json
import os
import signal
import stat
import sys
from types import SimpleNamespace

from deerflow.config import paths
from deerflow.config.paths import Paths
from deerflow.extensions.host_access import BoundHostAccess, HostAccess
from deerflow.skills.mutations import publication
from deerflow.skills.mutations import service as service_module
from deerflow.skills.mutations.guard import SkillMutationRuntime, configure_mutation_runtime
from deerflow.skills.mutations.recovery import SkillMutationRecovery
from deerflow.skills.mutations.repository import SkillMutationRepository
from deerflow.skills.mutations.topology import mutation_session_factory
from deerflow.skills.storage.user_scoped_skill_storage import UserScopedSkillStorage


def die():
    os.kill(os.getpid(), signal.SIGKILL)


async def main(args):
    paths._paths = Paths(base_dir=args["base"])
    engine, sessions = mutation_session_factory(args["database"])
    storage = UserScopedSkillStorage("owner", host_path=args["skills"])
    runtime = SkillMutationRuntime(SkillMutationRepository(sessions), owners=frozenset({"owner"}))
    configure_mutation_runtime(runtime)
    recovery = SkillMutationRecovery(runtime, lambda _: storage, rebuild_views=lambda _: None)
    binding = BoundHostAccess("plugin", HostAccess.model_validate(args["grant"]))
    service = service_module.HostSkillMutationService(binding, runtime=runtime, evidence=SimpleNamespace(_scope="scope"), storage_factory=lambda _: storage, scanner=SimpleNamespace(policy_version_sync=lambda: "policy-1"), recovery=recovery)
    boundary = args["boundary"]
    if boundary == "prepared":
        service_module.publish_prepared = lambda *_: die()
    elif boundary == "written":
        write = os.write

        def write_then_die(fd, content):
            write(fd, content)
            die()

        publication.os.write = write_then_die
    elif boundary in {"file_synced", "directory_synced"}:
        fsync = os.fsync

        def sync_then_die(fd):
            fsync(fd)
            mode = os.fstat(fd).st_mode
            if (boundary == "file_synced" and stat.S_ISREG(mode)) or (boundary == "directory_synced" and stat.S_ISDIR(mode)):
                die()

        publication.os.fsync = sync_then_die
    elif boundary == "renamed":
        replace = os.replace

        def replace_then_die(*args, **kwargs):
            replace(*args, **kwargs)
            die()

        publication.os.replace = replace_then_die
    elif boundary == "response_lost":
        recovery.refresh_views = lambda _: die()
    await service.commit(proposal_id=args["proposal"], idempotency_key="crash-commit")
    await service.close()
    engine.dispose()
    raise AssertionError("fault injection did not fire")


if __name__ == "__main__":
    asyncio.run(main(json.loads(sys.argv[1])))
