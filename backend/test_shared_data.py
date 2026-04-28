"""Verify shared-data mount works end-to-end."""

import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
os.chdir(backend_dir)
sys.path.insert(0, str(backend_dir))

from deerflow.config import get_app_config

# 1. Check config
config = get_app_config()
print("=== Config sandbox.mounts ===")
for m in config.sandbox.mounts:
    print(f"  host_path: {m.host_path}")
    print(f"  container_path: {m.container_path}")
    print(f"  read_only: {m.read_only}")

# 2. Check _get_custom_mounts() with cache cleared
from deerflow.sandbox.tools import _get_custom_mounts, _is_custom_mount_path

_get_custom_mounts._cached = None

mounts = _get_custom_mounts()
print("\n=== _get_custom_mounts() ===")
print(f"  Found {len(mounts)} mount(s)")
for m in mounts:
    print(f"  - {m.host_path} -> {m.container_path}")

# 3. Test path validation
print("\n=== Path validation ===")
test_paths = ["/mnt/shared-data/test.txt", "/mnt/shared-data/sub/file.md", "/mnt/user-data/workspace/x.md"]
for p in test_paths:
    result = _is_custom_mount_path(p)
    print(f"  {p} -> is_custom_mount: {result}")

# 4. Test LocalSandboxProvider path_mappings
from deerflow.sandbox.local.local_sandbox_provider import LocalSandboxProvider

provider = LocalSandboxProvider()
print("\n=== LocalSandboxProvider path_mappings ===")
for m in provider._path_mappings:
    print(f"  {m.container_path} -> {m.local_path} (read_only={m.read_only})")

# 5. Test path resolution
from deerflow.sandbox.local.local_sandbox import LocalSandbox

sandbox = LocalSandbox("test", path_mappings=provider._path_mappings)

print("\n=== _resolve_path test ===")
for p in ["/mnt/shared-data/test.txt", "/mnt/shared-data", "/mnt/skills/public/test.md"]:
    resolved = sandbox._resolve_path(p)
    print(f"  {p} -> {resolved}")

# 6. Test write_file
print("\n=== Write test ===")
try:
    sandbox.write_file("/mnt/shared-data/test_write.txt", "hello from shared-data\n")
    print("  Write SUCCESS")
except Exception as e:
    print(f"  Write FAILED: {type(e).__name__}: {e}")

# 7. Test read_file
print("\n=== Read test ===")
try:
    content = sandbox.read_file("/mnt/shared-data/test_write.txt")
    print(f"  Read SUCCESS: {repr(content)}")
except Exception as e:
    print(f"  Read FAILED: {type(e).__name__}: {e}")

# 8. Test list_dir
print("\n=== list_dir test ===")
try:
    entries = sandbox.list_dir("/mnt/shared-data")
    print(f"  list_dir SUCCESS: {entries}")
except Exception as e:
    print(f"  list_dir FAILED: {type(e).__name__}: {e}")

# Cleanup
try:
    os.remove(sandbox._resolve_path("/mnt/shared-data/test_write.txt"))
except:
    pass
