"Test scrolledlist, coverage 38%."

from idlelib.scrolledlist import ScrolledList
import unittest
from test.support import requires
requires('gui')
from tkinter import Tk


class ScrolledListTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = Tk()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        del cls.root


    def test_init(self):
        ScrolledList(self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
