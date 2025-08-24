"""Tests for distutils.command.bdist_dumb."""

import os
import sys
import zipfile
import unittest
from test.support import run_unittest

from distutils.core import Distribution
from distutils.command.bdist_dumb import bdist_dumb
from distutils.tests import support

SETUP_PY = """\
from distutils.core import setup
import foo

setup(name='foo', version='0.1', py_modules=['foo'],
      url='xxx', author='xxx', author_email='xxx')

"""

try:
    import zlib
    ZLIB_SUPPORT = True
except ImportError:
    ZLIB_SUPPORT = False


class BuildDumbTestCase(support.TempdirManager,
                        support.LoggingSilencer,
                        support.EnvironGuard,
                        unittest.TestCase):

    def setUp(self):
        super(BuildDumbTestCase, self).setUp()
        self.old_location = os.getcwd()
        self.old_sys_argv = sys.argv, sys.argv[:]

    def tearDown(self):
        os.chdir(self.old_location)
        sys.argv = self.old_sys_argv[0]
        sys.argv[:] = self.old_sys_argv[1]
        super(BuildDumbTestCase, self).tearDown()

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_simple_built(self):

        # let's create a simple package
        tmp_dir = self.mkdtemp()
        pkg_dir = os.path.join(tmp_dir, 'foo')
        os.mkdir(pkg_dir)
        self.write_file((pkg_dir, 'setup.py'), SETUP_PY)
        self.write_file((pkg_dir, 'foo.py'), '#')
        self.write_file((pkg_dir, 'MANIFEST.in'), 'include foo.py')
        self.write_file((pkg_dir, 'README'), '')

        dist = Distribution({'name': 'foo', 'version': '0.1',
                             'py_modules': ['foo'],
                             'url': 'xxx', 'author': 'xxx',
                             'author_email': 'xxx'})
        dist.script_name = 'setup.py'
        os.chdir(pkg_dir)

        sys.argv = ['setup.py']
        cmd = bdist_dumb(dist)

        # so the output is the same no matter
        # what is the platform
        cmd.format = 'zip'

        cmd.ensure_finalized()
        cmd.run()

        # see what we have
        dist_created = os.listdir(os.path.join(pkg_dir, 'dist'))
        base = "%s.%s.zip" % (dist.get_fullname(), cmd.plat_name)

        self.assertEqual(dist_created, [base])

        # now let's check what we have in the zip file
        fp = zipfile.ZipFile(os.path.join('dist', base))
        try:
            contents = fp.namelist()
        finally:
            fp.close()

        contents = sorted(filter(None, map(os.path.basename, contents)))
        wanted = ['foo-0.1-py%s.%s.egg-info' % sys.version_info[:2], 'foo.py']
        if not sys.dont_write_bytecode:
            wanted.append('foo.%s.pyc' % sys.implementation.cache_tag)
        self.assertEqual(contents, sorted(wanted))

def test_suite():
    return unittest.makeSuite(BuildDumbTestCase)

if __name__ == '__main__':
    run_unittest(test_suite())
