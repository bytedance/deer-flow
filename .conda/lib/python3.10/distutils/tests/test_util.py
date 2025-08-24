"""Tests for distutils.util."""
import os
import sys
import unittest
from copy import copy
from test.support import run_unittest
from unittest import mock

from distutils.errors import DistutilsPlatformError, DistutilsByteCompileError
from distutils.util import (get_platform, convert_path, change_root,
                            check_environ, split_quoted, strtobool,
                            rfc822_escape, byte_compile,
                            grok_environment_error)
from distutils import util # used to patch _environ_checked
from distutils.sysconfig import get_config_vars
from distutils import sysconfig
from distutils.tests import support
import _osx_support

class UtilTestCase(support.EnvironGuard, unittest.TestCase):

    def setUp(self):
        super(UtilTestCase, self).setUp()
        # saving the environment
        self.name = os.name
        self.platform = sys.platform
        self.version = sys.version
        self.sep = os.sep
        self.join = os.path.join
        self.isabs = os.path.isabs
        self.splitdrive = os.path.splitdrive
        self._config_vars = copy(sysconfig._config_vars)

        # patching os.uname
        if hasattr(os, 'uname'):
            self.uname = os.uname
            self._uname = os.uname()
        else:
            self.uname = None
            self._uname = None

        os.uname = self._get_uname

    def tearDown(self):
        # getting back the environment
        os.name = self.name
        sys.platform = self.platform
        sys.version = self.version
        os.sep = self.sep
        os.path.join = self.join
        os.path.isabs = self.isabs
        os.path.splitdrive = self.splitdrive
        if self.uname is not None:
            os.uname = self.uname
        else:
            del os.uname
        sysconfig._config_vars.clear()
        sysconfig._config_vars.update(self._config_vars)
        super(UtilTestCase, self).tearDown()

    def _set_uname(self, uname):
        self._uname = uname

    def _get_uname(self):
        return self._uname

    def test_get_platform(self):

        # windows XP, 32bits
        os.name = 'nt'
        sys.version = ('2.4.4 (#71, Oct 18 2006, 08:34:43) '
                       '[MSC v.1310 32 bit (Intel)]')
        sys.platform = 'win32'
        self.assertEqual(get_platform(), 'win32')

        # windows XP, amd64
        os.name = 'nt'
        sys.version = ('2.4.4 (#71, Oct 18 2006, 08:34:43) '
                       '[MSC v.1310 32 bit (Amd64)]')
        sys.platform = 'win32'
        self.assertEqual(get_platform(), 'win-amd64')

        # macbook
        os.name = 'posix'
        sys.version = ('2.5 (r25:51918, Sep 19 2006, 08:49:13) '
                       '\n[GCC 4.0.1 (Apple Computer, Inc. build 5341)]')
        sys.platform = 'darwin'
        self._set_uname(('Darwin', 'macziade', '8.11.1',
                   ('Darwin Kernel Version 8.11.1: '
                    'Wed Oct 10 18:23:28 PDT 2007; '
                    'root:xnu-792.25.20~1/RELEASE_I386'), 'i386'))
        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['MACOSX_DEPLOYMENT_TARGET'] = '10.3'

        get_config_vars()['CFLAGS'] = ('-fno-strict-aliasing -DNDEBUG -g '
                                       '-fwrapv -O3 -Wall -Wstrict-prototypes')

        cursize = sys.maxsize
        sys.maxsize = (2 ** 31)-1
        try:
            self.assertEqual(get_platform(), 'macosx-10.3-i386')
        finally:
            sys.maxsize = cursize

        # macbook with fat binaries (fat, universal or fat64)
        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['MACOSX_DEPLOYMENT_TARGET'] = '10.4'
        get_config_vars()['CFLAGS'] = ('-arch ppc -arch i386 -isysroot '
                                       '/Developer/SDKs/MacOSX10.4u.sdk  '
                                       '-fno-strict-aliasing -fno-common '
                                       '-dynamic -DNDEBUG -g -O3')

        self.assertEqual(get_platform(), 'macosx-10.4-fat')

        _osx_support._remove_original_values(get_config_vars())
        os.environ['MACOSX_DEPLOYMENT_TARGET'] = '10.1'
        self.assertEqual(get_platform(), 'macosx-10.4-fat')


        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['CFLAGS'] = ('-arch x86_64 -arch i386 -isysroot '
                                       '/Developer/SDKs/MacOSX10.4u.sdk  '
                                       '-fno-strict-aliasing -fno-common '
                                       '-dynamic -DNDEBUG -g -O3')

        self.assertEqual(get_platform(), 'macosx-10.4-intel')

        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['CFLAGS'] = ('-arch x86_64 -arch ppc -arch i386 -isysroot '
                                       '/Developer/SDKs/MacOSX10.4u.sdk  '
                                       '-fno-strict-aliasing -fno-common '
                                       '-dynamic -DNDEBUG -g -O3')
        self.assertEqual(get_platform(), 'macosx-10.4-fat3')

        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['CFLAGS'] = ('-arch ppc64 -arch x86_64 -arch ppc -arch i386 -isysroot '
                                       '/Developer/SDKs/MacOSX10.4u.sdk  '
                                       '-fno-strict-aliasing -fno-common '
                                       '-dynamic -DNDEBUG -g -O3')
        self.assertEqual(get_platform(), 'macosx-10.4-universal')

        _osx_support._remove_original_values(get_config_vars())
        get_config_vars()['CFLAGS'] = ('-arch x86_64 -arch ppc64 -isysroot '
                                       '/Developer/SDKs/MacOSX10.4u.sdk  '
                                       '-fno-strict-aliasing -fno-common '
                                       '-dynamic -DNDEBUG -g -O3')

        self.assertEqual(get_platform(), 'macosx-10.4-fat64')

        for arch in ('ppc', 'i386', 'x86_64', 'ppc64'):
            _osx_support._remove_original_values(get_config_vars())
            get_config_vars()['CFLAGS'] = ('-arch %s -isysroot '
                                           '/Developer/SDKs/MacOSX10.4u.sdk  '
                                           '-fno-strict-aliasing -fno-common '
                                           '-dynamic -DNDEBUG -g -O3'%(arch,))

            self.assertEqual(get_platform(), 'macosx-10.4-%s'%(arch,))


        # linux debian sarge
        os.name = 'posix'
        sys.version = ('2.3.5 (#1, Jul  4 2007, 17:28:59) '
                       '\n[GCC 4.1.2 20061115 (prerelease) (Debian 4.1.1-21)]')
        sys.platform = 'linux2'
        self._set_uname(('Linux', 'aglae', '2.6.21.1dedibox-r7',
                    '#1 Mon Apr 30 17:25:38 CEST 2007', 'i686'))

        self.assertEqual(get_platform(), 'linux-i686')

        # XXX more platforms to tests here

    def test_convert_path(self):
        # linux/mac
        os.sep = '/'
        def _join(path):
            return '/'.join(path)
        os.path.join = _join

        self.assertEqual(convert_path('/home/to/my/stuff'),
                         '/home/to/my/stuff')

        # win
        os.sep = '\\'
        def _join(*path):
            return '\\'.join(path)
        os.path.join = _join

        self.assertRaises(ValueError, convert_path, '/home/to/my/stuff')
        self.assertRaises(ValueError, convert_path, 'home/to/my/stuff/')

        self.assertEqual(convert_path('home/to/my/stuff'),
                         'home\\to\\my\\stuff')
        self.assertEqual(convert_path('.'),
                         os.curdir)

    def test_change_root(self):
        # linux/mac
        os.name = 'posix'
        def _isabs(path):
            return path[0] == '/'
        os.path.isabs = _isabs
        def _join(*path):
            return '/'.join(path)
        os.path.join = _join

        self.assertEqual(change_root('/root', '/old/its/here'),
                         '/root/old/its/here')
        self.assertEqual(change_root('/root', 'its/here'),
                         '/root/its/here')

        # windows
        os.name = 'nt'
        def _isabs(path):
            return path.startswith('c:\\')
        os.path.isabs = _isabs
        def _splitdrive(path):
            if path.startswith('c:'):
                return ('', path.replace('c:', ''))
            return ('', path)
        os.path.splitdrive = _splitdrive
        def _join(*path):
            return '\\'.join(path)
        os.path.join = _join

        self.assertEqual(change_root('c:\\root', 'c:\\old\\its\\here'),
                         'c:\\root\\old\\its\\here')
        self.assertEqual(change_root('c:\\root', 'its\\here'),
                         'c:\\root\\its\\here')

        # BugsBunny os (it's a great os)
        os.name = 'BugsBunny'
        self.assertRaises(DistutilsPlatformError,
                          change_root, 'c:\\root', 'its\\here')

        # XXX platforms to be covered: mac

    def test_check_environ(self):
        util._environ_checked = 0
        os.environ.pop('HOME', None)

        check_environ()

        self.assertEqual(os.environ['PLAT'], get_platform())
        self.assertEqual(util._environ_checked, 1)

    @unittest.skipUnless(os.name == 'posix', 'specific to posix')
    def test_check_environ_getpwuid(self):
        util._environ_checked = 0
        os.environ.pop('HOME', None)

        import pwd

        # only set pw_dir field, other fields are not used
        result = pwd.struct_passwd((None, None, None, None, None,
                                    '/home/distutils', None))
        with mock.patch.object(pwd, 'getpwuid', return_value=result):
            check_environ()
            self.assertEqual(os.environ['HOME'], '/home/distutils')

        util._environ_checked = 0
        os.environ.pop('HOME', None)

        # bpo-10496: Catch pwd.getpwuid() error
        with mock.patch.object(pwd, 'getpwuid', side_effect=KeyError):
            check_environ()
            self.assertNotIn('HOME', os.environ)

    def test_split_quoted(self):
        self.assertEqual(split_quoted('""one"" "two" \'three\' \\four'),
                         ['one', 'two', 'three', 'four'])

    def test_strtobool(self):
        yes = ('y', 'Y', 'yes', 'True', 't', 'true', 'True', 'On', 'on', '1')
        no = ('n', 'no', 'f', 'false', 'off', '0', 'Off', 'No', 'N')

        for y in yes:
            self.assertTrue(strtobool(y))

        for n in no:
            self.assertFalse(strtobool(n))

    def test_rfc822_escape(self):
        header = 'I am a\npoor\nlonesome\nheader\n'
        res = rfc822_escape(header)
        wanted = ('I am a%(8s)spoor%(8s)slonesome%(8s)s'
                  'header%(8s)s') % {'8s': '\n'+8*' '}
        self.assertEqual(res, wanted)

    def test_dont_write_bytecode(self):
        # makes sure byte_compile raise a DistutilsError
        # if sys.dont_write_bytecode is True
        old_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            self.assertRaises(DistutilsByteCompileError, byte_compile, [])
        finally:
            sys.dont_write_bytecode = old_dont_write_bytecode

    def test_grok_environment_error(self):
        # test obsolete function to ensure backward compat (#4931)
        exc = IOError("Unable to find batch file")
        msg = grok_environment_error(exc)
        self.assertEqual(msg, "error: Unable to find batch file")


def test_suite():
    return unittest.makeSuite(UtilTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
