"""Tests for distutils.spawn."""
import os
import stat
import sys
import unittest.mock
from test.support import run_unittest, unix_shell
from test.support import os_helper

from distutils.spawn import find_executable
from distutils.spawn import spawn
from distutils.errors import DistutilsExecError
from distutils.tests import support

class SpawnTestCase(support.TempdirManager,
                    support.LoggingSilencer,
                    unittest.TestCase):

    @unittest.skipUnless(os.name in ('nt', 'posix'),
                         'Runs only under posix or nt')
    def test_spawn(self):
        tmpdir = self.mkdtemp()

        # creating something executable
        # through the shell that returns 1
        if sys.platform != 'win32':
            exe = os.path.join(tmpdir, 'foo.sh')
            self.write_file(exe, '#!%s\nexit 1' % unix_shell)
        else:
            exe = os.path.join(tmpdir, 'foo.bat')
            self.write_file(exe, 'exit 1')

        os.chmod(exe, 0o777)
        self.assertRaises(DistutilsExecError, spawn, [exe])

        # now something that works
        if sys.platform != 'win32':
            exe = os.path.join(tmpdir, 'foo.sh')
            self.write_file(exe, '#!%s\nexit 0' % unix_shell)
        else:
            exe = os.path.join(tmpdir, 'foo.bat')
            self.write_file(exe, 'exit 0')

        os.chmod(exe, 0o777)
        spawn([exe])  # should work without any error

    def test_find_executable(self):
        with os_helper.temp_dir() as tmp_dir:
            # use TESTFN to get a pseudo-unique filename
            program_noeext = os_helper.TESTFN
            # Give the temporary program an ".exe" suffix for all.
            # It's needed on Windows and not harmful on other platforms.
            program = program_noeext + ".exe"

            filename = os.path.join(tmp_dir, program)
            with open(filename, "wb"):
                pass
            os.chmod(filename, stat.S_IXUSR)

            # test path parameter
            rv = find_executable(program, path=tmp_dir)
            self.assertEqual(rv, filename)

            if sys.platform == 'win32':
                # test without ".exe" extension
                rv = find_executable(program_noeext, path=tmp_dir)
                self.assertEqual(rv, filename)

            # test find in the current directory
            with os_helper.change_cwd(tmp_dir):
                rv = find_executable(program)
                self.assertEqual(rv, program)

            # test non-existent program
            dont_exist_program = "dontexist_" + program
            rv = find_executable(dont_exist_program , path=tmp_dir)
            self.assertIsNone(rv)

            # PATH='': no match, except in the current directory
            with os_helper.EnvironmentVarGuard() as env:
                env['PATH'] = ''
                with unittest.mock.patch('distutils.spawn.os.confstr',
                                         return_value=tmp_dir, create=True), \
                     unittest.mock.patch('distutils.spawn.os.defpath',
                                         tmp_dir):
                    rv = find_executable(program)
                    self.assertIsNone(rv)

                    # look in current directory
                    with os_helper.change_cwd(tmp_dir):
                        rv = find_executable(program)
                        self.assertEqual(rv, program)

            # PATH=':': explicitly looks in the current directory
            with os_helper.EnvironmentVarGuard() as env:
                env['PATH'] = os.pathsep
                with unittest.mock.patch('distutils.spawn.os.confstr',
                                         return_value='', create=True), \
                     unittest.mock.patch('distutils.spawn.os.defpath', ''):
                    rv = find_executable(program)
                    self.assertIsNone(rv)

                    # look in current directory
                    with os_helper.change_cwd(tmp_dir):
                        rv = find_executable(program)
                        self.assertEqual(rv, program)

            # missing PATH: test os.confstr("CS_PATH") and os.defpath
            with os_helper.EnvironmentVarGuard() as env:
                env.pop('PATH', None)

                # without confstr
                with unittest.mock.patch('distutils.spawn.os.confstr',
                                         side_effect=ValueError,
                                         create=True), \
                     unittest.mock.patch('distutils.spawn.os.defpath',
                                         tmp_dir):
                    rv = find_executable(program)
                    self.assertEqual(rv, filename)

                # with confstr
                with unittest.mock.patch('distutils.spawn.os.confstr',
                                         return_value=tmp_dir, create=True), \
                     unittest.mock.patch('distutils.spawn.os.defpath', ''):
                    rv = find_executable(program)
                    self.assertEqual(rv, filename)

    def test_spawn_missing_exe(self):
        with self.assertRaises(DistutilsExecError) as ctx:
            spawn(['does-not-exist'])
        self.assertIn("command 'does-not-exist' failed", str(ctx.exception))


def test_suite():
    return unittest.makeSuite(SpawnTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
