"""Test suite for distutils.

This test suite consists of a collection of test modules in the
distutils.tests package.  Each test module has a name starting with
'test' and contains a function test_suite().  The function is expected
to return an initialized unittest.TestSuite instance.

Tests for the command classes in the distutils.command package are
included in distutils.tests as well, instead of using a separate
distutils.command.tests package, since command identification is done
by import rather than matching pre-defined names.

"""

import os
import sys
import unittest
from test.support import run_unittest
from test.support.warnings_helper import save_restore_warnings_filters


here = os.path.dirname(__file__) or os.curdir


def test_suite():
    suite = unittest.TestSuite()
    for fn in os.listdir(here):
        if fn.startswith("test") and fn.endswith(".py"):
            modname = "distutils.tests." + fn[:-3]
            # bpo-40055: Save/restore warnings filters to leave them unchanged.
            # Importing tests imports docutils which imports pkg_resources
            # which adds a warnings filter.
            with save_restore_warnings_filters():
                __import__(modname)
            module = sys.modules[modname]
            suite.addTest(module.test_suite())
    return suite


if __name__ == "__main__":
    run_unittest(test_suite())
