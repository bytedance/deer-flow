"""Tests for distutils.command.clean."""
import os
import unittest

from distutils.command.clean import clean
from distutils.tests import support
from test.support import run_unittest

class cleanTestCase(support.TempdirManager,
                    support.LoggingSilencer,
                    unittest.TestCase):

    def test_simple_run(self):
        pkg_dir, dist = self.create_dist()
        cmd = clean(dist)

        # let's add some elements clean should remove
        dirs = [(d, os.path.join(pkg_dir, d))
                for d in ('build_temp', 'build_lib', 'bdist_base',
                'build_scripts', 'build_base')]

        for name, path in dirs:
            os.mkdir(path)
            setattr(cmd, name, path)
            if name == 'build_base':
                continue
            for f in ('one', 'two', 'three'):
                self.write_file(os.path.join(path, f))

        # let's run the command
        cmd.all = 1
        cmd.ensure_finalized()
        cmd.run()

        # make sure the files where removed
        for name, path in dirs:
            self.assertFalse(os.path.exists(path),
                         '%s was not removed' % path)

        # let's run the command again (should spit warnings but succeed)
        cmd.all = 1
        cmd.ensure_finalized()
        cmd.run()

def test_suite():
    return unittest.makeSuite(cleanTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
