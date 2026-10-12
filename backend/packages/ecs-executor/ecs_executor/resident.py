"""Small trusted supervisor: native Gateway and outbound B daemon share one cgroup.

Normal SIGTERM is issued only after operator drain/idle proof. Unexpected child
exit stops its sibling; durable unknown reservations are never cleared here.
"""

import os
import signal
import subprocess
import sys
import time


def main():
    worker = os.environ.get("ECS_RESIDENT_ROLE") == "worker"
    host = "127.0.0.1" if worker else "0.0.0.0"
    command = [sys.executable, "-m", "uvicorn", "app.gateway.app:app", "--host", host, "--port", "8001", "--timeout-graceful-shutdown", "10"]
    if not worker:
        proxy = os.environ["ECS_TRUSTED_PROXY_IP"]
        import ipaddress

        ipaddress.ip_address(proxy)
        command.extend(["--proxy-headers", "--forwarded-allow-ips", proxy])
    else:
        command.append("--no-proxy-headers")
    processes = [subprocess.Popen(command)]
    stopping = False

    def terminate(_signum=None, _frame=None):
        nonlocal stopping
        if not stopping:
            stopping = True
            for process in processes:
                if process.poll() is None:
                    process.send_signal(signal.SIGTERM)

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    if worker:
        # B and C remain separate engines/locks, but physical resident overhead
        # is capped together by the worker container's 500m / 1 GiB cgroup.
        processes.append(subprocess.Popen([sys.executable, "-m", "ecs_executor.dispatch"]))
    failed = False
    while any(process.poll() is None for process in processes):
        if not stopping and any(process.poll() is not None for process in processes):
            failed = True
            terminate()
        time.sleep(0.1)
    raise SystemExit(1 if failed or any(process.returncode not in (0, -signal.SIGTERM) for process in processes) else 0)


if __name__ == "__main__":
    main()
