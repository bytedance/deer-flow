"""Tests for distutils.command.build."""
import unittest
import os
import sys
from test.support import run_unittest

from distutils.command.build import build
from distutils.tests import support
from sysconfig import get_platform

class BuildTestCase(support.TempdirManager,
                    support.LoggingSilencer,
                    unittest.TestCase):

    def test_finalize_options(self):
        pkg_dir, dist = self.create_dist()
        cmd = build(dist)
        cmd.finalize_options()

        # if not specified, plat_name gets the current platform
        self.assertEqual(cmd.plat_name, get_platform())

        # build_purelib is build + lib
        wanted = os.path.join(cmd.build_base, 'lib')
        self.assertEqual(cmd.build_purelib, wanted)

        # build_platlib is 'build/lib.platform-x.x[-pydebug]'
        # examples:
        #   build/lib.macosx-10.3-i386-2.7
        plat_spec = '.%s-%d.%d' % (cmd.plat_name, *sys.version_info[:2])
        if hasattr(sys, 'gettotalrefcount'):
            self.assertTrue(cmd.build_platlib.endswith('-pydebug'))
            plat_spec += '-pydebug'
        wanted = os.path.join(cmd.build_base, 'lib' + plat_spec)
        self.assertEqual(cmd.build_platlib, wanted)

        # by default, build_lib = build_purelib
        self.assertEqual(cmd.build_lib, cmd.build_purelib)

        # build_temp is build/temp.<plat>
        wanted = os.path.join(cmd.build_base, 'temp' + plat_spec)
        self.assertEqual(cmd.build_temp, wanted)

        # build_scripts is build/scripts-x.x
        wanted = os.path.join(cmd.build_base,
                              'scripts-%d.%d' % sys.version_info[:2])
        self.assertEqual(cmd.build_scripts, wanted)

        # executable is os.path.normpath(sys.executable)
        self.assertEqual(cmd.executable, os.path.normpath(sys.executable))

def test_suite():
    return unittest.makeSuite(BuildTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
