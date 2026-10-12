"""Jenkins runs only the fixed approved B infrastructure entry using existing binding."""

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path("/data/jenkins-agent/deerflow/native-task6b-56636cebddc6")
helper = ROOT / "scripts/ecs_native_shanghai_bootstrap.py"
assert (
    hashlib.sha256(helper.read_bytes()).hexdigest()
    == "8d9f9613a0bdda49b763a5cf84c8b41d25e1e13dc351a9d4012928e88952a92a"
)
spec = importlib.util.spec_from_file_location("fixed_bootstrap", helper)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
for name, sha in [
    (
        "ecs_native_shanghai_b_main.py",
        "baf3d9a2ae161595bb64b9678ca3e6761016673db66f579f908bb89d00123ff2",
    ),
    (
        "ecs_native_shanghai_b_entry.py",
        "a255344e4dfd8c069421285affb069c785de94a64edff1553220ece9da43c637",
    ),
]:
    module.copy_public(
        "192.168.0.190",
        ROOT / "scripts" / name,
        module.REMOTE + "/bootstrap/" + name,
        sha,
    )
entry = module.REMOTE + "/bootstrap/ecs_native_shanghai_b_entry.py"
receipt = module.remote(
    "192.168.0.190",
    f'import subprocess;r=subprocess.run(["python3",{entry!r}],capture_output=True,timeout=300);assert r.returncode==0;print(r.stdout.decode())',
)
# The entry only returns selected public status/owned task proof; private log stays remote.
for line in receipt.decode().splitlines():
    if not line.strip():
        continue
    value = json.loads(line)
    assert set(value) <= {
        "worker_operator_status",
        "b_oneoff",
        "owned_thread_retained_for_native_cleanup",
        "models_called",
    }
    print(json.dumps(value))
