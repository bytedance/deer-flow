import contextlib
import functools
import re
import sys
import warnings


def check_syntax_warning(testcase, statement, errtext='',
                         *, lineno=1, offset=None):
    # Test also that a warning is emitted only once.
    from test.support import check_syntax_error
    with warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter('always', SyntaxWarning)
        compile(statement, '<testcase>', 'exec')
    testcase.assertEqual(len(warns), 1, warns)

    warn, = warns
    testcase.assertTrue(issubclass(warn.category, SyntaxWarning),
                        warn.category)
    if errtext:
        testcase.assertRegex(str(warn.message), errtext)
    testcase.assertEqual(warn.filename, '<testcase>')
    testcase.assertIsNotNone(warn.lineno)
    if lineno is not None:
        testcase.assertEqual(warn.lineno, lineno)

    # SyntaxWarning should be converted to SyntaxError when raised,
    # since the latter contains more information and provides better
    # error report.
    with warnings.catch_warnings(record=True) as warns:
        warnings.simplefilter('error', SyntaxWarning)
        check_syntax_error(testcase, statement, errtext,
                           lineno=lineno, offset=offset)
    # No warnings are leaked when a SyntaxError is raised.
    testcase.assertEqual(warns, [])


def ignore_warnings(*, category):
    """Decorator to suppress warnings.

    Use of context managers to hide warnings make diffs
    more noisy and tools like 'git blame' less useful.
    """
    def decorator(test):
        @functools.wraps(test)
        def wrapper(self, *args, **kwargs):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', category=category)
                return test(self, *args, **kwargs)
        return wrapper
    return decorator


class WarningsRecorder(object):
    """Convenience wrapper for the warnings list returned on
       entry to the warnings.catch_warnings() context manager.
    """
    def __init__(self, warnings_list):
        self._warnings = warnings_list
        self._last = 0

    def __getattr__(self, attr):
        if len(self._warnings) > self._last:
            return getattr(self._warnings[-1], attr)
        elif attr in warnings.WarningMessage._WARNING_DETAILS:
            return None
        raise AttributeError("%r has no attribute %r" % (self, attr))

    @property
    def warnings(self):
        return self._warnings[self._last:]

    def reset(self):
        self._last = len(self._warnings)


@contextlib.contextmanager
def check_warnings(*filters, **kwargs):
    """Context manager to silence warnings.

    Accept 2-tuples as positional arguments:
        ("message regexp", WarningCategory)

    Optional argument:
     - if 'quiet' is True, it does not fail if a filter catches nothing
        (default True without argument,
         default False if some filters are defined)

    Without argument, it defaults to:
        check_warnings(("", Warning), quiet=True)
    """
    quiet = kwargs.get('quiet')
    if not filters:
        filters = (("", Warning),)
        # Preserve backward compatibility
        if quiet is None:
            quiet = True
    return _filterwarnings(filters, quiet)


@contextlib.contextmanager
def check_no_warnings(testcase, message='', category=Warning, force_gc=False):
    """Context manager to check that no warnings are emitted.

    This context manager enables a given warning within its scope
    and checks that no warnings are emitted even with that warning
    enabled.

    If force_gc is True, a garbage collection is attempted before checking
    for warnings. This may help to catch warnings emitted when objects
    are deleted, such as ResourceWarning.

    Other keyword arguments are passed to warnings.filterwarnings().
    """
    from test.support import gc_collect
    with warnings.catch_warnings(record=True) as warns:
        warnings.filterwarnings('always',
                                message=message,
                                category=category)
        yield
        if force_gc:
            gc_collect()
    testcase.assertEqual(warns, [])


@contextlib.contextmanager
def check_no_resource_warning(testcase):
    """Context manager to check that no ResourceWarning is emitted.

    Usage:

        with check_no_resource_warning(self):
            f = open(...)
            ...
            del f

    You must remove the object which may emit ResourceWarning before
    the end of the context manager.
    """
    with check_no_warnings(testcase, category=ResourceWarning, force_gc=True):
        yield


def _filterwarnings(filters, quiet=False):
    """Catch the warnings, then check if all the expected
    warnings have been raised and re-raise unexpected warnings.
    If 'quiet' is True, only re-raise the unexpected warnings.
    """
    # Clear the warning registry of the calling module
    # in order to re-raise the warnings.
    frame = sys._getframe(2)
    registry = frame.f_globals.get('__warningregistry__')
    if registry:
        registry.clear()
    with warnings.catch_warnings(record=True) as w:
        # Set filter "always" to record all warnings.  Because
        # test_warnings swap the module, we need to look up in
        # the sys.modules dictionary.
        sys.modules['warnings'].simplefilter("always")
        yield WarningsRecorder(w)
    # Filter the recorded warnings
    reraise = list(w)
    missing = []
    for msg, cat in filters:
        seen = False
        for w in reraise[:]:
            warning = w.message
            # Filter out the matching messages
            if (re.match(msg, str(warning), re.I) and
                issubclass(warning.__class__, cat)):
                seen = True
                reraise.remove(w)
        if not seen and not quiet:
            # This filter caught nothing
            missing.append((msg, cat.__name__))
    if reraise:
        raise AssertionError("unhandled warning %s" % reraise[0])
    if missing:
        raise AssertionError("filter (%r, %s) did not catch any warning" %
                             missing[0])


@contextlib.contextmanager
def save_restore_warnings_filters():
    old_filters = warnings.filters[:]
    try:
        yield
    finally:
        warnings.filters[:] = old_filters


def _warn_about_deprecation():
    warnings.warn(
        "This is used in test_support test to ensure"
        " support.ignore_deprecations_from() works as expected."
        " You should not be seeing this.",
        DeprecationWarning,
        stacklevel=0,
    )
