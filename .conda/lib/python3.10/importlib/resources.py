import os
import io

from . import _common
from ._common import as_file, files
from .abc import ResourceReader
from contextlib import suppress
from importlib.abc import ResourceLoader
from importlib.machinery import ModuleSpec
from io import BytesIO, TextIOWrapper
from pathlib import Path
from types import ModuleType
from typing import ContextManager, Iterable, Union
from typing import cast
from typing.io import BinaryIO, TextIO
from collections.abc import Sequence
from functools import singledispatch


__all__ = [
    'Package',
    'Resource',
    'ResourceReader',
    'as_file',
    'contents',
    'files',
    'is_resource',
    'open_binary',
    'open_text',
    'path',
    'read_binary',
    'read_text',
]


Package = Union[str, ModuleType]
Resource = Union[str, os.PathLike]


def open_binary(package: Package, resource: Resource) -> BinaryIO:
    """Return a file-like object opened for binary reading of the resource."""
    resource = _common.normalize_path(resource)
    package = _common.get_package(package)
    reader = _common.get_resource_reader(package)
    if reader is not None:
        return reader.open_resource(resource)
    spec = cast(ModuleSpec, package.__spec__)
    # Using pathlib doesn't work well here due to the lack of 'strict'
    # argument for pathlib.Path.resolve() prior to Python 3.6.
    if spec.submodule_search_locations is not None:
        paths = spec.submodule_search_locations
    elif spec.origin is not None:
        paths = [os.path.dirname(os.path.abspath(spec.origin))]

    for package_path in paths:
        full_path = os.path.join(package_path, resource)
        try:
            return open(full_path, mode='rb')
        except OSError:
            # Just assume the loader is a resource loader; all the relevant
            # importlib.machinery loaders are and an AttributeError for
            # get_data() will make it clear what is needed from the loader.
            loader = cast(ResourceLoader, spec.loader)
            data = None
            if hasattr(spec.loader, 'get_data'):
                with suppress(OSError):
                    data = loader.get_data(full_path)
            if data is not None:
                return BytesIO(data)

    raise FileNotFoundError(f'{resource!r} resource not found in {spec.name!r}')


def open_text(
    package: Package,
    resource: Resource,
    encoding: str = 'utf-8',
    errors: str = 'strict',
) -> TextIO:
    """Return a file-like object opened for text reading of the resource."""
    return TextIOWrapper(
        open_binary(package, resource), encoding=encoding, errors=errors
    )


def read_binary(package: Package, resource: Resource) -> bytes:
    """Return the binary contents of the resource."""
    with open_binary(package, resource) as fp:
        return fp.read()


def read_text(
    package: Package,
    resource: Resource,
    encoding: str = 'utf-8',
    errors: str = 'strict',
) -> str:
    """Return the decoded string of the resource.

    The decoding-related arguments have the same semantics as those of
    bytes.decode().
    """
    with open_text(package, resource, encoding, errors) as fp:
        return fp.read()


def path(
    package: Package,
    resource: Resource,
) -> 'ContextManager[Path]':
    """A context manager providing a file path object to the resource.

    If the resource does not already exist on its own on the file system,
    a temporary file will be created. If the file was created, the file
    will be deleted upon exiting the context manager (no exception is
    raised if the file was deleted prior to the context manager
    exiting).
    """
    reader = _common.get_resource_reader(_common.get_package(package))
    return (
        _path_from_reader(reader, _common.normalize_path(resource))
        if reader
        else _common.as_file(
            _common.files(package).joinpath(_common.normalize_path(resource))
        )
    )


def _path_from_reader(reader, resource):
    return _path_from_resource_path(reader, resource) or _path_from_open_resource(
        reader, resource
    )


def _path_from_resource_path(reader, resource):
    with suppress(FileNotFoundError):
        return Path(reader.resource_path(resource))


def _path_from_open_resource(reader, resource):
    saved = io.BytesIO(reader.open_resource(resource).read())
    return _common._tempfile(saved.read, suffix=resource)


def is_resource(package: Package, name: str) -> bool:
    """True if 'name' is a resource inside 'package'.

    Directories are *not* resources.
    """
    package = _common.get_package(package)
    _common.normalize_path(name)
    reader = _common.get_resource_reader(package)
    if reader is not None:
        return reader.is_resource(name)
    package_contents = set(contents(package))
    if name not in package_contents:
        return False
    return (_common.from_package(package) / name).is_file()


def contents(package: Package) -> Iterable[str]:
    """Return an iterable of entries in 'package'.

    Note that not all entries are resources.  Specifically, directories are
    not considered resources.  Use `is_resource()` on each entry returned here
    to check if it is a resource or not.
    """
    package = _common.get_package(package)
    reader = _common.get_resource_reader(package)
    if reader is not None:
        return _ensure_sequence(reader.contents())
    transversable = _common.from_package(package)
    if transversable.is_dir():
        return list(item.name for item in transversable.iterdir())
    return []


@singledispatch
def _ensure_sequence(iterable):
    return list(iterable)


@_ensure_sequence.register(Sequence)
def _(iterable):
    return iterable
