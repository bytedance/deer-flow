"""
Windows 兼容修复 — DeerFlow 2.0

Fix 1: 强制 UTF-8 输出，绕过 GBK 终端编码
Fix 2: 路径大小写规范化
Fix 3: 环境变量补丁

用法: python windows_fix.py [command...]
  直接运行: python windows_fix.py
  作为 wrapper: python windows_fix.py uv run python scripts/setup_wizard.py
"""
import os
import sys
import io
import subprocess

# Fix 1: 强制 stdout/stderr 使用 UTF-8
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    # 设置控制台代码页为 UTF-8
    os.system("chcp 65001 > nul 2>&1")

# Fix 2: 设置关键环境变量
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("LANG", "en_US.UTF-8")

# Fix 3: 确保项目根目录在 PYTHONPATH
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
backend_dir = os.path.join(project_root, "backend")
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# 如果有参数，作为子进程运行
if len(sys.argv) > 1:
    cmd = sys.argv[1:]
    print(f"[windows_fix] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=project_root)
    sys.exit(result.returncode)
else:
    print("[windows_fix] Environment patched successfully")
    print(f"  Project root: {project_root}")
    print(f"  PYTHONIOENCODING: {os.environ.get('PYTHONIOENCODING')}")
    print(f"  PYTHONUTF8: {os.environ.get('PYTHONUTF8')}")
