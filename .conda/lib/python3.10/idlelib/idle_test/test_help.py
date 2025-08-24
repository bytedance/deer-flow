"Test help, coverage 87%."

from idlelib import help
import unittest
from test.support import requires
requires('gui')
from os.path import abspath, dirname, join
from tkinter import Tk


class HelpFrameTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        "By itself, this tests that file parsed without exception."
        cls.root = root = Tk()
        root.withdraw()
        helpfile = join(dirname(dirname(abspath(__file__))), 'help.html')
        cls.frame = help.HelpFrame(root, helpfile)

    @classmethod
    def tearDownClass(cls):
        del cls.frame
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def test_line1(self):
        text = self.frame.text
        self.assertEqual(text.get('1.0', '1.end'), ' IDLE ')


if __name__ == '__main__':
    unittest.main(verbosity=2)
