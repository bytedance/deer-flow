"""Tests for distutils.pypirc.pypirc."""
import os
import unittest

from distutils.core import PyPIRCCommand
from distutils.core import Distribution
from distutils.log import set_threshold
from distutils.log import WARN

from distutils.tests import support
from test.support import run_unittest

PYPIRC = """\
[distutils]

index-servers =
    server1
    server2
    server3

[server1]
username:me
password:secret

[server2]
username:meagain
password: secret
realm:acme
repository:http://another.pypi/

[server3]
username:cbiggles
password:yh^%#rest-of-my-password
"""

PYPIRC_OLD = """\
[server-login]
username:tarek
password:secret
"""

WANTED = """\
[distutils]
index-servers =
    pypi

[pypi]
username:tarek
password:xxx
"""


class BasePyPIRCCommandTestCase(support.TempdirManager,
                            support.LoggingSilencer,
                            support.EnvironGuard,
                            unittest.TestCase):

    def setUp(self):
        """Patches the environment."""
        super(BasePyPIRCCommandTestCase, self).setUp()
        self.tmp_dir = self.mkdtemp()
        os.environ['HOME'] = self.tmp_dir
        os.environ['USERPROFILE'] = self.tmp_dir
        self.rc = os.path.join(self.tmp_dir, '.pypirc')
        self.dist = Distribution()

        class command(PyPIRCCommand):
            def __init__(self, dist):
                PyPIRCCommand.__init__(self, dist)
            def initialize_options(self):
                pass
            finalize_options = initialize_options

        self._cmd = command
        self.old_threshold = set_threshold(WARN)

    def tearDown(self):
        """Removes the patch."""
        set_threshold(self.old_threshold)
        super(BasePyPIRCCommandTestCase, self).tearDown()


class PyPIRCCommandTestCase(BasePyPIRCCommandTestCase):

    def test_server_registration(self):
        # This test makes sure PyPIRCCommand knows how to:
        # 1. handle several sections in .pypirc
        # 2. handle the old format

        # new format
        self.write_file(self.rc, PYPIRC)
        cmd = self._cmd(self.dist)
        config = cmd._read_pypirc()

        config = list(sorted(config.items()))
        waited = [('password', 'secret'), ('realm', 'pypi'),
                  ('repository', 'https://upload.pypi.org/legacy/'),
                  ('server', 'server1'), ('username', 'me')]
        self.assertEqual(config, waited)

        # old format
        self.write_file(self.rc, PYPIRC_OLD)
        config = cmd._read_pypirc()
        config = list(sorted(config.items()))
        waited = [('password', 'secret'), ('realm', 'pypi'),
                  ('repository', 'https://upload.pypi.org/legacy/'),
                  ('server', 'server-login'), ('username', 'tarek')]
        self.assertEqual(config, waited)

    def test_server_empty_registration(self):
        cmd = self._cmd(self.dist)
        rc = cmd._get_rc_file()
        self.assertFalse(os.path.exists(rc))
        cmd._store_pypirc('tarek', 'xxx')
        self.assertTrue(os.path.exists(rc))
        f = open(rc)
        try:
            content = f.read()
            self.assertEqual(content, WANTED)
        finally:
            f.close()

    def test_config_interpolation(self):
        # using the % character in .pypirc should not raise an error (#20120)
        self.write_file(self.rc, PYPIRC)
        cmd = self._cmd(self.dist)
        cmd.repository = 'server3'
        config = cmd._read_pypirc()

        config = list(sorted(config.items()))
        waited = [('password', 'yh^%#rest-of-my-password'), ('realm', 'pypi'),
                  ('repository', 'https://upload.pypi.org/legacy/'),
                  ('server', 'server3'), ('username', 'cbiggles')]
        self.assertEqual(config, waited)


def test_suite():
    return unittest.makeSuite(PyPIRCCommandTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
