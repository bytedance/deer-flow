import sys
import os
from io import StringIO
import textwrap

from distutils.core import Distribution
from distutils.command.build_ext import build_ext
from distutils import sysconfig
from distutils.tests.support import (TempdirManager, LoggingSilencer,
                                     copy_xxmodule_c, fixup_build_ext)
from distutils.extension import Extension
from distutils.errors import (
    CompileError, DistutilsPlatformError, DistutilsSetupError,
    UnknownFileError)

import unittest
from test import support
from test.support import os_helper
from test.support.script_helper import assert_python_ok

# http://bugs.python.org/issue4373
# Don't load the xx module more than once.
ALREADY_TESTED = False


class BuildExtTestCase(TempdirManager,
                       LoggingSilencer,
                       unittest.TestCase):
    def setUp(self):
        # Create a simple test environment
        super(BuildExtTestCase, self).setUp()
        self.tmp_dir = self.mkdtemp()
        import site
        self.old_user_base = site.USER_BASE
        site.USER_BASE = self.mkdtemp()
        from distutils.command import build_ext
        build_ext.USER_BASE = site.USER_BASE
        self.old_config_vars = dict(sysconfig._config_vars)

        # bpo-30132: On Windows, a .pdb file may be created in the current
        # working directory. Create a temporary working directory to cleanup
        # everything at the end of the test.
        change_cwd = os_helper.change_cwd(self.tmp_dir)
        change_cwd.__enter__()
        self.addCleanup(change_cwd.__exit__, None, None, None)

    def tearDown(self):
        import site
        site.USER_BASE = self.old_user_base
        from distutils.command import build_ext
        build_ext.USER_BASE = self.old_user_base
        sysconfig._config_vars.clear()
        sysconfig._config_vars.update(self.old_config_vars)
        super(BuildExtTestCase, self).tearDown()

    def build_ext(self, *args, **kwargs):
        return build_ext(*args, **kwargs)

    def test_build_ext(self):
        cmd = support.missing_compiler_executable()
        if cmd is not None:
            self.skipTest('The %r command is not found' % cmd)
        global ALREADY_TESTED
        copy_xxmodule_c(self.tmp_dir)
        xx_c = os.path.join(self.tmp_dir, 'xxmodule.c')
        xx_ext = Extension('xx', [xx_c])
        dist = Distribution({'name': 'xx', 'ext_modules': [xx_ext]})
        dist.package_dir = self.tmp_dir
        cmd = self.build_ext(dist)
        fixup_build_ext(cmd)
        cmd.build_lib = self.tmp_dir
        cmd.build_temp = self.tmp_dir

        old_stdout = sys.stdout
        if not support.verbose:
            # silence compiler output
            sys.stdout = StringIO()
        try:
            cmd.ensure_finalized()
            cmd.run()
        finally:
            sys.stdout = old_stdout

        if ALREADY_TESTED:
            self.skipTest('Already tested in %s' % ALREADY_TESTED)
        else:
            ALREADY_TESTED = type(self).__name__

        code = textwrap.dedent(f"""
            tmp_dir = {self.tmp_dir!r}

            import sys
            import unittest
            from test import support

            sys.path.insert(0, tmp_dir)
            import xx

            class Tests(unittest.TestCase):
                def test_xx(self):
                    for attr in ('error', 'foo', 'new', 'roj'):
                        self.assertTrue(hasattr(xx, attr))

                    self.assertEqual(xx.foo(2, 5), 7)
                    self.assertEqual(xx.foo(13,15), 28)
                    self.assertEqual(xx.new().demo(), None)
                    if support.HAVE_DOCSTRINGS:
                        doc = 'This is a template module just for instruction.'
                        self.assertEqual(xx.__doc__, doc)
                    self.assertIsInstance(xx.Null(), xx.Null)
                    self.assertIsInstance(xx.Str(), xx.Str)


            unittest.main()
        """)
        assert_python_ok('-c', code)

    def test_solaris_enable_shared(self):
        dist = Distribution({'name': 'xx'})
        cmd = self.build_ext(dist)
        old = sys.platform

        sys.platform = 'sunos' # fooling finalize_options
        from distutils.sysconfig import  _config_vars
        old_var = _config_vars.get('Py_ENABLE_SHARED')
        _config_vars['Py_ENABLE_SHARED'] = 1
        try:
            cmd.ensure_finalized()
        finally:
            sys.platform = old
            if old_var is None:
                del _config_vars['Py_ENABLE_SHARED']
            else:
                _config_vars['Py_ENABLE_SHARED'] = old_var

        # make sure we get some library dirs under solaris
        self.assertGreater(len(cmd.library_dirs), 0)

    def test_user_site(self):
        import site
        dist = Distribution({'name': 'xx'})
        cmd = self.build_ext(dist)

        # making sure the user option is there
        options = [name for name, short, lable in
                   cmd.user_options]
        self.assertIn('user', options)

        # setting a value
        cmd.user = 1

        # setting user based lib and include
        lib = os.path.join(site.USER_BASE, 'lib')
        incl = os.path.join(site.USER_BASE, 'include')
        os.mkdir(lib)
        os.mkdir(incl)

        # let's run finalize
        cmd.ensure_finalized()

        # see if include_dirs and library_dirs
        # were set
        self.assertIn(lib, cmd.library_dirs)
        self.assertIn(lib, cmd.rpath)
        self.assertIn(incl, cmd.include_dirs)

    def test_optional_extension(self):

        # this extension will fail, but let's ignore this failure
        # with the optional argument.
        modules = [Extension('foo', ['xxx'], optional=False)]
        dist = Distribution({'name': 'xx', 'ext_modules': modules})
        cmd = self.build_ext(dist)
        cmd.ensure_finalized()
        self.assertRaises((UnknownFileError, CompileError),
                          cmd.run)  # should raise an error

        modules = [Extension('foo', ['xxx'], optional=True)]
        dist = Distribution({'name': 'xx', 'ext_modules': modules})
        cmd = self.build_ext(dist)
        cmd.ensure_finalized()
        cmd.run()  # should pass

    def test_finalize_options(self):
        # Make sure Python's include directories (for Python.h, pyconfig.h,
        # etc.) are in the include search path.
        modules = [Extension('foo', ['xxx'], optional=False)]
        dist = Distribution({'name': 'xx', 'ext_modules': modules})
        cmd = self.build_ext(dist)
        cmd.finalize_options()

        py_include = sysconfig.get_python_inc()
        for p in py_include.split(os.path.pathsep):
            self.assertIn(p, cmd.include_dirs)

        plat_py_include = sysconfig.get_python_inc(plat_specific=1)
        for p in plat_py_include.split(os.path.pathsep):
            self.assertIn(p, cmd.include_dirs)

        # make sure cmd.libraries is turned into a list
        # if it's a string
        cmd = self.build_ext(dist)
        cmd.libraries = 'my_lib, other_lib lastlib'
        cmd.finalize_options()
        self.assertEqual(cmd.libraries, ['my_lib', 'other_lib', 'lastlib'])

        # make sure cmd.library_dirs is turned into a list
        # if it's a string
        cmd = self.build_ext(dist)
        cmd.library_dirs = 'my_lib_dir%sother_lib_dir' % os.pathsep
        cmd.finalize_options()
        self.assertIn('my_lib_dir', cmd.library_dirs)
        self.assertIn('other_lib_dir', cmd.library_dirs)

        # make sure rpath is turned into a list
        # if it's a string
        cmd = self.build_ext(dist)
        cmd.rpath = 'one%stwo' % os.pathsep
        cmd.finalize_options()
        self.assertEqual(cmd.rpath, ['one', 'two'])

        # make sure cmd.link_objects is turned into a list
        # if it's a string
        cmd = build_ext(dist)
        cmd.link_objects = 'one two,three'
        cmd.finalize_options()
        self.assertEqual(cmd.link_objects, ['one', 'two', 'three'])

        # XXX more tests to perform for win32

        # make sure define is turned into 2-tuples
        # strings if they are ','-separated strings
        cmd = self.build_ext(dist)
        cmd.define = 'one,two'
        cmd.finalize_options()
        self.assertEqual(cmd.define, [('one', '1'), ('two', '1')])

        # make sure undef is turned into a list of
        # strings if they are ','-separated strings
        cmd = self.build_ext(dist)
        cmd.undef = 'one,two'
        cmd.finalize_options()
        self.assertEqual(cmd.undef, ['one', 'two'])

        # make sure swig_opts is turned into a list
        cmd = self.build_ext(dist)
        cmd.swig_opts = None
        cmd.finalize_options()
        self.assertEqual(cmd.swig_opts, [])

        cmd = self.build_ext(dist)
        cmd.swig_opts = '1 2'
        cmd.finalize_options()
        self.assertEqual(cmd.swig_opts, ['1', '2'])

    def test_check_extensions_list(self):
        dist = Distribution()
        cmd = self.build_ext(dist)
        cmd.finalize_options()

        #'extensions' option must be a list of Extension instances
        self.assertRaises(DistutilsSetupError,
                          cmd.check_extensions_list, 'foo')

        # each element of 'ext_modules' option must be an
        # Extension instance or 2-tuple
        exts = [('bar', 'foo', 'bar'), 'foo']
        self.assertRaises(DistutilsSetupError, cmd.check_extensions_list, exts)

        # first element of each tuple in 'ext_modules'
        # must be the extension name (a string) and match
        # a python dotted-separated name
        exts = [('foo-bar', '')]
        self.assertRaises(DistutilsSetupError, cmd.check_extensions_list, exts)

        # second element of each tuple in 'ext_modules'
        # must be a dictionary (build info)
        exts = [('foo.bar', '')]
        self.assertRaises(DistutilsSetupError, cmd.check_extensions_list, exts)

        # ok this one should pass
        exts = [('foo.bar', {'sources': [''], 'libraries': 'foo',
                             'some': 'bar'})]
        cmd.check_extensions_list(exts)
        ext = exts[0]
        self.assertIsInstance(ext, Extension)

        # check_extensions_list adds in ext the values passed
        # when they are in ('include_dirs', 'library_dirs', 'libraries'
        # 'extra_objects', 'extra_compile_args', 'extra_link_args')
        self.assertEqual(ext.libraries, 'foo')
        self.assertFalse(hasattr(ext, 'some'))

        # 'macros' element of build info dict must be 1- or 2-tuple
        exts = [('foo.bar', {'sources': [''], 'libraries': 'foo',
                'some': 'bar', 'macros': [('1', '2', '3'), 'foo']})]
        self.assertRaises(DistutilsSetupError, cmd.check_extensions_list, exts)

        exts[0][1]['macros'] = [('1', '2'), ('3',)]
        cmd.check_extensions_list(exts)
        self.assertEqual(exts[0].undef_macros, ['3'])
        self.assertEqual(exts[0].define_macros, [('1', '2')])

    def test_get_source_files(self):
        modules = [Extension('foo', ['xxx'], optional=False)]
        dist = Distribution({'name': 'xx', 'ext_modules': modules})
        cmd = self.build_ext(dist)
        cmd.ensure_finalized()
        self.assertEqual(cmd.get_source_files(), ['xxx'])

    def test_unicode_module_names(self):
        modules = [
            Extension('foo', ['aaa'], optional=False),
            Extension('föö', ['uuu'], optional=False),
        ]
        dist = Distribution({'name': 'xx', 'ext_modules': modules})
        cmd = self.build_ext(dist)
        cmd.ensure_finalized()
        self.assertRegex(cmd.get_ext_filename(modules[0].name), r'foo(_d)?\..*')
        self.assertRegex(cmd.get_ext_filename(modules[1].name), r'föö(_d)?\..*')
        self.assertEqual(cmd.get_export_symbols(modules[0]), ['PyInit_foo'])
        self.assertEqual(cmd.get_export_symbols(modules[1]), ['PyInitU_f_gkaa'])

    def test_compiler_option(self):
        # cmd.compiler is an option and
        # should not be overridden by a compiler instance
        # when the command is run
        dist = Distribution()
        cmd = self.build_ext(dist)
        cmd.compiler = 'unix'
        cmd.ensure_finalized()
        cmd.run()
        self.assertEqual(cmd.compiler, 'unix')

    def test_get_outputs(self):
        cmd = support.missing_compiler_executable()
        if cmd is not None:
            self.skipTest('The %r command is not found' % cmd)
        tmp_dir = self.mkdtemp()
        c_file = os.path.join(tmp_dir, 'foo.c')
        self.write_file(c_file, 'void PyInit_foo(void) {}\n')
        ext = Extension('foo', [c_file], optional=False)
        dist = Distribution({'name': 'xx',
                             'ext_modules': [ext]})
        cmd = self.build_ext(dist)
        fixup_build_ext(cmd)
        cmd.ensure_finalized()
        self.assertEqual(len(cmd.get_outputs()), 1)

        cmd.build_lib = os.path.join(self.tmp_dir, 'build')
        cmd.build_temp = os.path.join(self.tmp_dir, 'tempt')

        # issue #5977 : distutils build_ext.get_outputs
        # returns wrong result with --inplace
        other_tmp_dir = os.path.realpath(self.mkdtemp())
        old_wd = os.getcwd()
        os.chdir(other_tmp_dir)
        try:
            cmd.inplace = 1
            cmd.run()
            so_file = cmd.get_outputs()[0]
        finally:
            os.chdir(old_wd)
        self.assertTrue(os.path.exists(so_file))
        ext_suffix = sysconfig.get_config_var('EXT_SUFFIX')
        self.assertTrue(so_file.endswith(ext_suffix))
        so_dir = os.path.dirname(so_file)
        self.assertEqual(so_dir, other_tmp_dir)

        cmd.inplace = 0
        cmd.compiler = None
        cmd.run()
        so_file = cmd.get_outputs()[0]
        self.assertTrue(os.path.exists(so_file))
        self.assertTrue(so_file.endswith(ext_suffix))
        so_dir = os.path.dirname(so_file)
        self.assertEqual(so_dir, cmd.build_lib)

        # inplace = 0, cmd.package = 'bar'
        build_py = cmd.get_finalized_command('build_py')
        build_py.package_dir = {'': 'bar'}
        path = cmd.get_ext_fullpath('foo')
        # checking that the last directory is the build_dir
        path = os.path.split(path)[0]
        self.assertEqual(path, cmd.build_lib)

        # inplace = 1, cmd.package = 'bar'
        cmd.inplace = 1
        other_tmp_dir = os.path.realpath(self.mkdtemp())
        old_wd = os.getcwd()
        os.chdir(other_tmp_dir)
        try:
            path = cmd.get_ext_fullpath('foo')
        finally:
            os.chdir(old_wd)
        # checking that the last directory is bar
        path = os.path.split(path)[0]
        lastdir = os.path.split(path)[-1]
        self.assertEqual(lastdir, 'bar')

    def test_ext_fullpath(self):
        ext = sysconfig.get_config_var('EXT_SUFFIX')
        # building lxml.etree inplace
        #etree_c = os.path.join(self.tmp_dir, 'lxml.etree.c')
        #etree_ext = Extension('lxml.etree', [etree_c])
        #dist = Distribution({'name': 'lxml', 'ext_modules': [etree_ext]})
        dist = Distribution()
        cmd = self.build_ext(dist)
        cmd.inplace = 1
        cmd.distribution.package_dir = {'': 'src'}
        cmd.distribution.packages = ['lxml', 'lxml.html']
        curdir = os.getcwd()
        wanted = os.path.join(curdir, 'src', 'lxml', 'etree' + ext)
        path = cmd.get_ext_fullpath('lxml.etree')
        self.assertEqual(wanted, path)

        # building lxml.etree not inplace
        cmd.inplace = 0
        cmd.build_lib = os.path.join(curdir, 'tmpdir')
        wanted = os.path.join(curdir, 'tmpdir', 'lxml', 'etree' + ext)
        path = cmd.get_ext_fullpath('lxml.etree')
        self.assertEqual(wanted, path)

        # building twisted.runner.portmap not inplace
        build_py = cmd.get_finalized_command('build_py')
        build_py.package_dir = {}
        cmd.distribution.packages = ['twisted', 'twisted.runner.portmap']
        path = cmd.get_ext_fullpath('twisted.runner.portmap')
        wanted = os.path.join(curdir, 'tmpdir', 'twisted', 'runner',
                              'portmap' + ext)
        self.assertEqual(wanted, path)

        # building twisted.runner.portmap inplace
        cmd.inplace = 1
        path = cmd.get_ext_fullpath('twisted.runner.portmap')
        wanted = os.path.join(curdir, 'twisted', 'runner', 'portmap' + ext)
        self.assertEqual(wanted, path)


    @unittest.skipUnless(sys.platform == 'darwin', 'test only relevant for MacOSX')
    def test_deployment_target_default(self):
        # Issue 9516: Test that, in the absence of the environment variable,
        # an extension module is compiled with the same deployment target as
        #  the interpreter.
        self._try_compile_deployment_target('==', None)

    @unittest.skipUnless(sys.platform == 'darwin', 'test only relevant for MacOSX')
    def test_deployment_target_too_low(self):
        # Issue 9516: Test that an extension module is not allowed to be
        # compiled with a deployment target less than that of the interpreter.
        self.assertRaises(DistutilsPlatformError,
            self._try_compile_deployment_target, '>', '10.1')

    @unittest.skipUnless(sys.platform == 'darwin', 'test only relevant for MacOSX')
    def test_deployment_target_higher_ok(self):
        # Issue 9516: Test that an extension module can be compiled with a
        # deployment target higher than that of the interpreter: the ext
        # module may depend on some newer OS feature.
        deptarget = sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET')
        if deptarget:
            # increment the minor version number (i.e. 10.6 -> 10.7)
            deptarget = [int(x) for x in deptarget.split('.')]
            deptarget[-1] += 1
            deptarget = '.'.join(str(i) for i in deptarget)
            self._try_compile_deployment_target('<', deptarget)

    def _try_compile_deployment_target(self, operator, target):
        orig_environ = os.environ
        os.environ = orig_environ.copy()
        self.addCleanup(setattr, os, 'environ', orig_environ)

        if target is None:
            if os.environ.get('MACOSX_DEPLOYMENT_TARGET'):
                del os.environ['MACOSX_DEPLOYMENT_TARGET']
        else:
            os.environ['MACOSX_DEPLOYMENT_TARGET'] = target

        deptarget_c = os.path.join(self.tmp_dir, 'deptargetmodule.c')

        with open(deptarget_c, 'w') as fp:
            fp.write(textwrap.dedent('''\
                #include <AvailabilityMacros.h>

                int dummy;

                #if TARGET %s MAC_OS_X_VERSION_MIN_REQUIRED
                #else
                #error "Unexpected target"
                #endif

            ''' % operator))

        # get the deployment target that the interpreter was built with
        target = sysconfig.get_config_var('MACOSX_DEPLOYMENT_TARGET')
        target = tuple(map(int, target.split('.')[0:2]))
        # format the target value as defined in the Apple
        # Availability Macros.  We can't use the macro names since
        # at least one value we test with will not exist yet.
        if target[:2] < (10, 10):
            # for 10.1 through 10.9.x -> "10n0"
            target = '%02d%01d0' % target
        else:
            # for 10.10 and beyond -> "10nn00"
            if len(target) >= 2:
                target = '%02d%02d00' % target
            else:
                # 11 and later can have no minor version (11 instead of 11.0)
                target = '%02d0000' % target
        deptarget_ext = Extension(
            'deptarget',
            [deptarget_c],
            extra_compile_args=['-DTARGET=%s'%(target,)],
        )
        dist = Distribution({
            'name': 'deptarget',
            'ext_modules': [deptarget_ext]
        })
        dist.package_dir = self.tmp_dir
        cmd = self.build_ext(dist)
        cmd.build_lib = self.tmp_dir
        cmd.build_temp = self.tmp_dir

        try:
            old_stdout = sys.stdout
            if not support.verbose:
                # silence compiler output
                sys.stdout = StringIO()
            try:
                cmd.ensure_finalized()
                cmd.run()
            finally:
                sys.stdout = old_stdout

        except CompileError:
            self.fail("Wrong deployment target during compilation")


class ParallelBuildExtTestCase(BuildExtTestCase):

    def build_ext(self, *args, **kwargs):
        build_ext = super().build_ext(*args, **kwargs)
        build_ext.parallel = True
        return build_ext


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(BuildExtTestCase))
    suite.addTest(unittest.makeSuite(ParallelBuildExtTestCase))
    return suite

if __name__ == '__main__':
    support.run_unittest(__name__)
