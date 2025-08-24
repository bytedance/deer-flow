"""Tests for distutils.extension."""
import unittest
import os
import warnings

from test.support import run_unittest
from test.support.warnings_helper import check_warnings
from distutils.extension import read_setup_file, Extension

class ExtensionTestCase(unittest.TestCase):

    def test_read_setup_file(self):
        # trying to read a Setup file
        # (sample extracted from the PyGame project)
        setup = os.path.join(os.path.dirname(__file__), 'Setup.sample')

        exts = read_setup_file(setup)
        names = [ext.name for ext in exts]
        names.sort()

        # here are the extensions read_setup_file should have created
        # out of the file
        wanted = ['_arraysurfarray', '_camera', '_numericsndarray',
                  '_numericsurfarray', 'base', 'bufferproxy', 'cdrom',
                  'color', 'constants', 'display', 'draw', 'event',
                  'fastevent', 'font', 'gfxdraw', 'image', 'imageext',
                  'joystick', 'key', 'mask', 'mixer', 'mixer_music',
                  'mouse', 'movie', 'overlay', 'pixelarray', 'pypm',
                  'rect', 'rwobject', 'scrap', 'surface', 'surflock',
                  'time', 'transform']

        self.assertEqual(names, wanted)

    def test_extension_init(self):
        # the first argument, which is the name, must be a string
        self.assertRaises(AssertionError, Extension, 1, [])
        ext = Extension('name', [])
        self.assertEqual(ext.name, 'name')

        # the second argument, which is the list of files, must
        # be a list of strings
        self.assertRaises(AssertionError, Extension, 'name', 'file')
        self.assertRaises(AssertionError, Extension, 'name', ['file', 1])
        ext = Extension('name', ['file1', 'file2'])
        self.assertEqual(ext.sources, ['file1', 'file2'])

        # others arguments have defaults
        for attr in ('include_dirs', 'define_macros', 'undef_macros',
                     'library_dirs', 'libraries', 'runtime_library_dirs',
                     'extra_objects', 'extra_compile_args', 'extra_link_args',
                     'export_symbols', 'swig_opts', 'depends'):
            self.assertEqual(getattr(ext, attr), [])

        self.assertEqual(ext.language, None)
        self.assertEqual(ext.optional, None)

        # if there are unknown keyword options, warn about them
        with check_warnings() as w:
            warnings.simplefilter('always')
            ext = Extension('name', ['file1', 'file2'], chic=True)

        self.assertEqual(len(w.warnings), 1)
        self.assertEqual(str(w.warnings[0].message),
                          "Unknown Extension options: 'chic'")

def test_suite():
    return unittest.makeSuite(ExtensionTestCase)

if __name__ == "__main__":
    run_unittest(test_suite())
