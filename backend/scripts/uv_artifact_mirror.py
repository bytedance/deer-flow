"""CI-only artifact transport rewrite; dependency metadata stays unchanged."""

import copy
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

lock = Path("uv.lock")
assert lock.is_file() and not lock.is_symlink()
mirror = os.environ["UV_ARTIFACT_MIRROR"]
assert mirror == "https://mirrors.tuna.tsinghua.edu.cn/pypi/web"
original = lock.read_bytes()
expected = copy.deepcopy(tomllib.loads(original.decode()))
rewritten = original.decode()
changed = 0
for package in expected["package"]:
    artifacts = list(package.get("wheels", []))
    if "sdist" in package:
        artifacts.append(package["sdist"])
    for artifact in artifacts:
        url = artifact.get("url", "")
        if not url.startswith("https://files.pythonhosted.org/packages/"):
            continue
        parsed = urlsplit(url)
        assert parsed.hostname == "files.pythonhosted.org"
        assert not parsed.query and not parsed.fragment
        assert ".." not in Path(parsed.path).parts
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["hash"])
        assert isinstance(artifact["size"], int) and artifact["size"] > 0
        replacement = mirror + parsed.path
        assert '"' + url + '"' in rewritten
        rewritten = rewritten.replace('"' + url + '"', '"' + replacement + '"')
        artifact["url"] = replacement
        changed += 1
assert changed > 0
# Reject changes to any field outside the selected artifact URL dictionaries.
assert tomllib.loads(rewritten) == expected
lock.write_bytes(rewritten.encode())
