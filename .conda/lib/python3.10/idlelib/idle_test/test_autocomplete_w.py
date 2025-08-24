"Test autocomplete_w, coverage 11%."

import unittest
from test.support import requires
from tkinter import Tk, Text

import idlelib.autocomplete_w as acw


class AutoCompleteWindowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.text = Text(cls.root)
        cls.acw = acw.AutoCompleteWindow(cls.text, tags=None)

    @classmethod
    def tearDownClass(cls):
        del cls.text, cls.acw
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def test_init(self):
        self.assertEqual(self.acw.widget, self.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
