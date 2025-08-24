# Copyright 2006 Google, Inc. All Rights Reserved.
# Licensed to PSF under a Contributor Agreement.

"""Unit tests for pytree.py.

NOTE: Please *don't* add doc strings to individual test methods!
In verbose mode, printing of the module, class and method name is much
more helpful than printing of (the first line of) the docstring,
especially when debugging a test.
"""

# Testing imports
from . import support

from lib2to3 import pytree

try:
    sorted
except NameError:
    def sorted(lst):
        l = list(lst)
        l.sort()
        return l

class TestNodes(support.TestCase):

    """Unit tests for nodes (Base, Leaf, Node)."""

    def test_instantiate_base(self):
        if __debug__:
            # Test that instantiating Base() raises an AssertionError
            self.assertRaises(AssertionError, pytree.Base)

    def test_leaf(self):
        l1 = pytree.Leaf(100, "foo")
        self.assertEqual(l1.type, 100)
        self.assertEqual(l1.value, "foo")

    def test_leaf_repr(self):
        l1 = pytree.Leaf(100, "foo")
        self.assertEqual(repr(l1), "Leaf(100, 'foo')")

    def test_leaf_str(self):
        l1 = pytree.Leaf(100, "foo")
        self.assertEqual(str(l1), "foo")
        l2 = pytree.Leaf(100, "foo", context=(" ", (10, 1)))
        self.assertEqual(str(l2), " foo")

    def test_leaf_str_numeric_value(self):
        # Make sure that the Leaf's value is stringified. Failing to
        #  do this can cause a TypeError in certain situations.
        l1 = pytree.Leaf(2, 5)
        l1.prefix = "foo_"
        self.assertEqual(str(l1), "foo_5")

    def test_leaf_equality(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "foo", context=(" ", (1, 0)))
        self.assertEqual(l1, l2)
        l3 = pytree.Leaf(101, "foo")
        l4 = pytree.Leaf(100, "bar")
        self.assertNotEqual(l1, l3)
        self.assertNotEqual(l1, l4)

    def test_leaf_prefix(self):
        l1 = pytree.Leaf(100, "foo")
        self.assertEqual(l1.prefix, "")
        self.assertFalse(l1.was_changed)
        l1.prefix = "  ##\n\n"
        self.assertEqual(l1.prefix, "  ##\n\n")
        self.assertTrue(l1.was_changed)

    def test_node(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(200, "bar")
        n1 = pytree.Node(1000, [l1, l2])
        self.assertEqual(n1.type, 1000)
        self.assertEqual(n1.children, [l1, l2])

    def test_node_repr(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar", context=(" ", (1, 0)))
        n1 = pytree.Node(1000, [l1, l2])
        self.assertEqual(repr(n1),
                         "Node(1000, [%s, %s])" % (repr(l1), repr(l2)))

    def test_node_str(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar", context=(" ", (1, 0)))
        n1 = pytree.Node(1000, [l1, l2])
        self.assertEqual(str(n1), "foo bar")

    def test_node_prefix(self):
        l1 = pytree.Leaf(100, "foo")
        self.assertEqual(l1.prefix, "")
        n1 = pytree.Node(1000, [l1])
        self.assertEqual(n1.prefix, "")
        n1.prefix = " "
        self.assertEqual(n1.prefix, " ")
        self.assertEqual(l1.prefix, " ")

    def test_get_suffix(self):
        l1 = pytree.Leaf(100, "foo", prefix="a")
        l2 = pytree.Leaf(100, "bar", prefix="b")
        n1 = pytree.Node(1000, [l1, l2])

        self.assertEqual(l1.get_suffix(), l2.prefix)
        self.assertEqual(l2.get_suffix(), "")
        self.assertEqual(n1.get_suffix(), "")

        l3 = pytree.Leaf(100, "bar", prefix="c")
        n2 = pytree.Node(1000, [n1, l3])

        self.assertEqual(n1.get_suffix(), l3.prefix)
        self.assertEqual(l3.get_suffix(), "")
        self.assertEqual(n2.get_suffix(), "")

    def test_node_equality(self):
        n1 = pytree.Node(1000, ())
        n2 = pytree.Node(1000, [], context=(" ", (1, 0)))
        self.assertEqual(n1, n2)
        n3 = pytree.Node(1001, ())
        self.assertNotEqual(n1, n3)

    def test_node_recursive_equality(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1])
        n2 = pytree.Node(1000, [l2])
        self.assertEqual(n1, n2)
        l3 = pytree.Leaf(100, "bar")
        n3 = pytree.Node(1000, [l3])
        self.assertNotEqual(n1, n3)

    def test_replace(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "+")
        l3 = pytree.Leaf(100, "bar")
        n1 = pytree.Node(1000, [l1, l2, l3])
        self.assertEqual(n1.children, [l1, l2, l3])
        self.assertIsInstance(n1.children, list)
        self.assertFalse(n1.was_changed)
        l2new = pytree.Leaf(100, "-")
        l2.replace(l2new)
        self.assertEqual(n1.children, [l1, l2new, l3])
        self.assertIsInstance(n1.children, list)
        self.assertTrue(n1.was_changed)

    def test_replace_with_list(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "+")
        l3 = pytree.Leaf(100, "bar")
        n1 = pytree.Node(1000, [l1, l2, l3])

        l2.replace([pytree.Leaf(100, "*"), pytree.Leaf(100, "*")])
        self.assertEqual(str(n1), "foo**bar")
        self.assertIsInstance(n1.children, list)

    def test_leaves(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        l3 = pytree.Leaf(100, "fooey")
        n2 = pytree.Node(1000, [l1, l2])
        n3 = pytree.Node(1000, [l3])
        n1 = pytree.Node(1000, [n2, n3])

        self.assertEqual(list(n1.leaves()), [l1, l2, l3])

    def test_depth(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        n2 = pytree.Node(1000, [l1, l2])
        n3 = pytree.Node(1000, [])
        n1 = pytree.Node(1000, [n2, n3])

        self.assertEqual(l1.depth(), 2)
        self.assertEqual(n3.depth(), 1)
        self.assertEqual(n1.depth(), 0)

    def test_post_order(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        l3 = pytree.Leaf(100, "fooey")
        c1 = pytree.Node(1000, [l1, l2])
        n1 = pytree.Node(1000, [c1, l3])
        self.assertEqual(list(n1.post_order()), [l1, l2, c1, l3, n1])

    def test_pre_order(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        l3 = pytree.Leaf(100, "fooey")
        c1 = pytree.Node(1000, [l1, l2])
        n1 = pytree.Node(1000, [c1, l3])
        self.assertEqual(list(n1.pre_order()), [n1, c1, l1, l2, l3])

    def test_changed(self):
        l1 = pytree.Leaf(100, "f")
        self.assertFalse(l1.was_changed)
        l1.changed()
        self.assertTrue(l1.was_changed)

        l1 = pytree.Leaf(100, "f")
        n1 = pytree.Node(1000, [l1])
        self.assertFalse(n1.was_changed)
        n1.changed()
        self.assertTrue(n1.was_changed)

        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "+")
        l3 = pytree.Leaf(100, "bar")
        n1 = pytree.Node(1000, [l1, l2, l3])
        n2 = pytree.Node(1000, [n1])
        self.assertFalse(l1.was_changed)
        self.assertFalse(n1.was_changed)
        self.assertFalse(n2.was_changed)

        n1.changed()
        self.assertTrue(n1.was_changed)
        self.assertTrue(n2.was_changed)
        self.assertFalse(l1.was_changed)

    def test_leaf_constructor_prefix(self):
        for prefix in ("xyz_", ""):
            l1 = pytree.Leaf(100, "self", prefix=prefix)
            self.assertTrue(str(l1), prefix + "self")
            self.assertEqual(l1.prefix, prefix)

    def test_node_constructor_prefix(self):
        for prefix in ("xyz_", ""):
            l1 = pytree.Leaf(100, "self")
            l2 = pytree.Leaf(100, "foo", prefix="_")
            n1 = pytree.Node(1000, [l1, l2], prefix=prefix)
            self.assertTrue(str(n1), prefix + "self_foo")
            self.assertEqual(n1.prefix, prefix)
            self.assertEqual(l1.prefix, prefix)
            self.assertEqual(l2.prefix, "_")

    def test_remove(self):
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1, l2])
        n2 = pytree.Node(1000, [n1])

        self.assertEqual(n1.remove(), 0)
        self.assertEqual(n2.children, [])
        self.assertEqual(l1.parent, n1)
        self.assertEqual(n1.parent, None)
        self.assertEqual(n2.parent, None)
        self.assertFalse(n1.was_changed)
        self.assertTrue(n2.was_changed)

        self.assertEqual(l2.remove(), 1)
        self.assertEqual(l1.remove(), 0)
        self.assertEqual(n1.children, [])
        self.assertEqual(l1.parent, None)
        self.assertEqual(n1.parent, None)
        self.assertEqual(n2.parent, None)
        self.assertTrue(n1.was_changed)
        self.assertTrue(n2.was_changed)

    def test_remove_parentless(self):
        n1 = pytree.Node(1000, [])
        n1.remove()
        self.assertEqual(n1.parent, None)

        l1 = pytree.Leaf(100, "foo")
        l1.remove()
        self.assertEqual(l1.parent, None)

    def test_node_set_child(self):
        l1 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1])

        l2 = pytree.Leaf(100, "bar")
        n1.set_child(0, l2)
        self.assertEqual(l1.parent, None)
        self.assertEqual(l2.parent, n1)
        self.assertEqual(n1.children, [l2])

        n2 = pytree.Node(1000, [l1])
        n2.set_child(0, n1)
        self.assertEqual(l1.parent, None)
        self.assertEqual(n1.parent, n2)
        self.assertEqual(n2.parent, None)
        self.assertEqual(n2.children, [n1])

        self.assertRaises(IndexError, n1.set_child, 4, l2)
        # I don't care what it raises, so long as it's an exception
        self.assertRaises(Exception, n1.set_child, 0, list)

    def test_node_insert_child(self):
        l1 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1])

        l2 = pytree.Leaf(100, "bar")
        n1.insert_child(0, l2)
        self.assertEqual(l2.parent, n1)
        self.assertEqual(n1.children, [l2, l1])

        l3 = pytree.Leaf(100, "abc")
        n1.insert_child(2, l3)
        self.assertEqual(n1.children, [l2, l1, l3])

        # I don't care what it raises, so long as it's an exception
        self.assertRaises(Exception, n1.insert_child, 0, list)

    def test_node_append_child(self):
        n1 = pytree.Node(1000, [])

        l1 = pytree.Leaf(100, "foo")
        n1.append_child(l1)
        self.assertEqual(l1.parent, n1)
        self.assertEqual(n1.children, [l1])

        l2 = pytree.Leaf(100, "bar")
        n1.append_child(l2)
        self.assertEqual(l2.parent, n1)
        self.assertEqual(n1.children, [l1, l2])

        # I don't care what it raises, so long as it's an exception
        self.assertRaises(Exception, n1.append_child, list)

    def test_node_next_sibling(self):
        n1 = pytree.Node(1000, [])
        n2 = pytree.Node(1000, [])
        p1 = pytree.Node(1000, [n1, n2])

        self.assertIs(n1.next_sibling, n2)
        self.assertEqual(n2.next_sibling, None)
        self.assertEqual(p1.next_sibling, None)

    def test_leaf_next_sibling(self):
        l1 = pytree.Leaf(100, "a")
        l2 = pytree.Leaf(100, "b")
        p1 = pytree.Node(1000, [l1, l2])

        self.assertIs(l1.next_sibling, l2)
        self.assertEqual(l2.next_sibling, None)
        self.assertEqual(p1.next_sibling, None)

    def test_node_prev_sibling(self):
        n1 = pytree.Node(1000, [])
        n2 = pytree.Node(1000, [])
        p1 = pytree.Node(1000, [n1, n2])

        self.assertIs(n2.prev_sibling, n1)
        self.assertEqual(n1.prev_sibling, None)
        self.assertEqual(p1.prev_sibling, None)

    def test_leaf_prev_sibling(self):
        l1 = pytree.Leaf(100, "a")
        l2 = pytree.Leaf(100, "b")
        p1 = pytree.Node(1000, [l1, l2])

        self.assertIs(l2.prev_sibling, l1)
        self.assertEqual(l1.prev_sibling, None)
        self.assertEqual(p1.prev_sibling, None)


class TestPatterns(support.TestCase):

    """Unit tests for tree matching patterns."""

    def test_basic_patterns(self):
        # Build a tree
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        l3 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1, l2])
        n2 = pytree.Node(1000, [l3])
        root = pytree.Node(1000, [n1, n2])
        # Build a pattern matching a leaf
        pl = pytree.LeafPattern(100, "foo", name="pl")
        r = {}
        self.assertFalse(pl.match(root, results=r))
        self.assertEqual(r, {})
        self.assertFalse(pl.match(n1, results=r))
        self.assertEqual(r, {})
        self.assertFalse(pl.match(n2, results=r))
        self.assertEqual(r, {})
        self.assertTrue(pl.match(l1, results=r))
        self.assertEqual(r, {"pl": l1})
        r = {}
        self.assertFalse(pl.match(l2, results=r))
        self.assertEqual(r, {})
        # Build a pattern matching a node
        pn = pytree.NodePattern(1000, [pl], name="pn")
        self.assertFalse(pn.match(root, results=r))
        self.assertEqual(r, {})
        self.assertFalse(pn.match(n1, results=r))
        self.assertEqual(r, {})
        self.assertTrue(pn.match(n2, results=r))
        self.assertEqual(r, {"pn": n2, "pl": l3})
        r = {}
        self.assertFalse(pn.match(l1, results=r))
        self.assertEqual(r, {})
        self.assertFalse(pn.match(l2, results=r))
        self.assertEqual(r, {})

    def test_wildcard(self):
        # Build a tree for testing
        l1 = pytree.Leaf(100, "foo")
        l2 = pytree.Leaf(100, "bar")
        l3 = pytree.Leaf(100, "foo")
        n1 = pytree.Node(1000, [l1, l2])
        n2 = pytree.Node(1000, [l3])
        root = pytree.Node(1000, [n1, n2])
        # Build a pattern
        pl = pytree.LeafPattern(100, "foo", name="pl")
        pn = pytree.NodePattern(1000, [pl], name="pn")
        pw = pytree.WildcardPattern([[pn], [pl, pl]], name="pw")
        r = {}
        self.assertFalse(pw.match_seq([root], r))
        self.assertEqual(r, {})
        self.assertFalse(pw.match_seq([n1], r))
        self.assertEqual(r, {})
        self.assertTrue(pw.match_seq([n2], r))
        # These are easier to debug
        self.assertEqual(sorted(r.keys()), ["pl", "pn", "pw"])
        self.assertEqual(r["pl"], l1)
        self.assertEqual(r["pn"], n2)
        self.assertEqual(r["pw"], [n2])
        # But this is equivalent
        self.assertEqual(r, {"pl": l1, "pn": n2, "pw": [n2]})
        r = {}
        self.assertTrue(pw.match_seq([l1, l3], r))
        self.assertEqual(r, {"pl": l3, "pw": [l1, l3]})
        self.assertIs(r["pl"], l3)
        r = {}

    def test_generate_matches(self):
        la = pytree.Leaf(1, "a")
        lb = pytree.Leaf(1, "b")
        lc = pytree.Leaf(1, "c")
        ld = pytree.Leaf(1, "d")
        le = pytree.Leaf(1, "e")
        lf = pytree.Leaf(1, "f")
        leaves = [la, lb, lc, ld, le, lf]
        root = pytree.Node(1000, leaves)
        pa = pytree.LeafPattern(1, "a", "pa")
        pb = pytree.LeafPattern(1, "b", "pb")
        pc = pytree.LeafPattern(1, "c", "pc")
        pd = pytree.LeafPattern(1, "d", "pd")
        pe = pytree.LeafPattern(1, "e", "pe")
        pf = pytree.LeafPattern(1, "f", "pf")
        pw = pytree.WildcardPattern([[pa, pb, pc], [pd, pe],
                                     [pa, pb], [pc, pd], [pe, pf]],
                                    min=1, max=4, name="pw")
        self.assertEqual([x[0] for x in pw.generate_matches(leaves)],
                         [3, 5, 2, 4, 6])
        pr = pytree.NodePattern(type=1000, content=[pw], name="pr")
        matches = list(pytree.generate_matches([pr], [root]))
        self.assertEqual(len(matches), 1)
        c, r = matches[0]
        self.assertEqual(c, 1)
        self.assertEqual(str(r["pr"]), "abcdef")
        self.assertEqual(r["pw"], [la, lb, lc, ld, le, lf])
        for c in "abcdef":
            self.assertEqual(r["p" + c], pytree.Leaf(1, c))

    def test_has_key_example(self):
        pattern = pytree.NodePattern(331,
                                     (pytree.LeafPattern(7),
                                      pytree.WildcardPattern(name="args"),
                                      pytree.LeafPattern(8)))
        l1 = pytree.Leaf(7, "(")
        l2 = pytree.Leaf(3, "x")
        l3 = pytree.Leaf(8, ")")
        node = pytree.Node(331, [l1, l2, l3])
        r = {}
        self.assertTrue(pattern.match(node, r))
        self.assertEqual(r["args"], [l2])
