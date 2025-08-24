# -*- coding: utf-8 -*-
"""Tests for distutils.archive_util."""
import unittest
import os
import sys
import tarfile
from os.path import splitdrive
import warnings

from distutils import archive_util
from distutils.archive_util import (check_archive_formats, make_tarball,
                                    make_zipfile, make_archive,
                                    ARCHIVE_FORMATS)
from distutils.spawn import find_executable, spawn
from distutils.tests import support
from test.support import run_unittest, patch
from test.support.os_helper import change_cwd
from test.support.warnings_helper import check_warnings

try:
    import grp
    import pwd
    UID_GID_SUPPORT = True
except ImportError:
    UID_GID_SUPPORT = False

try:
    import zipfile
    ZIP_SUPPORT = True
except ImportError:
    ZIP_SUPPORT = find_executable('zip')

try:
    import zlib
    ZLIB_SUPPORT = True
except ImportError:
    ZLIB_SUPPORT = False

try:
    import bz2
except ImportError:
    bz2 = None

try:
    import lzma
except ImportError:
    lzma = None

def can_fs_encode(filename):
    """
    Return True if the filename can be saved in the file system.
    """
    if os.path.supports_unicode_filenames:
        return True
    try:
        filename.encode(sys.getfilesystemencoding())
    except UnicodeEncodeError:
        return False
    return True


class ArchiveUtilTestCase(support.TempdirManager,
                          support.LoggingSilencer,
                          unittest.TestCase):

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_make_tarball(self, name='archive'):
        # creating something to tar
        tmpdir = self._create_files()
        self._make_tarball(tmpdir, name, '.tar.gz')
        # trying an uncompressed one
        self._make_tarball(tmpdir, name, '.tar', compress=None)

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_make_tarball_gzip(self):
        tmpdir = self._create_files()
        self._make_tarball(tmpdir, 'archive', '.tar.gz', compress='gzip')

    @unittest.skipUnless(bz2, 'Need bz2 support to run')
    def test_make_tarball_bzip2(self):
        tmpdir = self._create_files()
        self._make_tarball(tmpdir, 'archive', '.tar.bz2', compress='bzip2')

    @unittest.skipUnless(lzma, 'Need lzma support to run')
    def test_make_tarball_xz(self):
        tmpdir = self._create_files()
        self._make_tarball(tmpdir, 'archive', '.tar.xz', compress='xz')

    @unittest.skipUnless(can_fs_encode('årchiv'),
        'File system cannot handle this filename')
    def test_make_tarball_latin1(self):
        """
        Mirror test_make_tarball, except filename contains latin characters.
        """
        self.test_make_tarball('årchiv') # note this isn't a real word

    @unittest.skipUnless(can_fs_encode('のアーカイブ'),
        'File system cannot handle this filename')
    def test_make_tarball_extended(self):
        """
        Mirror test_make_tarball, except filename contains extended
        characters outside the latin charset.
        """
        self.test_make_tarball('のアーカイブ') # japanese for archive

    def _make_tarball(self, tmpdir, target_name, suffix, **kwargs):
        tmpdir2 = self.mkdtemp()
        unittest.skipUnless(splitdrive(tmpdir)[0] == splitdrive(tmpdir2)[0],
                            "source and target should be on same drive")

        base_name = os.path.join(tmpdir2, target_name)

        # working with relative paths to avoid tar warnings
        with change_cwd(tmpdir):
            make_tarball(splitdrive(base_name)[1], 'dist', **kwargs)

        # check if the compressed tarball was created
        tarball = base_name + suffix
        self.assertTrue(os.path.exists(tarball))
        self.assertEqual(self._tarinfo(tarball), self._created_files)

    def _tarinfo(self, path):
        tar = tarfile.open(path)
        try:
            names = tar.getnames()
            names.sort()
            return names
        finally:
            tar.close()

    _zip_created_files = ['dist/', 'dist/file1', 'dist/file2',
                          'dist/sub/', 'dist/sub/file3', 'dist/sub2/']
    _created_files = [p.rstrip('/') for p in _zip_created_files]

    def _create_files(self):
        # creating something to tar
        tmpdir = self.mkdtemp()
        dist = os.path.join(tmpdir, 'dist')
        os.mkdir(dist)
        self.write_file([dist, 'file1'], 'xxx')
        self.write_file([dist, 'file2'], 'xxx')
        os.mkdir(os.path.join(dist, 'sub'))
        self.write_file([dist, 'sub', 'file3'], 'xxx')
        os.mkdir(os.path.join(dist, 'sub2'))
        return tmpdir

    @unittest.skipUnless(find_executable('tar') and find_executable('gzip')
                         and ZLIB_SUPPORT,
                         'Need the tar, gzip and zlib command to run')
    def test_tarfile_vs_tar(self):
        tmpdir =  self._create_files()
        tmpdir2 = self.mkdtemp()
        base_name = os.path.join(tmpdir2, 'archive')
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            make_tarball(base_name, 'dist')
        finally:
            os.chdir(old_dir)

        # check if the compressed tarball was created
        tarball = base_name + '.tar.gz'
        self.assertTrue(os.path.exists(tarball))

        # now create another tarball using `tar`
        tarball2 = os.path.join(tmpdir, 'archive2.tar.gz')
        tar_cmd = ['tar', '-cf', 'archive2.tar', 'dist']
        gzip_cmd = ['gzip', '-f', '-9', 'archive2.tar']
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            spawn(tar_cmd)
            spawn(gzip_cmd)
        finally:
            os.chdir(old_dir)

        self.assertTrue(os.path.exists(tarball2))
        # let's compare both tarballs
        self.assertEqual(self._tarinfo(tarball), self._created_files)
        self.assertEqual(self._tarinfo(tarball2), self._created_files)

        # trying an uncompressed one
        base_name = os.path.join(tmpdir2, 'archive')
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            make_tarball(base_name, 'dist', compress=None)
        finally:
            os.chdir(old_dir)
        tarball = base_name + '.tar'
        self.assertTrue(os.path.exists(tarball))

        # now for a dry_run
        base_name = os.path.join(tmpdir2, 'archive')
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            make_tarball(base_name, 'dist', compress=None, dry_run=True)
        finally:
            os.chdir(old_dir)
        tarball = base_name + '.tar'
        self.assertTrue(os.path.exists(tarball))

    @unittest.skipUnless(find_executable('compress'),
                         'The compress program is required')
    def test_compress_deprecated(self):
        tmpdir =  self._create_files()
        base_name = os.path.join(self.mkdtemp(), 'archive')

        # using compress and testing the PendingDeprecationWarning
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            with check_warnings() as w:
                warnings.simplefilter("always")
                make_tarball(base_name, 'dist', compress='compress')
        finally:
            os.chdir(old_dir)
        tarball = base_name + '.tar.Z'
        self.assertTrue(os.path.exists(tarball))
        self.assertEqual(len(w.warnings), 1)

        # same test with dry_run
        os.remove(tarball)
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        try:
            with check_warnings() as w:
                warnings.simplefilter("always")
                make_tarball(base_name, 'dist', compress='compress',
                             dry_run=True)
        finally:
            os.chdir(old_dir)
        self.assertFalse(os.path.exists(tarball))
        self.assertEqual(len(w.warnings), 1)

    @unittest.skipUnless(ZIP_SUPPORT and ZLIB_SUPPORT,
                         'Need zip and zlib support to run')
    def test_make_zipfile(self):
        # creating something to tar
        tmpdir = self._create_files()
        base_name = os.path.join(self.mkdtemp(), 'archive')
        with change_cwd(tmpdir):
            make_zipfile(base_name, 'dist')

        # check if the compressed tarball was created
        tarball = base_name + '.zip'
        self.assertTrue(os.path.exists(tarball))
        with zipfile.ZipFile(tarball) as zf:
            self.assertEqual(sorted(zf.namelist()), self._zip_created_files)

    @unittest.skipUnless(ZIP_SUPPORT, 'Need zip support to run')
    def test_make_zipfile_no_zlib(self):
        patch(self, archive_util.zipfile, 'zlib', None)  # force zlib ImportError

        called = []
        zipfile_class = zipfile.ZipFile
        def fake_zipfile(*a, **kw):
            if kw.get('compression', None) == zipfile.ZIP_STORED:
                called.append((a, kw))
            return zipfile_class(*a, **kw)

        patch(self, archive_util.zipfile, 'ZipFile', fake_zipfile)

        # create something to tar and compress
        tmpdir = self._create_files()
        base_name = os.path.join(self.mkdtemp(), 'archive')
        with change_cwd(tmpdir):
            make_zipfile(base_name, 'dist')

        tarball = base_name + '.zip'
        self.assertEqual(called,
                         [((tarball, "w"), {'compression': zipfile.ZIP_STORED})])
        self.assertTrue(os.path.exists(tarball))
        with zipfile.ZipFile(tarball) as zf:
            self.assertEqual(sorted(zf.namelist()), self._zip_created_files)

    def test_check_archive_formats(self):
        self.assertEqual(check_archive_formats(['gztar', 'xxx', 'zip']),
                         'xxx')
        self.assertIsNone(check_archive_formats(['gztar', 'bztar', 'xztar',
                                                 'ztar', 'tar', 'zip']))

    def test_make_archive(self):
        tmpdir = self.mkdtemp()
        base_name = os.path.join(tmpdir, 'archive')
        self.assertRaises(ValueError, make_archive, base_name, 'xxx')

    def test_make_archive_cwd(self):
        current_dir = os.getcwd()
        def _breaks(*args, **kw):
            raise RuntimeError()
        ARCHIVE_FORMATS['xxx'] = (_breaks, [], 'xxx file')
        try:
            try:
                make_archive('xxx', 'xxx', root_dir=self.mkdtemp())
            except:
                pass
            self.assertEqual(os.getcwd(), current_dir)
        finally:
            del ARCHIVE_FORMATS['xxx']

    def test_make_archive_tar(self):
        base_dir =  self._create_files()
        base_name = os.path.join(self.mkdtemp() , 'archive')
        res = make_archive(base_name, 'tar', base_dir, 'dist')
        self.assertTrue(os.path.exists(res))
        self.assertEqual(os.path.basename(res), 'archive.tar')
        self.assertEqual(self._tarinfo(res), self._created_files)

    @unittest.skipUnless(ZLIB_SUPPORT, 'Need zlib support to run')
    def test_make_archive_gztar(self):
        base_dir =  self._create_files()
        base_name = os.path.join(self.mkdtemp() , 'archive')
        res = make_archive(base_name, 'gztar', base_dir, 'dist')
        self.assertTrue(os.path.exists(res))
        self.assertEqual(os.path.basename(res), 'archive.tar.gz')
        self.assertEqual(self._tarinfo(res), self._created_files)

    @unittest.skipUnless(bz2, 'Need bz2 support to run')
    def test_make_archive_bztar(self):
        base_dir =  self._create_files()
        base_name = os.path.join(self.mkdtemp() , 'archive')
        res = make_archive(base_name, 'bztar', base_dir, 'dist')
        self.assertTrue(os.path.exists(res))
        self.assertEqual(os.path.basename(res), 'archive.tar.bz2')
        self.assertEqual(self._tarinfo(res), self._created_files)

    @unittest.skipUnless(lzma, 'Need xz support to run')
    def test_make_archive_xztar(self):
        base_dir =  self._create_files()
        base_name = os.path.join(self.mkdtemp() , 'archive')
        res = make_archive(base_name, 'xztar', base_dir, 'dist')
        self.assertTrue(os.path.exists(res))
        self.assertEqual(os.path.basename(res), 'archive.tar.xz')
        self.assertEqual(self._tarinfo(res), self._created_files)

    def test_make_archive_owner_group(self):
        # testing make_archive with owner and group, with various combinations
        # this works even if there's not gid/uid support
        if UID_GID_SUPPORT:
            group = grp.getgrgid(0)[0]
            owner = pwd.getpwuid(0)[0]
        else:
            group = owner = 'root'

        base_dir =  self._create_files()
        root_dir = self.mkdtemp()
        base_name = os.path.join(self.mkdtemp() , 'archive')
        res = make_archive(base_name, 'zip', root_dir, base_dir, owner=owner,
                           group=group)
        self.assertTrue(os.path.exists(res))

        res = make_archive(base_name, 'zip', root_dir, base_dir)
        self.assertTrue(os.path.exists(res))

        res = make_archive(base_name, 'tar', root_dir, base_dir,
                           owner=owner, group=group)
        self.assertTrue(os.path.exists(res))

        res = make_archive(base_name, 'tar', root_dir, base_dir,
                           owner='kjhkjhkjg', group='oihohoh')
        self.assertTrue(os.path.exists(res))

    @unittest.skipUnless(ZLIB_SUPPORT, "Requires zlib")
    @unittest.skipUnless(UID_GID_SUPPORT, "Requires grp and pwd support")
    def test_tarfile_root_owner(self):
        tmpdir =  self._create_files()
        base_name = os.path.join(self.mkdtemp(), 'archive')
        old_dir = os.getcwd()
        os.chdir(tmpdir)
        group = grp.getgrgid(0)[0]
        owner = pwd.getpwuid(0)[0]
        try:
            archive_name = make_tarball(base_name, 'dist', compress=None,
                                        owner=owner, group=group)
        finally:
            os.chdir(old_dir)

        # check if the compressed tarball was created
        self.assertTrue(os.path.exists(archive_name))

        # now checks the rights
        archive = tarfile.open(archive_name)
        try:
            for member in archive.getmembers():
                self.assertEqual(member.uid, 0)
                self.assertEqual(member.gid, 0)
        finally:
            archive.close()

def test_suite():
    return unittest.makeSuite(ArchiveUtilTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
