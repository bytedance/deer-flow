"""Tests for distutils.cygwinccompiler."""
import unittest
import sys
import os
from io import BytesIO
from test.support import run_unittest

from distutils import cygwinccompiler
from distutils.cygwinccompiler import (check_config_h,
                                       CONFIG_H_OK, CONFIG_H_NOTOK,
                                       CONFIG_H_UNCERTAIN, get_versions,
                                       get_msvcr)
from distutils.tests import support

class FakePopen(object):
    test_class = None

    def __init__(self, cmd, shell, stdout):
        self.cmd = cmd.split()[0]
        exes = self.test_class._exes
        if self.cmd in exes:
            # issue #6438 in Python 3.x, Popen returns bytes
            self.stdout = BytesIO(exes[self.cmd])
        else:
            self.stdout = os.popen(cmd, 'r')


class CygwinCCompilerTestCase(support.TempdirManager,
                              unittest.TestCase):

    def setUp(self):
        super(CygwinCCompilerTestCase, self).setUp()
        self.version = sys.version
        self.python_h = os.path.join(self.mkdtemp(), 'python.h')
        from distutils import sysconfig
        self.old_get_config_h_filename = sysconfig.get_config_h_filename
        sysconfig.get_config_h_filename = self._get_config_h_filename
        self.old_find_executable = cygwinccompiler.find_executable
        cygwinccompiler.find_executable = self._find_executable
        self._exes = {}
        self.old_popen = cygwinccompiler.Popen
        FakePopen.test_class = self
        cygwinccompiler.Popen = FakePopen

    def tearDown(self):
        sys.version = self.version
        from distutils import sysconfig
        sysconfig.get_config_h_filename = self.old_get_config_h_filename
        cygwinccompiler.find_executable = self.old_find_executable
        cygwinccompiler.Popen = self.old_popen
        super(CygwinCCompilerTestCase, self).tearDown()

    def _get_config_h_filename(self):
        return self.python_h

    def _find_executable(self, name):
        if name in self._exes:
            return name
        return None

    def test_check_config_h(self):

        # check_config_h looks for "GCC" in sys.version first
        # returns CONFIG_H_OK if found
        sys.version = ('2.6.1 (r261:67515, Dec  6 2008, 16:42:21) \n[GCC '
                       '4.0.1 (Apple Computer, Inc. build 5370)]')

        self.assertEqual(check_config_h()[0], CONFIG_H_OK)

        # then it tries to see if it can find "__GNUC__" in pyconfig.h
        sys.version = 'something without the *CC word'

        # if the file doesn't exist it returns  CONFIG_H_UNCERTAIN
        self.assertEqual(check_config_h()[0], CONFIG_H_UNCERTAIN)

        # if it exists but does not contain __GNUC__, it returns CONFIG_H_NOTOK
        self.write_file(self.python_h, 'xxx')
        self.assertEqual(check_config_h()[0], CONFIG_H_NOTOK)

        # and CONFIG_H_OK if __GNUC__ is found
        self.write_file(self.python_h, 'xxx __GNUC__ xxx')
        self.assertEqual(check_config_h()[0], CONFIG_H_OK)

    def test_get_versions(self):

        # get_versions calls distutils.spawn.find_executable on
        # 'gcc', 'ld' and 'dllwrap'
        self.assertEqual(get_versions(), (None, None, None))

        # Let's fake we have 'gcc' and it returns '3.4.5'
        self._exes['gcc'] = b'gcc (GCC) 3.4.5 (mingw special)\nFSF'
        res = get_versions()
        self.assertEqual(str(res[0]), '3.4.5')

        # and let's see what happens when the version
        # doesn't match the regular expression
        # (\d+\.\d+(\.\d+)*)
        self._exes['gcc'] = b'very strange output'
        res = get_versions()
        self.assertEqual(res[0], None)

        # same thing for ld
        self._exes['ld'] = b'GNU ld version 2.17.50 20060824'
        res = get_versions()
        self.assertEqual(str(res[1]), '2.17.50')
        self._exes['ld'] = b'@(#)PROGRAM:ld  PROJECT:ld64-77'
        res = get_versions()
        self.assertEqual(res[1], None)

        # and dllwrap
        self._exes['dllwrap'] = b'GNU dllwrap 2.17.50 20060824\nFSF'
        res = get_versions()
        self.assertEqual(str(res[2]), '2.17.50')
        self._exes['dllwrap'] = b'Cheese Wrap'
        res = get_versions()
        self.assertEqual(res[2], None)

    def test_get_msvcr(self):

        # none
        sys.version  = ('2.6.1 (r261:67515, Dec  6 2008, 16:42:21) '
                        '\n[GCC 4.0.1 (Apple Computer, Inc. build 5370)]')
        self.assertEqual(get_msvcr(), None)

        # MSVC 7.0
        sys.version = ('2.5.1 (r251:54863, Apr 18 2007, 08:51:08) '
                       '[MSC v.1300 32 bits (Intel)]')
        self.assertEqual(get_msvcr(), ['msvcr70'])

        # MSVC 7.1
        sys.version = ('2.5.1 (r251:54863, Apr 18 2007, 08:51:08) '
                       '[MSC v.1310 32 bits (Intel)]')
        self.assertEqual(get_msvcr(), ['msvcr71'])

        # VS2005 / MSVC 8.0
        sys.version = ('2.5.1 (r251:54863, Apr 18 2007, 08:51:08) '
                       '[MSC v.1400 32 bits (Intel)]')
        self.assertEqual(get_msvcr(), ['msvcr80'])

        # VS2008 / MSVC 9.0
        sys.version = ('2.5.1 (r251:54863, Apr 18 2007, 08:51:08) '
                       '[MSC v.1500 32 bits (Intel)]')
        self.assertEqual(get_msvcr(), ['msvcr90'])

        # unknown
        sys.version = ('2.5.1 (r251:54863, Apr 18 2007, 08:51:08) '
                       '[MSC v.1999 32 bits (Intel)]')
        self.assertRaises(ValueError, get_msvcr)

def test_suite():
    return unittest.makeSuite(CygwinCCompilerTestCase)

if __name__ == '__main__':
    run_unittest(test_suite())
