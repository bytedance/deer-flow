import contextlib
import importlib
import importlib.util
import os
import shutil
import sys
import unittest
import warnings

from .os_helper import unlink


@contextlib.contextmanager
def _ignore_deprecated_imports(ignore=True):
    """Context manager to suppress package and module deprecation
    warnings when importing them.

    If ignore is False, this context manager has no effect.
    """
    if ignore:
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", ".+ (module|package)",
                                    DeprecationWarning)
            yield
    else:
        yield


def unload(name):
    try:
        del sys.modules[name]
    except KeyError:
        pass


def forget(modname):
    """'Forget' a module was ever imported.

    This removes the module from sys.modules and deletes any PEP 3147/488 or
    legacy .pyc files.
    """
    unload(modname)
    for dirname in sys.path:
        source = os.path.join(dirname, modname + '.py')
        # It doesn't matter if they exist or not, unlink all possible
        # combinations of PEP 3147/488 and legacy pyc files.
        unlink(source + 'c')
        for opt in ('', 1, 2):
            unlink(importlib.util.cache_from_source(source, optimization=opt))


def make_legacy_pyc(source):
    """Move a PEP 3147/488 pyc file to its legacy pyc location.

    :param source: The file system path to the source file.  The source file
        does not need to exist, however the PEP 3147/488 pyc file must exist.
    :return: The file system path to the legacy pyc file.
    """
    pyc_file = importlib.util.cache_from_source(source)
    up_one = os.path.dirname(os.path.abspath(source))
    legacy_pyc = os.path.join(up_one, source + 'c')
    shutil.move(pyc_file, legacy_pyc)
    return legacy_pyc


def import_module(name, deprecated=False, *, required_on=()):
    """Import and return the module to be tested, raising SkipTest if
    it is not available.

    If deprecated is True, any module or package deprecation messages
    will be suppressed. If a module is required on a platform but optional for
    others, set required_on to an iterable of platform prefixes which will be
    compared against sys.platform.
    """
    with _ignore_deprecated_imports(deprecated):
        try:
            return importlib.import_module(name)
        except ImportError as msg:
            if sys.platform.startswith(tuple(required_on)):
                raise
            raise unittest.SkipTest(str(msg))


def _save_and_remove_modules(names):
    orig_modules = {}
    prefixes = tuple(name + '.' for name in names)
    for modname in list(sys.modules):
        if modname in names or modname.startswith(prefixes):
            orig_modules[modname] = sys.modules.pop(modname)
    return orig_modules


def import_fresh_module(name, fresh=(), blocked=(), deprecated=False):
    """Import and return a module, deliberately bypassing sys.modules.

    This function imports and returns a fresh copy of the named Python module
    by removing the named module from sys.modules before doing the import.
    Note that unlike reload, the original module is not affected by
    this operation.

    *fresh* is an iterable of additional module names that are also removed
    from the sys.modules cache before doing the import. If one of these
    modules can't be imported, None is returned.

    *blocked* is an iterable of module names that are replaced with None
    in the module cache during the import to ensure that attempts to import
    them raise ImportError.

    The named module and any modules named in the *fresh* and *blocked*
    parameters are saved before starting the import and then reinserted into
    sys.modules when the fresh import is complete.

    Module and package deprecation messages are suppressed during this import
    if *deprecated* is True.

    This function will raise ImportError if the named module cannot be
    imported.
    """
    # NOTE: test_heapq, test_json and test_warnings include extra sanity checks
    # to make sure that this utility function is working as expected
    with _ignore_deprecated_imports(deprecated):
        # Keep track of modules saved for later restoration as well
        # as those which just need a blocking entry removed
        fresh = list(fresh)
        blocked = list(blocked)
        names = {name, *fresh, *blocked}
        orig_modules = _save_and_remove_modules(names)
        for modname in blocked:
            sys.modules[modname] = None

        try:
            # Return None when one of the "fresh" modules can not be imported.
            try:
                for modname in fresh:
                    __import__(modname)
            except ImportError:
                return None
            return importlib.import_module(name)
        finally:
            _save_and_remove_modules(names)
            sys.modules.update(orig_modules)


class CleanImport(object):
    """Context manager to force import to return a new module reference.

    This is useful for testing module-level behaviours, such as
    the emission of a DeprecationWarning on import.

    Use like this:

        with CleanImport("foo"):
            importlib.import_module("foo") # new reference
    """

    def __init__(self, *module_names):
        self.original_modules = sys.modules.copy()
        for module_name in module_names:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                # It is possible that module_name is just an alias for
                # another module (e.g. stub for modules renamed in 3.x).
                # In that case, we also need delete the real module to clear
                # the import cache.
                if module.__name__ != module_name:
                    del sys.modules[module.__name__]
                del sys.modules[module_name]

    def __enter__(self):
        return self

    def __exit__(self, *ignore_exc):
        sys.modules.update(self.original_modules)


class DirsOnSysPath(object):
    """Context manager to temporarily add directories to sys.path.

    This makes a copy of sys.path, appends any directories given
    as positional arguments, then reverts sys.path to the copied
    settings when the context ends.

    Note that *all* sys.path modifications in the body of the
    context manager, including replacement of the object,
    will be reverted at the end of the block.
    """

    def __init__(self, *paths):
        self.original_value = sys.path[:]
        self.original_object = sys.path
        sys.path.extend(paths)

    def __enter__(self):
        return self

    def __exit__(self, *ignore_exc):
        sys.path = self.original_object
        sys.path[:] = self.original_value


def modules_setup():
    return sys.modules.copy(),


def modules_cleanup(oldmodules):
    # Encoders/decoders are registered permanently within the internal
    # codec cache. If we destroy the corresponding modules their
    # globals will be set to None which will trip up the cached functions.
    encodings = [(k, v) for k, v in sys.modules.items()
                 if k.startswith('encodings.')]
    sys.modules.clear()
    sys.modules.update(encodings)
    # XXX: This kind of problem can affect more than just encodings.
    # In particular extension modules (such as _ssl) don't cope
    # with reloading properly. Really, test modules should be cleaning
    # out the test specific modules they know they added (ala test_runpy)
    # rather than relying on this function (as test_importhooks and test_pkg
    # do currently). Implicitly imported *real* modules should be left alone
    # (see issue 10556).
    sys.modules.update(oldmodules)
