"""Tests for distutils.sysconfig."""
import contextlib
import os
import shutil
import subprocess
import sys
import textwrap
import unittest

from distutils import sysconfig
from distutils.ccompiler import get_default_compiler
from distutils.tests import support
from test.support import run_unittest, swap_item
from test.support.os_helper import TESTFN
from test.support.warnings_helper import check_warnings


class SysconfigTestCase(support.EnvironGuard, unittest.TestCase):
    def setUp(self):
        super(SysconfigTestCase, self).setUp()
        self.makefile = None

    def tearDown(self):
        if self.makefile is not None:
            os.unlink(self.makefile)
        self.cleanup_testfn()
        super(SysconfigTestCase, self).tearDown()

    def cleanup_testfn(self):
        if os.path.isfile(TESTFN):
            os.remove(TESTFN)
        elif os.path.isdir(TESTFN):
            shutil.rmtree(TESTFN)

    def test_get_config_h_filename(self):
        config_h = sysconfig.get_config_h_filename()
        self.assertTrue(os.path.isfile(config_h), config_h)

    def test_get_python_lib(self):
        # XXX doesn't work on Linux when Python was never installed before
        #self.assertTrue(os.path.isdir(lib_dir), lib_dir)
        # test for pythonxx.lib?
        self.assertNotEqual(sysconfig.get_python_lib(),
                            sysconfig.get_python_lib(prefix=TESTFN))

    def test_get_config_vars(self):
        cvars = sysconfig.get_config_vars()
        self.assertIsInstance(cvars, dict)
        self.assertTrue(cvars)

    def test_srcdir(self):
        # See Issues #15322, #15364.
        srcdir = sysconfig.get_config_var('srcdir')

        self.assertTrue(os.path.isabs(srcdir), srcdir)
        self.assertTrue(os.path.isdir(srcdir), srcdir)

        if sysconfig.python_build:
            # The python executable has not been installed so srcdir
            # should be a full source checkout.
            Python_h = os.path.join(srcdir, 'Include', 'Python.h')
            self.assertTrue(os.path.exists(Python_h), Python_h)
            self.assertTrue(sysconfig._is_python_source_dir(srcdir))
        elif os.name == 'posix':
            self.assertEqual(
                os.path.dirname(sysconfig.get_makefile_filename()),
                srcdir)

    def test_srcdir_independent_of_cwd(self):
        # srcdir should be independent of the current working directory
        # See Issues #15322, #15364.
        srcdir = sysconfig.get_config_var('srcdir')
        cwd = os.getcwd()
        try:
            os.chdir('..')
            srcdir2 = sysconfig.get_config_var('srcdir')
        finally:
            os.chdir(cwd)
        self.assertEqual(srcdir, srcdir2)

    def customize_compiler(self):
        # make sure AR gets caught
        class compiler:
            compiler_type = 'unix'

            def set_executables(self, **kw):
                self.exes = kw

        sysconfig_vars = {
            'AR': 'sc_ar',
            'CC': 'sc_cc',
            'CXX': 'sc_cxx',
            'ARFLAGS': '--sc-arflags',
            'CFLAGS': '--sc-cflags',
            'CCSHARED': '--sc-ccshared',
            'LDSHARED': 'sc_ldshared',
            'SHLIB_SUFFIX': 'sc_shutil_suffix',

            # On macOS, disable _osx_support.customize_compiler()
            'CUSTOMIZED_OSX_COMPILER': 'True',
        }

        comp = compiler()
        with contextlib.ExitStack() as cm:
            for key, value in sysconfig_vars.items():
                cm.enter_context(swap_item(sysconfig._config_vars, key, value))
            sysconfig.customize_compiler(comp)

        return comp

    @unittest.skipUnless(get_default_compiler() == 'unix',
                         'not testing if default compiler is not unix')
    def test_customize_compiler(self):
        # Make sure that sysconfig._config_vars is initialized
        sysconfig.get_config_vars()

        os.environ['AR'] = 'env_ar'
        os.environ['CC'] = 'env_cc'
        os.environ['CPP'] = 'env_cpp'
        os.environ['CXX'] = 'env_cxx --env-cxx-flags'
        os.environ['LDSHARED'] = 'env_ldshared'
        os.environ['LDFLAGS'] = '--env-ldflags'
        os.environ['ARFLAGS'] = '--env-arflags'
        os.environ['CFLAGS'] = '--env-cflags'
        os.environ['CPPFLAGS'] = '--env-cppflags'

        comp = self.customize_compiler()
        self.assertEqual(comp.exes['archiver'],
                         'env_ar --env-arflags')
        self.assertEqual(comp.exes['preprocessor'],
                         'env_cpp --env-cppflags')
        self.assertEqual(comp.exes['compiler'],
                         'env_cc --sc-cflags --env-cflags --env-cppflags')
        self.assertEqual(comp.exes['compiler_so'],
                         ('env_cc --sc-cflags '
                          '--env-cflags ''--env-cppflags --sc-ccshared'))
        self.assertEqual(comp.exes['compiler_cxx'],
                         'env_cxx --env-cxx-flags')
        self.assertEqual(comp.exes['linker_exe'],
                         'env_cc')
        self.assertEqual(comp.exes['linker_so'],
                         ('env_ldshared --env-ldflags --env-cflags'
                          ' --env-cppflags'))
        self.assertEqual(comp.shared_lib_extension, 'sc_shutil_suffix')

        del os.environ['AR']
        del os.environ['CC']
        del os.environ['CPP']
        del os.environ['CXX']
        del os.environ['LDSHARED']
        del os.environ['LDFLAGS']
        del os.environ['ARFLAGS']
        del os.environ['CFLAGS']
        del os.environ['CPPFLAGS']

        comp = self.customize_compiler()
        self.assertEqual(comp.exes['archiver'],
                         'sc_ar --sc-arflags')
        self.assertEqual(comp.exes['preprocessor'],
                         'sc_cc -E')
        self.assertEqual(comp.exes['compiler'],
                         'sc_cc --sc-cflags')
        self.assertEqual(comp.exes['compiler_so'],
                         'sc_cc --sc-cflags --sc-ccshared')
        self.assertEqual(comp.exes['compiler_cxx'],
                         'sc_cxx')
        self.assertEqual(comp.exes['linker_exe'],
                         'sc_cc')
        self.assertEqual(comp.exes['linker_so'],
                         'sc_ldshared')
        self.assertEqual(comp.shared_lib_extension, 'sc_shutil_suffix')

    def test_parse_makefile_base(self):
        self.makefile = TESTFN
        fd = open(self.makefile, 'w')
        try:
            fd.write(r"CONFIG_ARGS=  '--arg1=optarg1' 'ENV=LIB'" '\n')
            fd.write('VAR=$OTHER\nOTHER=foo')
        finally:
            fd.close()
        d = sysconfig.parse_makefile(self.makefile)
        self.assertEqual(d, {'CONFIG_ARGS': "'--arg1=optarg1' 'ENV=LIB'",
                             'OTHER': 'foo'})

    def test_parse_makefile_literal_dollar(self):
        self.makefile = TESTFN
        fd = open(self.makefile, 'w')
        try:
            fd.write(r"CONFIG_ARGS=  '--arg1=optarg1' 'ENV=\$$LIB'" '\n')
            fd.write('VAR=$OTHER\nOTHER=foo')
        finally:
            fd.close()
        d = sysconfig.parse_makefile(self.makefile)
        self.assertEqual(d, {'CONFIG_ARGS': r"'--arg1=optarg1' 'ENV=\$LIB'",
                             'OTHER': 'foo'})


    def test_sysconfig_module(self):
        import sysconfig as global_sysconfig
        self.assertEqual(global_sysconfig.get_config_var('CFLAGS'),
                         sysconfig.get_config_var('CFLAGS'))
        self.assertEqual(global_sysconfig.get_config_var('LDFLAGS'),
                         sysconfig.get_config_var('LDFLAGS'))

    @unittest.skipIf(sysconfig.get_config_var('CUSTOMIZED_OSX_COMPILER'),
                     'compiler flags customized')
    def test_sysconfig_compiler_vars(self):
        # On OS X, binary installers support extension module building on
        # various levels of the operating system with differing Xcode
        # configurations.  This requires customization of some of the
        # compiler configuration directives to suit the environment on
        # the installed machine.  Some of these customizations may require
        # running external programs and, so, are deferred until needed by
        # the first extension module build.  With Python 3.3, only
        # the Distutils version of sysconfig is used for extension module
        # builds, which happens earlier in the Distutils tests.  This may
        # cause the following tests to fail since no tests have caused
        # the global version of sysconfig to call the customization yet.
        # The solution for now is to simply skip this test in this case.
        # The longer-term solution is to only have one version of sysconfig.

        import sysconfig as global_sysconfig
        if sysconfig.get_config_var('CUSTOMIZED_OSX_COMPILER'):
            self.skipTest('compiler flags customized')
        self.assertEqual(global_sysconfig.get_config_var('LDSHARED'),
                         sysconfig.get_config_var('LDSHARED'))
        self.assertEqual(global_sysconfig.get_config_var('CC'),
                         sysconfig.get_config_var('CC'))

    @unittest.skipIf(sysconfig.get_config_var('EXT_SUFFIX') is None,
                     'EXT_SUFFIX required for this test')
    def test_SO_deprecation(self):
        self.assertWarns(DeprecationWarning,
                         sysconfig.get_config_var, 'SO')

    @unittest.skipIf(sysconfig.get_config_var('EXT_SUFFIX') is None,
                     'EXT_SUFFIX required for this test')
    def test_SO_value(self):
        with check_warnings(('', DeprecationWarning)):
            self.assertEqual(sysconfig.get_config_var('SO'),
                             sysconfig.get_config_var('EXT_SUFFIX'))

    @unittest.skipIf(sysconfig.get_config_var('EXT_SUFFIX') is None,
                     'EXT_SUFFIX required for this test')
    def test_SO_in_vars(self):
        vars = sysconfig.get_config_vars()
        self.assertIsNotNone(vars['SO'])
        self.assertEqual(vars['SO'], vars['EXT_SUFFIX'])

    def test_customize_compiler_before_get_config_vars(self):
        # Issue #21923: test that a Distribution compiler
        # instance can be called without an explicit call to
        # get_config_vars().
        with open(TESTFN, 'w') as f:
            f.writelines(textwrap.dedent('''\
                from distutils.core import Distribution
                config = Distribution().get_command_obj('config')
                # try_compile may pass or it may fail if no compiler
                # is found but it should not raise an exception.
                rc = config.try_compile('int x;')
                '''))
        p = subprocess.Popen([str(sys.executable), TESTFN],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True)
        outs, errs = p.communicate()
        self.assertEqual(0, p.returncode, "Subprocess failed: " + outs)


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(SysconfigTestCase))
    return suite


if __name__ == '__main__':
    run_unittest(test_suite())
