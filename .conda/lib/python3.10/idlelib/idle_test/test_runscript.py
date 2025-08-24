"Test runscript, coverage 16%."

from idlelib import runscript
import unittest
from test.support import requires
from tkinter import Tk
from idlelib.editor import EditorWindow


class ScriptBindingTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.update_idletasks()
        for id in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(id)  # Need for EditorWindow.
        cls.root.destroy()
        del cls.root

    def test_init(self):
        ew = EditorWindow(root=self.root)
        sb = runscript.ScriptBinding(ew)
        ew._close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
