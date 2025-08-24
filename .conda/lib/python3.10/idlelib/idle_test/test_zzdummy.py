"Test zzdummy, coverage 100%."

from idlelib import zzdummy
import unittest
from test.support import requires
from tkinter import Tk, Text
from unittest import mock
from idlelib import config
from idlelib import editor
from idlelib import format


usercfg = zzdummy.idleConf.userCfg
testcfg = {
    'main': config.IdleUserConfParser(''),
    'highlight': config.IdleUserConfParser(''),
    'keys': config.IdleUserConfParser(''),
    'extensions': config.IdleUserConfParser(''),
}
code_sample = """\

class C1:
    # Class comment.
    def __init__(self, a, b):
        self.a = a
        self.b = b
"""


class DummyEditwin:
    get_selection_indices = editor.EditorWindow.get_selection_indices
    def __init__(self, root, text):
        self.root = root
        self.top = root
        self.text = text
        self.fregion = format.FormatRegion(self)
        self.text.undo_block_start = mock.Mock()
        self.text.undo_block_stop = mock.Mock()


class ZZDummyTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        root = cls.root = Tk()
        root.withdraw()
        text = cls.text = Text(cls.root)
        cls.editor = DummyEditwin(root, text)
        zzdummy.idleConf.userCfg = testcfg

    @classmethod
    def tearDownClass(cls):
        zzdummy.idleConf.userCfg = usercfg
        del cls.editor, cls.text
        cls.root.update_idletasks()
        for id in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(id)  # Need for EditorWindow.
        cls.root.destroy()
        del cls.root

    def setUp(self):
        text = self.text
        text.insert('1.0', code_sample)
        text.undo_block_start.reset_mock()
        text.undo_block_stop.reset_mock()
        zz = self.zz = zzdummy.ZzDummy(self.editor)
        zzdummy.ZzDummy.ztext = '# ignore #'

    def tearDown(self):
        self.text.delete('1.0', 'end')
        del self.zz

    def checklines(self, text, value):
        # Verify that there are lines being checked.
        end_line = int(float(text.index('end')))

        # Check each line for the starting text.
        actual = []
        for line in range(1, end_line):
            txt = text.get(f'{line}.0', f'{line}.end')
            actual.append(txt.startswith(value))
        return actual

    def test_init(self):
        zz = self.zz
        self.assertEqual(zz.editwin, self.editor)
        self.assertEqual(zz.text, self.editor.text)

    def test_reload(self):
        self.assertEqual(self.zz.ztext, '# ignore #')
        testcfg['extensions'].SetOption('ZzDummy', 'z-text', 'spam')
        zzdummy.ZzDummy.reload()
        self.assertEqual(self.zz.ztext, 'spam')

    def test_z_in_event(self):
        eq = self.assertEqual
        zz = self.zz
        text = zz.text
        eq(self.zz.ztext, '# ignore #')

        # No lines have the leading text.
        expected = [False, False, False, False, False, False, False]
        actual = self.checklines(text, zz.ztext)
        eq(expected, actual)

        text.tag_add('sel', '2.0', '4.end')
        eq(zz.z_in_event(), 'break')
        expected = [False, True, True, True, False, False, False]
        actual = self.checklines(text, zz.ztext)
        eq(expected, actual)

        text.undo_block_start.assert_called_once()
        text.undo_block_stop.assert_called_once()

    def test_z_out_event(self):
        eq = self.assertEqual
        zz = self.zz
        text = zz.text
        eq(self.zz.ztext, '# ignore #')

        # Prepend text.
        text.tag_add('sel', '2.0', '5.end')
        zz.z_in_event()
        text.undo_block_start.reset_mock()
        text.undo_block_stop.reset_mock()

        # Select a few lines to remove text.
        text.tag_remove('sel', '1.0', 'end')
        text.tag_add('sel', '3.0', '4.end')
        eq(zz.z_out_event(), 'break')
        expected = [False, True, False, False, True, False, False]
        actual = self.checklines(text, zz.ztext)
        eq(expected, actual)

        text.undo_block_start.assert_called_once()
        text.undo_block_stop.assert_called_once()

    def test_roundtrip(self):
        # Insert and remove to all code should give back original text.
        zz = self.zz
        text = zz.text

        text.tag_add('sel', '1.0', 'end-1c')
        zz.z_in_event()
        zz.z_out_event()

        self.assertEqual(text.get('1.0', 'end-1c'), code_sample)


if __name__ == '__main__':
    unittest.main(verbosity=2)
