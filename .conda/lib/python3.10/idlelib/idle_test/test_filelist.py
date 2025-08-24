"Test filelist, coverage 19%."

from idlelib import filelist
import unittest
from test.support import requires
from tkinter import Tk

class FileListTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.update_idletasks()
        for id in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(id)
        cls.root.destroy()
        del cls.root

    def test_new_empty(self):
        flist = filelist.FileList(self.root)
        self.assertEqual(flist.root, self.root)
        e = flist.new()
        self.assertEqual(type(e), flist.EditorWindow)
        e._close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
