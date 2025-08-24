"Test redirector, coverage 100%."

from idlelib.redirector import WidgetRedirector
import unittest
from test.support import requires
from tkinter import Tk, Text, TclError
from idlelib.idle_test.mock_idle import Func


class InitCloseTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.text = Text(cls.root)

    @classmethod
    def tearDownClass(cls):
        del cls.text
        cls.root.destroy()
        del cls.root

    def test_init(self):
        redir = WidgetRedirector(self.text)
        self.assertEqual(redir.widget, self.text)
        self.assertEqual(redir.tk, self.text.tk)
        self.assertRaises(TclError, WidgetRedirector, self.text)
        redir.close()  # restore self.tk, self.text

    def test_close(self):
        redir = WidgetRedirector(self.text)
        redir.register('insert', Func)
        redir.close()
        self.assertEqual(redir._operations, {})
        self.assertFalse(hasattr(self.text, 'widget'))


class WidgetRedirectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.text = Text(cls.root)

    @classmethod
    def tearDownClass(cls):
        del cls.text
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

    def setUp(self):
        self.redir = WidgetRedirector(self.text)
        self.func = Func()
        self.orig_insert = self.redir.register('insert', self.func)
        self.text.insert('insert', 'asdf')  # leaves self.text empty

    def tearDown(self):
        self.text.delete('1.0', 'end')
        self.redir.close()

    def test_repr(self):  # partly for 100% coverage
        self.assertIn('Redirector', repr(self.redir))
        self.assertIn('Original', repr(self.orig_insert))

    def test_register(self):
        self.assertEqual(self.text.get('1.0', 'end'), '\n')
        self.assertEqual(self.func.args, ('insert', 'asdf'))
        self.assertIn('insert', self.redir._operations)
        self.assertIn('insert', self.text.__dict__)
        self.assertEqual(self.text.insert, self.func)

    def test_original_command(self):
        self.assertEqual(self.orig_insert.operation, 'insert')
        self.assertEqual(self.orig_insert.tk_call, self.text.tk.call)
        self.orig_insert('insert', 'asdf')
        self.assertEqual(self.text.get('1.0', 'end'), 'asdf\n')

    def test_unregister(self):
        self.assertIsNone(self.redir.unregister('invalid operation name'))
        self.assertEqual(self.redir.unregister('insert'), self.func)
        self.assertNotIn('insert', self.redir._operations)
        self.assertNotIn('insert', self.text.__dict__)

    def test_unregister_no_attribute(self):
        del self.text.insert
        self.assertEqual(self.redir.unregister('insert'), self.func)

    def test_dispatch_intercept(self):
        self.func.__init__(True)
        self.assertTrue(self.redir.dispatch('insert', False))
        self.assertFalse(self.func.args[0])

    def test_dispatch_bypass(self):
        self.orig_insert('insert', 'asdf')
        # tk.call returns '' where Python would return None
        self.assertEqual(self.redir.dispatch('delete', '1.0', 'end'), '')
        self.assertEqual(self.text.get('1.0', 'end'), '\n')

    def test_dispatch_error(self):
        self.func.__init__(TclError())
        self.assertEqual(self.redir.dispatch('insert', False), '')
        self.assertEqual(self.redir.dispatch('invalid'), '')

    def test_command_dispatch(self):
        # Test that .__init__ causes redirection of tk calls
        # through redir.dispatch
        self.root.call(self.text._w, 'insert', 'hello')
        self.assertEqual(self.func.args, ('hello',))
        self.assertEqual(self.text.get('1.0', 'end'), '\n')
        # Ensure that called through redir .dispatch and not through
        # self.text.insert by having mock raise TclError.
        self.func.__init__(TclError())
        self.assertEqual(self.root.call(self.text._w, 'insert', 'boo'), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
