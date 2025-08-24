"Test debugobj_r, coverage 56%."

from idlelib import debugobj_r
import unittest


class WrappedObjectTreeItemTest(unittest.TestCase):

    def test_getattr(self):
        ti = debugobj_r.WrappedObjectTreeItem(list)
        self.assertEqual(ti.append, list.append)

class StubObjectTreeItemTest(unittest.TestCase):

    def test_init(self):
        ti = debugobj_r.StubObjectTreeItem('socket', 1111)
        self.assertEqual(ti.sockio, 'socket')
        self.assertEqual(ti.oid, 1111)


if __name__ == '__main__':
    unittest.main(verbosity=2)
