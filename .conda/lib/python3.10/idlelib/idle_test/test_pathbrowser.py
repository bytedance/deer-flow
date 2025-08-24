"Test pathbrowser, coverage 95%."

from idlelib import pathbrowser
import unittest
from test.support import requires
from tkinter import Tk

import os.path
import pyclbr  # for _modules
import sys  # for sys.path

from idlelib.idle_test.mock_idle import Func
import idlelib  # for __file__
from idlelib import browser
from idlelib.tree import TreeNode


class PathBrowserTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = Tk()
        cls.root.withdraw()
        cls.pb = pathbrowser.PathBrowser(cls.root, _utest=True)

    @classmethod
    def tearDownClass(cls):
        cls.pb.close()
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root, cls.pb

    def test_init(self):
        pb = self.pb
        eq = self.assertEqual
        eq(pb.master, self.root)
        eq(pyclbr._modules, {})
        self.assertIsInstance(pb.node, TreeNode)
        self.assertIsNotNone(browser.file_open)

    def test_settitle(self):
        pb = self.pb
        self.assertEqual(pb.top.title(), 'Path Browser')
        self.assertEqual(pb.top.iconname(), 'Path Browser')

    def test_rootnode(self):
        pb = self.pb
        rn = pb.rootnode()
        self.assertIsInstance(rn, pathbrowser.PathBrowserTreeItem)

    def test_close(self):
        pb = self.pb
        pb.top.destroy = Func()
        pb.node.destroy = Func()
        pb.close()
        self.assertTrue(pb.top.destroy.called)
        self.assertTrue(pb.node.destroy.called)
        del pb.top.destroy, pb.node.destroy


class DirBrowserTreeItemTest(unittest.TestCase):

    def test_DirBrowserTreeItem(self):
        # Issue16226 - make sure that getting a sublist works
        d = pathbrowser.DirBrowserTreeItem('')
        d.GetSubList()
        self.assertEqual('', d.GetText())

        dir = os.path.split(os.path.abspath(idlelib.__file__))[0]
        self.assertEqual(d.ispackagedir(dir), True)
        self.assertEqual(d.ispackagedir(dir + '/Icons'), False)


class PathBrowserTreeItemTest(unittest.TestCase):

    def test_PathBrowserTreeItem(self):
        p = pathbrowser.PathBrowserTreeItem()
        self.assertEqual(p.GetText(), 'sys.path')
        sub = p.GetSubList()
        self.assertEqual(len(sub), len(sys.path))
        self.assertEqual(type(sub[0]), pathbrowser.DirBrowserTreeItem)


if __name__ == '__main__':
    unittest.main(verbosity=2, exit=False)
