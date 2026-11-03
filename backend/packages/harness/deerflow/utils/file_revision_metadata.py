"""Preserve access controls before publishing a Linux/macOS file revision."""

from __future__ import annotations

import ctypes
import errno
import os
import stat
import sys
from functools import cache


@cache
def _darwin_library():
    library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    signatures = {
        "acl_get_fd_np": ([ctypes.c_int, ctypes.c_int], ctypes.c_void_p),
        "acl_init": ([ctypes.c_int], ctypes.c_void_p),
        "acl_set_fd_np": ([ctypes.c_int, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
        "acl_free": ([ctypes.c_void_p], ctypes.c_int),
        "fcopyfile": ([ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(library, name)
        function.argtypes = arguments
        function.restype = result
    return library


def _darwin_error() -> OSError:
    code = ctypes.get_errno() or errno.EIO
    return OSError(code, os.strerror(code))


def _copy_darwin_metadata(source: int, destination: int) -> None:
    library = _darwin_library()
    acl_type_extended = 0x100
    acl = library.acl_get_fd_np(source, acl_type_extended)
    if not acl:
        if ctypes.get_errno() != errno.ENOENT:
            raise _darwin_error()
        # An empty source ACL must remove any grants inherited by staging.
        acl = library.acl_init(0)
        if not acl:
            raise _darwin_error()
    try:
        if library.acl_set_fd_np(destination, acl, acl_type_extended) != 0:
            raise _darwin_error()
    finally:
        library.acl_free(acl)
    # COPYFILE_XATTR only: do not copy old data or restore its modification time.
    if library.fcopyfile(source, destination, None, 1 << 2) != 0:
        raise _darwin_error()


def _copy_linux_metadata(source: int, destination: int) -> None:
    try:
        names = os.listxattr(source)
    except OSError as error:
        if error.errno == errno.ENOTSUP:
            return  # Both files are on the same filesystem, without xattrs.
        raise
    if {"security.capability", "security.ima", "security.evm"}.intersection(names):
        raise OSError(errno.ENOTSUP, "Cannot safely transfer content-bound file privileges")
    for name in os.listxattr(destination):
        if name not in names:
            os.removexattr(destination, name)
    for name in names:
        os.setxattr(destination, name, os.getxattr(source, name))


def preserve_revision_metadata(source: int, destination: int) -> None:
    """Copy metadata using open descriptors, or abort without publishing.

    Unlike shutil.copystat, errors copying ownership, ACLs and attributes are
    not suppressed. Privileged/flagged files require an explicit editing policy.
    Call before writing content so inherited staging grants cannot expose it.
    """
    before = os.fstat(source)
    if before.st_mode & (stat.S_ISUID | stat.S_ISGID) or getattr(before, "st_flags", 0):
        raise OSError(errno.ENOTSUP, "Atomic text revisions do not support privileged or flagged files")
    temporary = os.fstat(destination)
    if temporary.st_dev != before.st_dev:
        raise OSError(errno.EXDEV, "Atomic text revisions require the same filesystem")
    if (temporary.st_uid, temporary.st_gid) != (before.st_uid, before.st_gid):
        os.fchown(destination, before.st_uid, before.st_gid)
    os.fchmod(destination, stat.S_IMODE(before.st_mode))
    if sys.platform == "darwin":
        _copy_darwin_metadata(source, destination)
    elif sys.platform == "linux":
        _copy_linux_metadata(source, destination)
    else:
        raise OSError(errno.ENOTSUP, "File revision metadata is supported on Linux and macOS only")
