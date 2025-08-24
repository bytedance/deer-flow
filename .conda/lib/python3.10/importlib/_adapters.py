from contextlib import suppress

from . import abc


class SpecLoaderAdapter:
    """
    Adapt a package spec to adapt the underlying loader.
    """

    def __init__(self, spec, adapter=lambda spec: spec.loader):
        self.spec = spec
        self.loader = adapter(spec)

    def __getattr__(self, name):
        return getattr(self.spec, name)


class TraversableResourcesLoader:
    """
    Adapt a loader to provide TraversableResources.
    """

    def __init__(self, spec):
        self.spec = spec

    def get_resource_reader(self, name):
        return DegenerateFiles(self.spec)._native()


class DegenerateFiles:
    """
    Adapter for an existing or non-existant resource reader
    to provide a degenerate .files().
    """

    class Path(abc.Traversable):
        def iterdir(self):
            return iter(())

        def is_dir(self):
            return False

        is_file = exists = is_dir  # type: ignore

        def joinpath(self, other):
            return DegenerateFiles.Path()

        @property
        def name(self):
            return ''

        def open(self, mode='rb', *args, **kwargs):
            raise ValueError()

    def __init__(self, spec):
        self.spec = spec

    @property
    def _reader(self):
        with suppress(AttributeError):
            return self.spec.loader.get_resource_reader(self.spec.name)

    def _native(self):
        """
        Return the native reader if it supports files().
        """
        reader = self._reader
        return reader if hasattr(reader, 'files') else self

    def __getattr__(self, attr):
        return getattr(self._reader, attr)

    def files(self):
        return DegenerateFiles.Path()


def wrap_spec(package):
    """
    Construct a package spec with traversable compatibility
    on the spec/loader/reader.
    """
    return SpecLoaderAdapter(package.__spec__, TraversableResourcesLoader)
