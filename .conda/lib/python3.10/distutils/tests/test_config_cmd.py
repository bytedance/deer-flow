"""Tests for distutils.command.config."""
import unittest
import os
import sys
import sysconfig
from test.support import run_unittest, missing_compiler_executable

from distutils.command.config import dump_file, config
from distutils.tests import support
from distutils import log

class ConfigTestCase(support.LoggingSilencer,
                     support.TempdirManager,
                     unittest.TestCase):

    def _info(self, msg, *args):
        for line in msg.splitlines():
            self._logs.append(line)

    def setUp(self):
        super(ConfigTestCase, self).setUp()
        self._logs = []
        self.old_log = log.info
        log.info = self._info
        self.old_config_vars = dict(sysconfig._CONFIG_VARS)

    def tearDown(self):
        log.info = self.old_log
        sysconfig._CONFIG_VARS.clear()
        sysconfig._CONFIG_VARS.update(self.old_config_vars)
        super(ConfigTestCase, self).tearDown()

    def test_dump_file(self):
        this_file = os.path.splitext(__file__)[0] + '.py'
        f = open(this_file)
        try:
            numlines = len(f.readlines())
        finally:
            f.close()

        dump_file(this_file, 'I am the header')
        self.assertEqual(len(self._logs), numlines+1)

    @unittest.skipIf(sys.platform == 'win32', "can't test on Windows")
    def test_search_cpp(self):
        cmd = missing_compiler_executable(['preprocessor'])
        if cmd is not None:
            self.skipTest('The %r command is not found' % cmd)
        pkg_dir, dist = self.create_dist()
        cmd = config(dist)
        cmd._check_compiler()
        compiler = cmd.compiler
        if sys.platform[:3] == "aix" and "xlc" in compiler.preprocessor[0].lower():
            self.skipTest('xlc: The -E option overrides the -P, -o, and -qsyntaxonly options')

        # simple pattern searches
        match = cmd.search_cpp(pattern='xxx', body='/* xxx */')
        self.assertEqual(match, 0)

        match = cmd.search_cpp(pattern='_configtest', body='/* xxx */')
        self.assertEqual(match, 1)

    def test_finalize_options(self):
        # finalize_options does a bit of transformation
        # on options
        pkg_dir, dist = self.create_dist()
        cmd = config(dist)
        cmd.include_dirs = 'one%stwo' % os.pathsep
        cmd.libraries = 'one'
        cmd.library_dirs = 'three%sfour' % os.pathsep
        cmd.ensure_finalized()

        self.assertEqual(cmd.include_dirs, ['one', 'two'])
        self.assertEqual(cmd.libraries, ['one'])
        self.assertEqual(cmd.library_dirs, ['three', 'four'])

    def test_clean(self):
        # _clean removes files
        tmp_dir = self.mkdtemp()
        f1 = os.path.join(tmp_dir, 'one')
        f2 = os.path.join(tmp_dir, 'two')

        self.write_file(f1, 'xxx')
        self.write_file(f2, 'xxx')

        for f in (f1, f2):
            self.assertTrue(os.path.exists(f))

        pkg_dir, dist = self.create_dist()
        cmd = config(dist)
        cmd._clean(f1, f2)

        for f in (f1, f2):
            self.assertFalse(os.path.exists(f))

def test_suite():
    return unittest.makeSuite(ConfigTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
