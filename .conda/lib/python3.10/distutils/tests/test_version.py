"""Tests for distutils.version."""
import unittest
from distutils.version import LooseVersion
from distutils.version import StrictVersion
from test.support import run_unittest

class VersionTestCase(unittest.TestCase):

    def test_prerelease(self):
        version = StrictVersion('1.2.3a1')
        self.assertEqual(version.version, (1, 2, 3))
        self.assertEqual(version.prerelease, ('a', 1))
        self.assertEqual(str(version), '1.2.3a1')

        version = StrictVersion('1.2.0')
        self.assertEqual(str(version), '1.2')

    def test_cmp_strict(self):
        versions = (('1.5.1', '1.5.2b2', -1),
                    ('161', '3.10a', ValueError),
                    ('8.02', '8.02', 0),
                    ('3.4j', '1996.07.12', ValueError),
                    ('3.2.pl0', '3.1.1.6', ValueError),
                    ('2g6', '11g', ValueError),
                    ('0.9', '2.2', -1),
                    ('1.2.1', '1.2', 1),
                    ('1.1', '1.2.2', -1),
                    ('1.2', '1.1', 1),
                    ('1.2.1', '1.2.2', -1),
                    ('1.2.2', '1.2', 1),
                    ('1.2', '1.2.2', -1),
                    ('0.4.0', '0.4', 0),
                    ('1.13++', '5.5.kw', ValueError))

        for v1, v2, wanted in versions:
            try:
                res = StrictVersion(v1)._cmp(StrictVersion(v2))
            except ValueError:
                if wanted is ValueError:
                    continue
                else:
                    raise AssertionError(("cmp(%s, %s) "
                                          "shouldn't raise ValueError")
                                            % (v1, v2))
            self.assertEqual(res, wanted,
                             'cmp(%s, %s) should be %s, got %s' %
                             (v1, v2, wanted, res))
            res = StrictVersion(v1)._cmp(v2)
            self.assertEqual(res, wanted,
                             'cmp(%s, %s) should be %s, got %s' %
                             (v1, v2, wanted, res))
            res = StrictVersion(v1)._cmp(object())
            self.assertIs(res, NotImplemented,
                          'cmp(%s, %s) should be NotImplemented, got %s' %
                          (v1, v2, res))


    def test_cmp(self):
        versions = (('1.5.1', '1.5.2b2', -1),
                    ('161', '3.10a', 1),
                    ('8.02', '8.02', 0),
                    ('3.4j', '1996.07.12', -1),
                    ('3.2.pl0', '3.1.1.6', 1),
                    ('2g6', '11g', -1),
                    ('0.960923', '2.2beta29', -1),
                    ('1.13++', '5.5.kw', -1))


        for v1, v2, wanted in versions:
            res = LooseVersion(v1)._cmp(LooseVersion(v2))
            self.assertEqual(res, wanted,
                             'cmp(%s, %s) should be %s, got %s' %
                             (v1, v2, wanted, res))
            res = LooseVersion(v1)._cmp(v2)
            self.assertEqual(res, wanted,
                             'cmp(%s, %s) should be %s, got %s' %
                             (v1, v2, wanted, res))
            res = LooseVersion(v1)._cmp(object())
            self.assertIs(res, NotImplemented,
                          'cmp(%s, %s) should be NotImplemented, got %s' %
                          (v1, v2, res))

def test_suite():
    return unittest.makeSuite(VersionTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
