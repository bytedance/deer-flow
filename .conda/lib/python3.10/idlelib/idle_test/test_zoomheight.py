"Test zoomheight, coverage 66%."
# Some code is system dependent.

from idlelib import zoomheight
import unittest
from test.support import requires
from tkinter import Tk
from idlelib.editor import EditorWindow


class Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.editwin = EditorWindow(root=cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.editwin._close()
        cls.root.update_idletasks()
        for id in cls.root.tk.call('after', 'info'):
            cls.root.after_cancel(id)  # Need for EditorWindow.
        cls.root.destroy()
        del cls.root

    def test_init(self):
        zoom = zoomheight.ZoomHeight(self.editwin)
        self.assertIs(zoom.editwin, self.editwin)

    def test_zoom_height_event(self):
        zoom = zoomheight.ZoomHeight(self.editwin)
        zoom.zoom_height_event()


if __name__ == '__main__':
    unittest.main(verbosity=2)
