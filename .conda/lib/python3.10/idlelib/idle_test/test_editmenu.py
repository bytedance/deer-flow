'''Test (selected) IDLE Edit menu items.

Edit modules have their own test files
'''
from test.support import requires
requires('gui')
import tkinter as tk
from tkinter import ttk
import unittest
from idlelib import pyshell

class PasteTest(unittest.TestCase):
    '''Test pasting into widgets that allow pasting.

    On X11, replacing selections requires tk fix.
    '''
    @classmethod
    def setUpClass(cls):
        cls.root = root = tk.Tk()
        cls.root.withdraw()
        pyshell.fix_x11_paste(root)
        cls.text = tk.Text(root)
        cls.entry = tk.Entry(root)
        cls.tentry = ttk.Entry(root)
        cls.spin = tk.Spinbox(root)
        root.clipboard_clear()
        root.clipboard_append('two')

    @classmethod
    def tearDownClass(cls):
        del cls.text, cls.entry, cls.tentry
        cls.root.clipboard_clear()
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def test_paste_text(self):
        "Test pasting into text with and without a selection."
        text = self.text
        for tag, ans in ('', 'onetwo\n'), ('sel', 'two\n'):
            with self.subTest(tag=tag, ans=ans):
                text.delete('1.0', 'end')
                text.insert('1.0', 'one', tag)
                text.event_generate('<<Paste>>')
                self.assertEqual(text.get('1.0', 'end'), ans)

    def test_paste_entry(self):
        "Test pasting into an entry with and without a selection."
        # Generated <<Paste>> fails for tk entry without empty select
        # range for 'no selection'.  Live widget works fine.
        for entry in self.entry, self.tentry:
            for end, ans in (0, 'onetwo'), ('end', 'two'):
                with self.subTest(entry=entry, end=end, ans=ans):
                    entry.delete(0, 'end')
                    entry.insert(0, 'one')
                    entry.select_range(0, end)
                    entry.event_generate('<<Paste>>')
                    self.assertEqual(entry.get(), ans)

    def test_paste_spin(self):
        "Test pasting into a spinbox with and without a selection."
        # See note above for entry.
        spin = self.spin
        for end, ans in (0, 'onetwo'), ('end', 'two'):
            with self.subTest(end=end, ans=ans):
                spin.delete(0, 'end')
                spin.insert(0, 'one')
                spin.selection('range', 0, end)  # see note
                spin.event_generate('<<Paste>>')
                self.assertEqual(spin.get(), ans)


if __name__ == '__main__':
    unittest.main(verbosity=2)
