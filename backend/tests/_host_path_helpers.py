"""Helpers for asserting on paths the codebase spells in host-native style.

The provisioner's ``join_host_path`` deliberately preserves the host
filesystem style (explicit ``PureWindowsPath`` branch), and
``os.path.normpath`` re-spells POSIX inputs with backslashes on Windows, so
hostPath volume strings, docker ``--mount`` args and ``PYTHONPATH`` entries
carry ``\\`` on a Windows host where POSIX CI sees ``/``. Tests that match
segments inside such strings normalize with :func:`posix_path` instead of
hard-coding one separator; the replace is a no-op on POSIX inputs.
"""


def posix_path(path: str) -> str:
    return path.replace("\\", "/")
