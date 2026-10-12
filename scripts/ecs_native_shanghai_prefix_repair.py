"""Repair only the owned AIO namespace; admission must remain drained externally."""

import argparse
import json
import os
from pathlib import Path
import stat

ROOT = Path("/srv/deerflow-native-task6b/56636cebddc6")
PRIVATE = ROOT / "private/820d7a3429d9/resident"
OLD = "deer-native-820d7a3429d9"
NEW = "deer-native-aio-820d7a3429d9"


def load(path):
    s = path.lstat()
    assert (
        stat.S_ISREG(s.st_mode) and s.st_uid == 0 and stat.S_IMODE(s.st_mode) == 0o600
    )
    return json.loads(path.read_text())


def replace(path, value):
    data = (json.dumps(value, indent=2) + "\n").encode()
    temp = path.with_name(path.name + ".prefix-new")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    os.replace(temp, path)


def main(role):
    assert os.getuid() == 0
    for directory in [ROOT, PRIVATE.parent, PRIVATE]:
        s = directory.lstat()
        assert (
            stat.S_ISDIR(s.st_mode)
            and s.st_uid == 0
            and stat.S_IMODE(s.st_mode) == 0o700
        )
    paths = [PRIVATE / "native.json", PRIVATE / "worker-ops.json"]
    if role == "controller":
        paths.append(PRIVATE / "controller-ops.json")
    before = {path: load(path) for path in paths}
    assert before[paths[0]]["sandbox"]["container_prefix"] in [OLD, NEW]
    for path in paths[1:]:
        assert before[path]["sandbox_prefix"] in [OLD, NEW]
        assert before[path]["node_id"] == "native-820d7a3429d9"
        assert before[path]["project"] == OLD + "-" + before[path]["role"]
    # Validate every file before writing any; resume remains a separate reviewed step.
    for path, value in before.items():
        if path.name == "native.json":
            value["sandbox"]["container_prefix"] = NEW
        else:
            value["sandbox_prefix"] = NEW
        replace(path, value)
    assert load(paths[0])["sandbox"]["container_prefix"] == NEW
    assert all(load(path)["sandbox_prefix"] == NEW for path in paths[1:])
    print(
        json.dumps(
            {
                "role": role,
                "aio_prefix": NEW,
                "role_project_unchanged": True,
                "models_and_credentials_unchanged": True,
                "roles_started": False,
                "admission_resumed": False,
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=["controller", "worker"])
    main(parser.parse_args().role)
