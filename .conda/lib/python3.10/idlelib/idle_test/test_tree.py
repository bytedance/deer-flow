"Test tree. coverage 56%."

from idlelib import tree
import unittest
from test.support import requires
requires('gui')
from tkinter import Tk, EventType, SCROLL


class TreeTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        del cls.root

    def test_init(self):
        # Start with code slightly adapted from htest.
        sc = tree.ScrolledCanvas(
            self.root, bg="white", highlightthickness=0, takefocus=1)
        sc.frame.pack(expand=1, fill="both", side='left')
        item = tree.FileTreeItem(tree.ICONDIR)
        node = tree.TreeNode(sc.canvas, None, item)
        node.expand()


class TestScrollEvent(unittest.TestCase):

    def test_wheel_event(self):
        # Fake widget class containing `yview` only.
        class _Widget:
            def __init__(widget, *expected):
                widget.expected = expected
            def yview(widget, *args):
                self.assertTupleEqual(widget.expected, args)
        # Fake event class
        class _Event:
            pass
        #        (type, delta, num, amount)
        tests = ((EventType.MouseWheel, 120, -1, -5),
                 (EventType.MouseWheel, -120, -1, 5),
                 (EventType.ButtonPress, -1, 4, -5),
                 (EventType.ButtonPress, -1, 5, 5))

        event = _Event()
        for ty, delta, num, amount in tests:
            event.type = ty
            event.delta = delta
            event.num = num
            res = tree.wheel_event(event, _Widget(SCROLL, amount, "units"))
            self.assertEqual(res, "break")


if __name__ == '__main__':
    unittest.main(verbosity=2)
