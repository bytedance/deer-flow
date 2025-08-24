"""Tests for distutils.log"""

import io
import sys
import unittest
from test.support import swap_attr, run_unittest

from distutils import log

class TestLog(unittest.TestCase):
    def test_non_ascii(self):
        # Issues #8663, #34421: test that non-encodable text is escaped with
        # backslashreplace error handler and encodable non-ASCII text is
        # output as is.
        for errors in ('strict', 'backslashreplace', 'surrogateescape',
                       'replace', 'ignore'):
            with self.subTest(errors=errors):
                stdout = io.TextIOWrapper(io.BytesIO(),
                                          encoding='cp437', errors=errors)
                stderr = io.TextIOWrapper(io.BytesIO(),
                                          encoding='cp437', errors=errors)
                old_threshold = log.set_threshold(log.DEBUG)
                try:
                    with swap_attr(sys, 'stdout', stdout), \
                         swap_attr(sys, 'stderr', stderr):
                        log.debug('Dεbug\tMėssãge')
                        log.fatal('Fαtal\tÈrrōr')
                finally:
                    log.set_threshold(old_threshold)

                stdout.seek(0)
                self.assertEqual(stdout.read().rstrip(),
                        'Dεbug\tM?ss?ge' if errors == 'replace' else
                        'Dεbug\tMssge' if errors == 'ignore' else
                        'Dεbug\tM\\u0117ss\\xe3ge')
                stderr.seek(0)
                self.assertEqual(stderr.read().rstrip(),
                        'Fαtal\t?rr?r' if errors == 'replace' else
                        'Fαtal\trrr' if errors == 'ignore' else
                        'Fαtal\t\\xc8rr\\u014dr')

def test_suite():
    return unittest.makeSuite(TestLog)

if __name__ == "__main__":
    run_unittest(test_suite())
