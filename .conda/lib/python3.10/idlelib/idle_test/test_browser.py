"Test browser, coverage 90%."

from idlelib import browser
from test.support import requires
import unittest
from unittest import mock
from idlelib.idle_test.mock_idle import Func
from idlelib.util import py_extensions

from collections import deque
import os.path
import pyclbr
from tkinter import Tk

from idlelib.tree import TreeNode


class ModuleBrowserTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.mb = browser.ModuleBrowser(cls.root, __file__, _utest=True)

    @classmethod
    def tearDownClass(cls):
        cls.mb.close()
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root, cls.mb

    def test_init(self):
        mb = self.mb
        eq = self.assertEqual
        eq(mb.path, __file__)
        eq(pyclbr._modules, {})
        self.assertIsInstance(mb.node, TreeNode)
        self.assertIsNotNone(browser.file_open)

    def test_settitle(self):
        mb = self.mb
        self.assertIn(os.path.basename(__file__), mb.top.title())
        self.assertEqual(mb.top.iconname(), 'Module Browser')

    def test_rootnode(self):
        mb = self.mb
        rn = mb.rootnode()
        self.assertIsInstance(rn, browser.ModuleBrowserTreeItem)

    def test_close(self):
        mb = self.mb
        mb.top.destroy = Func()
        mb.node.destroy = Func()
        mb.close()
        self.assertTrue(mb.top.destroy.called)
        self.assertTrue(mb.node.destroy.called)
        del mb.top.destroy, mb.node.destroy

    def test_is_browseable_extension(self):
        path = "/path/to/file"
        for ext in py_extensions:
            with self.subTest(ext=ext):
                filename = f'{path}{ext}'
                actual = browser.is_browseable_extension(filename)
                expected = ext not in browser.browseable_extension_blocklist
                self.assertEqual(actual, expected)


# Nested tree same as in test_pyclbr.py except for supers on C0. C1.
mb = pyclbr
module, fname = 'test', 'test.py'
C0 = mb.Class(module, 'C0', ['base'], fname, 1, end_lineno=9)
F1 = mb._nest_function(C0, 'F1', 3, 5)
C1 = mb._nest_class(C0, 'C1', 6, 9, [''])
C2 = mb._nest_class(C1, 'C2', 7, 9)
F3 = mb._nest_function(C2, 'F3', 9, 9)
f0 = mb.Function(module, 'f0', fname, 11, end_lineno=15)
f1 = mb._nest_function(f0, 'f1', 12, 14)
f2 = mb._nest_function(f1, 'f2', 13, 13)
c1 = mb._nest_class(f0, 'c1', 15, 15)
mock_pyclbr_tree = {'C0': C0, 'f0': f0}

# Adjust C0.name, C1.name so tests do not depend on order.
browser.transform_children(mock_pyclbr_tree, 'test')  # C0(base)
browser.transform_children(C0.children)  # C1()

# The class below checks that the calls above are correct
# and that duplicate calls have no effect.


class TransformChildrenTest(unittest.TestCase):

    def test_transform_module_children(self):
        eq = self.assertEqual
        transform = browser.transform_children
        # Parameter matches tree module.
        tcl = list(transform(mock_pyclbr_tree, 'test'))
        eq(tcl, [C0, f0])
        eq(tcl[0].name, 'C0(base)')
        eq(tcl[1].name, 'f0')
        # Check that second call does not change suffix.
        tcl = list(transform(mock_pyclbr_tree, 'test'))
        eq(tcl[0].name, 'C0(base)')
        # Nothing to traverse if parameter name isn't same as tree module.
        tcl = list(transform(mock_pyclbr_tree, 'different name'))
        eq(tcl, [])

    def test_transform_node_children(self):
        eq = self.assertEqual
        transform = browser.transform_children
        # Class with two children, one name altered.
        tcl = list(transform(C0.children))
        eq(tcl, [F1, C1])
        eq(tcl[0].name, 'F1')
        eq(tcl[1].name, 'C1()')
        tcl = list(transform(C0.children))
        eq(tcl[1].name, 'C1()')
        # Function with two children.
        eq(list(transform(f0.children)), [f1, c1])


class ModuleBrowserTreeItemTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.mbt = browser.ModuleBrowserTreeItem(fname)

    def test_init(self):
        self.assertEqual(self.mbt.file, fname)

    def test_gettext(self):
        self.assertEqual(self.mbt.GetText(), fname)

    def test_geticonname(self):
        self.assertEqual(self.mbt.GetIconName(), 'python')

    def test_isexpandable(self):
        self.assertTrue(self.mbt.IsExpandable())

    def test_listchildren(self):
        save_rex = browser.pyclbr.readmodule_ex
        save_tc = browser.transform_children
        browser.pyclbr.readmodule_ex = Func(result=mock_pyclbr_tree)
        browser.transform_children = Func(result=[f0, C0])
        try:
            self.assertEqual(self.mbt.listchildren(), [f0, C0])
        finally:
            browser.pyclbr.readmodule_ex = save_rex
            browser.transform_children = save_tc

    def test_getsublist(self):
        mbt = self.mbt
        mbt.listchildren = Func(result=[f0, C0])
        sub0, sub1 = mbt.GetSubList()
        del mbt.listchildren
        self.assertIsInstance(sub0, browser.ChildBrowserTreeItem)
        self.assertIsInstance(sub1, browser.ChildBrowserTreeItem)
        self.assertEqual(sub0.name, 'f0')
        self.assertEqual(sub1.name, 'C0(base)')

    @mock.patch('idlelib.browser.file_open')
    def test_ondoubleclick(self, fopen):
        mbt = self.mbt

        with mock.patch('os.path.exists', return_value=False):
            mbt.OnDoubleClick()
            fopen.assert_not_called()

        with mock.patch('os.path.exists', return_value=True):
            mbt.OnDoubleClick()
            fopen.assert_called_once_with(fname)


class ChildBrowserTreeItemTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        CBT = browser.ChildBrowserTreeItem
        cls.cbt_f1 = CBT(f1)
        cls.cbt_C1 = CBT(C1)
        cls.cbt_F1 = CBT(F1)

    @classmethod
    def tearDownClass(cls):
        del cls.cbt_C1, cls.cbt_f1, cls.cbt_F1

    def test_init(self):
        eq = self.assertEqual
        eq(self.cbt_C1.name, 'C1()')
        self.assertFalse(self.cbt_C1.isfunction)
        eq(self.cbt_f1.name, 'f1')
        self.assertTrue(self.cbt_f1.isfunction)

    def test_gettext(self):
        self.assertEqual(self.cbt_C1.GetText(), 'class C1()')
        self.assertEqual(self.cbt_f1.GetText(), 'def f1(...)')

    def test_geticonname(self):
        self.assertEqual(self.cbt_C1.GetIconName(), 'folder')
        self.assertEqual(self.cbt_f1.GetIconName(), 'python')

    def test_isexpandable(self):
        self.assertTrue(self.cbt_C1.IsExpandable())
        self.assertTrue(self.cbt_f1.IsExpandable())
        self.assertFalse(self.cbt_F1.IsExpandable())

    def test_getsublist(self):
        eq = self.assertEqual
        CBT = browser.ChildBrowserTreeItem

        f1sublist = self.cbt_f1.GetSubList()
        self.assertIsInstance(f1sublist[0], CBT)
        eq(len(f1sublist), 1)
        eq(f1sublist[0].name, 'f2')

        eq(self.cbt_F1.GetSubList(), [])

    @mock.patch('idlelib.browser.file_open')
    def test_ondoubleclick(self, fopen):
        goto = fopen.return_value.gotoline = mock.Mock()
        self.cbt_F1.OnDoubleClick()
        fopen.assert_called()
        goto.assert_called()
        goto.assert_called_with(self.cbt_F1.obj.lineno)
        # Failure test would have to raise OSError or AttributeError.


class NestedChildrenTest(unittest.TestCase):
    "Test that all the nodes in a nested tree are added to the BrowserTree."

    def test_nested(self):
        queue = deque()
        actual_names = []
        # The tree items are processed in breadth first order.
        # Verify that processing each sublist hits every node and
        # in the right order.
        expected_names = ['f0', 'C0(base)',
                          'f1', 'c1', 'F1', 'C1()',
                          'f2', 'C2',
                          'F3']
        CBT = browser.ChildBrowserTreeItem
        queue.extend((CBT(f0), CBT(C0)))
        while queue:
            cb = queue.popleft()
            sublist = cb.GetSubList()
            queue.extend(sublist)
            self.assertIn(cb.name, cb.GetText())
            self.assertIn(cb.GetIconName(), ('python', 'folder'))
            self.assertIs(cb.IsExpandable(), sublist != [])
            actual_names.append(cb.name)
        self.assertEqual(actual_names, expected_names)


if __name__ == '__main__':
    unittest.main(verbosity=2)
