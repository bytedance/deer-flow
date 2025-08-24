"""Test parenmatch, coverage 91%.

This must currently be a gui test because ParenMatch methods use
several text methods not defined on idlelib.idle_test.mock_tk.Text.
"""
from idlelib.parenmatch import ParenMatch
from test.support import requires
requires('gui')

import unittest
from unittest.mock import Mock
from tkinter import Tk, Text


class DummyEditwin:
    def __init__(self, text):
        self.text = text
        self.indentwidth = 8
        self.tabwidth = 8
        self.prompt_last_line = '>>>' # Currently not used by parenmatch.


class ParenMatchTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = Tk()
        cls.root.withdraw()
        cls.text = Text(cls.root)
        cls.editwin = DummyEditwin(cls.text)
        cls.editwin.text_frame = Mock()

    @classmethod
    def tearDownClass(cls):
        del cls.text, cls.editwin
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def tearDown(self):
        self.text.delete('1.0', 'end')

    def get_parenmatch(self):
        pm = ParenMatch(self.editwin)
        pm.bell = lambda: None
        return pm

    def test_paren_styles(self):
        """
        Test ParenMatch with each style.
        """
        text = self.text
        pm = self.get_parenmatch()
        for style, range1, range2 in (
                ('opener', ('1.10', '1.11'), ('1.10', '1.11')),
                ('default',('1.10', '1.11'),('1.10', '1.11')),
                ('parens', ('1.14', '1.15'), ('1.15', '1.16')),
                ('expression', ('1.10', '1.15'), ('1.10', '1.16'))):
            with self.subTest(style=style):
                text.delete('1.0', 'end')
                pm.STYLE = style
                text.insert('insert', 'def foobar(a, b')

                pm.flash_paren_event('event')
                self.assertIn('<<parenmatch-check-restore>>', text.event_info())
                if style == 'parens':
                    self.assertTupleEqual(text.tag_nextrange('paren', '1.0'),
                                          ('1.10', '1.11'))
                self.assertTupleEqual(
                        text.tag_prevrange('paren', 'end'), range1)

                text.insert('insert', ')')
                pm.restore_event()
                self.assertNotIn('<<parenmatch-check-restore>>',
                                 text.event_info())
                self.assertEqual(text.tag_prevrange('paren', 'end'), ())

                pm.paren_closed_event('event')
                self.assertTupleEqual(
                        text.tag_prevrange('paren', 'end'), range2)

    def test_paren_corner(self):
        """
        Test corner cases in flash_paren_event and paren_closed_event.

        Force execution of conditional expressions and alternate paths.
        """
        text = self.text
        pm = self.get_parenmatch()

        text.insert('insert', '# Comment.)')
        pm.paren_closed_event('event')

        text.insert('insert', '\ndef')
        pm.flash_paren_event('event')
        pm.paren_closed_event('event')

        text.insert('insert', ' a, *arg)')
        pm.paren_closed_event('event')

    def test_handle_restore_timer(self):
        pm = self.get_parenmatch()
        pm.restore_event = Mock()
        pm.handle_restore_timer(0)
        self.assertTrue(pm.restore_event.called)
        pm.restore_event.reset_mock()
        pm.handle_restore_timer(1)
        self.assertFalse(pm.restore_event.called)


if __name__ == '__main__':
    unittest.main(verbosity=2)
