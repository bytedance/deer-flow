" Test history, coverage 100%."

from idlelib.history import History
import unittest
from test.support import requires

import tkinter as tk
from tkinter import Text as tkText
from idlelib.idle_test.mock_tk import Text as mkText
from idlelib.config import idleConf

line1 = 'a = 7'
line2 = 'b = a'


class StoreTest(unittest.TestCase):
    '''Tests History.__init__ and History.store with mock Text'''

    @classmethod
    def setUpClass(cls):
        cls.text = mkText()
        cls.history = History(cls.text)

    def tearDown(self):
        self.text.delete('1.0', 'end')
        self.history.history = []

    def test_init(self):
        self.assertIs(self.history.text, self.text)
        self.assertEqual(self.history.history, [])
        self.assertIsNone(self.history.prefix)
        self.assertIsNone(self.history.pointer)
        self.assertEqual(self.history.cyclic,
                idleConf.GetOption("main", "History",  "cyclic", 1, "bool"))

    def test_store_short(self):
        self.history.store('a')
        self.assertEqual(self.history.history, [])
        self.history.store('  a  ')
        self.assertEqual(self.history.history, [])

    def test_store_dup(self):
        self.history.store(line1)
        self.assertEqual(self.history.history, [line1])
        self.history.store(line2)
        self.assertEqual(self.history.history, [line1, line2])
        self.history.store(line1)
        self.assertEqual(self.history.history, [line2, line1])

    def test_store_reset(self):
        self.history.prefix = line1
        self.history.pointer = 0
        self.history.store(line2)
        self.assertIsNone(self.history.prefix)
        self.assertIsNone(self.history.pointer)


class TextWrapper:
    def __init__(self, master):
        self.text = tkText(master=master)
        self._bell = False
    def __getattr__(self, name):
        return getattr(self.text, name)
    def bell(self):
        self._bell = True


class FetchTest(unittest.TestCase):
    '''Test History.fetch with wrapped tk.Text.
    '''
    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = tk.Tk()
        cls.root.withdraw()

    def setUp(self):
        self.text = text = TextWrapper(self.root)
        text.insert('1.0', ">>> ")
        text.mark_set('iomark', '1.4')
        text.mark_gravity('iomark', 'left')
        self.history = History(text)
        self.history.history = [line1, line2]

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()
        del cls.root

    def fetch_test(self, reverse, line, prefix, index, *, bell=False):
        # Perform one fetch as invoked by Alt-N or Alt-P
        # Test the result. The line test is the most important.
        # The last two are diagnostic of fetch internals.
        History = self.history
        History.fetch(reverse)

        Equal = self.assertEqual
        Equal(self.text.get('iomark', 'end-1c'), line)
        Equal(self.text._bell, bell)
        if bell:
            self.text._bell = False
        Equal(History.prefix, prefix)
        Equal(History.pointer, index)
        Equal(self.text.compare("insert", '==', "end-1c"), 1)

    def test_fetch_prev_cyclic(self):
        prefix = ''
        test = self.fetch_test
        test(True, line2, prefix, 1)
        test(True, line1, prefix, 0)
        test(True, prefix, None, None, bell=True)

    def test_fetch_next_cyclic(self):
        prefix = ''
        test  = self.fetch_test
        test(False, line1, prefix, 0)
        test(False, line2, prefix, 1)
        test(False, prefix, None, None, bell=True)

    # Prefix 'a' tests skip line2, which starts with 'b'
    def test_fetch_prev_prefix(self):
        prefix = 'a'
        self.text.insert('iomark', prefix)
        self.fetch_test(True, line1, prefix, 0)
        self.fetch_test(True, prefix, None, None, bell=True)

    def test_fetch_next_prefix(self):
        prefix = 'a'
        self.text.insert('iomark', prefix)
        self.fetch_test(False, line1, prefix, 0)
        self.fetch_test(False, prefix, None, None, bell=True)

    def test_fetch_prev_noncyclic(self):
        prefix = ''
        self.history.cyclic = False
        test = self.fetch_test
        test(True, line2, prefix, 1)
        test(True, line1, prefix, 0)
        test(True, line1, prefix, 0, bell=True)

    def test_fetch_next_noncyclic(self):
        prefix = ''
        self.history.cyclic = False
        test  = self.fetch_test
        test(False, prefix, None, None, bell=True)
        test(True, line2, prefix, 1)
        test(False, prefix, None, None, bell=True)
        test(False, prefix, None, None, bell=True)

    def test_fetch_cursor_move(self):
        # Move cursor after fetch
        self.history.fetch(reverse=True)  # initialization
        self.text.mark_set('insert', 'iomark')
        self.fetch_test(True, line2, None, None, bell=True)

    def test_fetch_edit(self):
        # Edit after fetch
        self.history.fetch(reverse=True)  # initialization
        self.text.delete('iomark', 'insert', )
        self.text.insert('iomark', 'a =')
        self.fetch_test(True, line1, 'a =', 0)  # prefix is reset

    def test_history_prev_next(self):
        # Minimally test functions bound to events
        self.history.history_prev('dummy event')
        self.assertEqual(self.history.pointer, 1)
        self.history.history_next('dummy event')
        self.assertEqual(self.history.pointer, None)


if __name__ == '__main__':
    unittest.main(verbosity=2, exit=2)
