"Test statusbar, coverage 100%."

from idlelib import statusbar
import unittest
from test.support import requires
from tkinter import Tk


class Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def test_init(self):
        bar = statusbar.MultiStatusBar(self.root)
        self.assertEqual(bar.labels, {})

    def test_set_label(self):
        bar = statusbar.MultiStatusBar(self.root)
        bar.set_label('left', text='sometext', width=10)
        self.assertIn('left', bar.labels)
        left = bar.labels['left']
        self.assertEqual(left['text'], 'sometext')
        self.assertEqual(left['width'], 10)
        bar.set_label('left', text='revised text')
        self.assertEqual(left['text'], 'revised text')
        bar.set_label('right', text='correct text')
        self.assertEqual(bar.labels['right']['text'], 'correct text')


if __name__ == '__main__':
    unittest.main(verbosity=2)
