"Test window, coverage 47%."

from idlelib import window
import unittest
from test.support import requires
from tkinter import Tk


class WindowListTest(unittest.TestCase):

    def test_init(self):
        wl = window.WindowList()
        self.assertEqual(wl.dict, {})
        self.assertEqual(wl.callbacks, [])

    # Further tests need mock Window.


class ListedToplevelTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        window.registry = set()
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        window.registry = window.WindowList()
        cls.root.update_idletasks()
##        for id in cls.root.tk.call('after', 'info'):
##            cls.root.after_cancel(id)  # Need for EditorWindow.
        cls.root.destroy()
        del cls.root

    def test_init(self):

        win = window.ListedToplevel(self.root)
        self.assertIn(win, window.registry)
        self.assertEqual(win.focused_widget, win)


if __name__ == '__main__':
    unittest.main(verbosity=2)
