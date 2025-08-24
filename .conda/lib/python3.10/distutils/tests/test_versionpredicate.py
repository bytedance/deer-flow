"""Tests harness for distutils.versionpredicate.

"""

import distutils.versionpredicate
import doctest
from test.support import run_unittest

def test_suite():
    return doctest.DocTestSuite(distutils.versionpredicate)

if __name__ == '__main__':
    run_unittest(test_suite())
