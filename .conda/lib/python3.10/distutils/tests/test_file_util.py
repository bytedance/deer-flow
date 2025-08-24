"""Tests for distutils.file_util."""
import unittest
import os
import errno
from unittest.mock import patch

from distutils.file_util import move_file, copy_file
from distutils import log
from distutils.tests import support
from distutils.errors import DistutilsFileError
from test.support import run_unittest
from test.support.os_helper import unlink


class FileUtilTestCase(support.TempdirManager, unittest.TestCase):

    def _log(self, msg, *args):
        if len(args) > 0:
            self._logs.append(msg % args)
        else:
            self._logs.append(msg)

    def setUp(self):
        super(FileUtilTestCase, self).setUp()
        self._logs = []
        self.old_log = log.info
        log.info = self._log
        tmp_dir = self.mkdtemp()
        self.source = os.path.join(tmp_dir, 'f1')
        self.target = os.path.join(tmp_dir, 'f2')
        self.target_dir = os.path.join(tmp_dir, 'd1')

    def tearDown(self):
        log.info = self.old_log
        super(FileUtilTestCase, self).tearDown()

    def test_move_file_verbosity(self):
        f = open(self.source, 'w')
        try:
            f.write('some content')
        finally:
            f.close()

        move_file(self.source, self.target, verbose=0)
        wanted = []
        self.assertEqual(self._logs, wanted)

        # back to original state
        move_file(self.target, self.source, verbose=0)

        move_file(self.source, self.target, verbose=1)
        wanted = ['moving %s -> %s' % (self.source, self.target)]
        self.assertEqual(self._logs, wanted)

        # back to original state
        move_file(self.target, self.source, verbose=0)

        self._logs = []
        # now the target is a dir
        os.mkdir(self.target_dir)
        move_file(self.source, self.target_dir, verbose=1)
        wanted = ['moving %s -> %s' % (self.source, self.target_dir)]
        self.assertEqual(self._logs, wanted)

    def test_move_file_exception_unpacking_rename(self):
        # see issue 22182
        with patch("os.rename", side_effect=OSError("wrong", 1)), \
             self.assertRaises(DistutilsFileError):
            with open(self.source, 'w') as fobj:
                fobj.write('spam eggs')
            move_file(self.source, self.target, verbose=0)

    def test_move_file_exception_unpacking_unlink(self):
        # see issue 22182
        with patch("os.rename", side_effect=OSError(errno.EXDEV, "wrong")), \
             patch("os.unlink", side_effect=OSError("wrong", 1)), \
             self.assertRaises(DistutilsFileError):
            with open(self.source, 'w') as fobj:
                fobj.write('spam eggs')
            move_file(self.source, self.target, verbose=0)

    def test_copy_file_hard_link(self):
        with open(self.source, 'w') as f:
            f.write('some content')
        # Check first that copy_file() will not fall back on copying the file
        # instead of creating the hard link.
        try:
            os.link(self.source, self.target)
        except OSError as e:
            self.skipTest('os.link: %s' % e)
        else:
            unlink(self.target)
        st = os.stat(self.source)
        copy_file(self.source, self.target, link='hard')
        st2 = os.stat(self.source)
        st3 = os.stat(self.target)
        self.assertTrue(os.path.samestat(st, st2), (st, st2))
        self.assertTrue(os.path.samestat(st2, st3), (st2, st3))
        with open(self.source, 'r') as f:
            self.assertEqual(f.read(), 'some content')

    def test_copy_file_hard_link_failure(self):
        # If hard linking fails, copy_file() falls back on copying file
        # (some special filesystems don't support hard linking even under
        #  Unix, see issue #8876).
        with open(self.source, 'w') as f:
            f.write('some content')
        st = os.stat(self.source)
        with patch("os.link", side_effect=OSError(0, "linking unsupported")):
            copy_file(self.source, self.target, link='hard')
        st2 = os.stat(self.source)
        st3 = os.stat(self.target)
        self.assertTrue(os.path.samestat(st, st2), (st, st2))
        self.assertFalse(os.path.samestat(st2, st3), (st2, st3))
        for fn in (self.source, self.target):
            with open(fn, 'r') as f:
                self.assertEqual(f.read(), 'some content')


def test_suite():
    return unittest.makeSuite(FileUtilTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
