"Test outwin, coverage 76%."

from idlelib import outwin
import unittest
from test.support import requires
from tkinter import Tk, Text
from idlelib.idle_test.mock_tk import Mbox_func
from idlelib.idle_test.mock_idle import Func
from unittest import mock


class OutputWindowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        root = cls.root = Tk()
        root.withdraw()
        w = cls.window = outwin.OutputWindow(None, None, None, root)
        cls.text = w.text = Text(root)

    @classmethod
    def tearDownClass(cls):
        cls.window.close()
        del cls.text, cls.window
        cls.root.destroy()
        del cls.root

    def setUp(self):
        self.text.delete('1.0', 'end')

    def test_ispythonsource(self):
        # OutputWindow overrides ispythonsource to always return False.
        w = self.window
        self.assertFalse(w.ispythonsource('test.txt'))
        self.assertFalse(w.ispythonsource(__file__))

    def test_window_title(self):
        self.assertEqual(self.window.top.title(), 'Output')

    def test_maybesave(self):
        w = self.window
        eq = self.assertEqual
        w.get_saved = Func()

        w.get_saved.result = False
        eq(w.maybesave(), 'no')
        eq(w.get_saved.called, 1)

        w.get_saved.result = True
        eq(w.maybesave(), 'yes')
        eq(w.get_saved.called, 2)
        del w.get_saved

    def test_write(self):
        eq = self.assertEqual
        delete = self.text.delete
        get = self.text.get
        write = self.window.write

        # No new line - insert stays on same line.
        delete('1.0', 'end')
        test_text = 'test text'
        eq(write(test_text), len(test_text))
        eq(get('1.0', '1.end'), 'test text')
        eq(get('insert linestart', 'insert lineend'), 'test text')

        # New line - insert moves to next line.
        delete('1.0', 'end')
        test_text = 'test text\n'
        eq(write(test_text), len(test_text))
        eq(get('1.0', '1.end'), 'test text')
        eq(get('insert linestart', 'insert lineend'), '')

        # Text after new line is tagged for second line of Text widget.
        delete('1.0', 'end')
        test_text = 'test text\nLine 2'
        eq(write(test_text), len(test_text))
        eq(get('1.0', '1.end'), 'test text')
        eq(get('2.0', '2.end'), 'Line 2')
        eq(get('insert linestart', 'insert lineend'), 'Line 2')

        # Test tags.
        delete('1.0', 'end')
        test_text = 'test text\n'
        test_text2 = 'Line 2\n'
        eq(write(test_text, tags='mytag'), len(test_text))
        eq(write(test_text2, tags='secondtag'), len(test_text2))
        eq(get('mytag.first', 'mytag.last'), test_text)
        eq(get('secondtag.first', 'secondtag.last'), test_text2)
        eq(get('1.0', '1.end'), test_text.rstrip('\n'))
        eq(get('2.0', '2.end'), test_text2.rstrip('\n'))

    def test_writelines(self):
        eq = self.assertEqual
        get = self.text.get
        writelines = self.window.writelines

        writelines(('Line 1\n', 'Line 2\n', 'Line 3\n'))
        eq(get('1.0', '1.end'), 'Line 1')
        eq(get('2.0', '2.end'), 'Line 2')
        eq(get('3.0', '3.end'), 'Line 3')
        eq(get('insert linestart', 'insert lineend'), '')

    def test_goto_file_line(self):
        eq = self.assertEqual
        w = self.window
        text = self.text

        w.flist = mock.Mock()
        gfl = w.flist.gotofileline = Func()
        showerror = w.showerror = Mbox_func()

        # No file/line number.
        w.write('Not a file line')
        self.assertIsNone(w.goto_file_line())
        eq(gfl.called, 0)
        eq(showerror.title, 'No special line')

        # Current file/line number.
        w.write(f'{str(__file__)}: 42: spam\n')
        w.write(f'{str(__file__)}: 21: spam')
        self.assertIsNone(w.goto_file_line())
        eq(gfl.args, (str(__file__), 21))

        # Previous line has file/line number.
        text.delete('1.0', 'end')
        w.write(f'{str(__file__)}: 42: spam\n')
        w.write('Not a file line')
        self.assertIsNone(w.goto_file_line())
        eq(gfl.args, (str(__file__), 42))

        del w.flist.gotofileline, w.showerror


class ModuleFunctionTest(unittest.TestCase):

    @classmethod
    def setUp(cls):
        outwin.file_line_progs = None

    def test_compile_progs(self):
        outwin.compile_progs()
        for pat, regex in zip(outwin.file_line_pats, outwin.file_line_progs):
            self.assertEqual(regex.pattern, pat)

    @mock.patch('builtins.open')
    def test_file_line_helper(self, mock_open):
        flh = outwin.file_line_helper
        test_lines = (
            (r'foo file "testfile1", line 42, bar', ('testfile1', 42)),
            (r'foo testfile2(21) bar', ('testfile2', 21)),
            (r'  testfile3  : 42: foo bar\n', ('  testfile3  ', 42)),
            (r'foo testfile4.py :1: ', ('foo testfile4.py ', 1)),
            ('testfile5: \u19D4\u19D2: ', ('testfile5', 42)),
            (r'testfile6: 42', None),       # only one `:`
            (r'testfile7 42 text', None)    # no separators
            )
        for line, expected_output in test_lines:
            self.assertEqual(flh(line), expected_output)
            if expected_output:
                mock_open.assert_called_with(expected_output[0], 'r')


if __name__ == '__main__':
    unittest.main(verbosity=2)
