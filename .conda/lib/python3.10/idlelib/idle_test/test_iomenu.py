"Test , coverage 17%."

from idlelib import iomenu
import unittest
from test.support import requires
from tkinter import Tk
from idlelib.editor import EditorWindow
from idlelib import util
from idlelib.idle_test.mock_idle import Func


class IOBindingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.editwin = EditorWindow(root=cls.root)
        cls.io = iomenu.IOBinding(cls.editwin)

    @classmethod
    def tearDownClass(cls):
        cls.io.close()
        cls.editwin._close()
        del cls.editwin
        cls.root.update_idletasks()
        for id in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(id)  # Need for EditorWindow.
        cls.root.destroy()
        del cls.root

    def test_init(self):
        self.assertIs(self.io.editwin, self.editwin)

    def test_fixnewlines_end(self):
        eq = self.assertEqual
        io = self.io
        fix = io.fixnewlines
        text = io.editwin.text

        # Make the editor temporarily look like Shell.
        self.editwin.interp = None
        shelltext = '>>> if 1'
        self.editwin.get_prompt_text = Func(result=shelltext)
        eq(fix(), shelltext)  # Get... call and '\n' not added.
        del self.editwin.interp, self.editwin.get_prompt_text

        text.insert(1.0, 'a')
        eq(fix(), 'a'+io.eol_convention)
        eq(text.get('1.0', 'end-1c'), 'a\n')
        eq(fix(), 'a'+io.eol_convention)


def _extension_in_filetypes(extension):
    return any(
        f'*{extension}' in filetype_tuple[1]
        for filetype_tuple in iomenu.IOBinding.filetypes
    )


class FiletypesTest(unittest.TestCase):
    def test_python_source_files(self):
        for extension in util.py_extensions:
            with self.subTest(extension=extension):
                self.assertTrue(
                    _extension_in_filetypes(extension)
                )

    def test_text_files(self):
        self.assertTrue(_extension_in_filetypes('.txt'))

    def test_all_files(self):
        self.assertTrue(_extension_in_filetypes(''))


if __name__ == '__main__':
    unittest.main(verbosity=2)
