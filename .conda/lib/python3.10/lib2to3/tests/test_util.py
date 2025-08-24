""" Test suite for the code in fixer_util """

# Testing imports
from . import support

# Local imports
from lib2to3.pytree import Node, Leaf
from lib2to3 import fixer_util
from lib2to3.fixer_util import Attr, Name, Call, Comma
from lib2to3.pgen2 import token

def parse(code, strip_levels=0):
    # The topmost node is file_input, which we don't care about.
    # The next-topmost node is a *_stmt node, which we also don't care about
    tree = support.parse_string(code)
    for i in range(strip_levels):
        tree = tree.children[0]
    tree.parent = None
    return tree

class MacroTestCase(support.TestCase):
    def assertStr(self, node, string):
        if isinstance(node, (tuple, list)):
            node = Node(fixer_util.syms.simple_stmt, node)
        self.assertEqual(str(node), string)


class Test_is_tuple(support.TestCase):
    def is_tuple(self, string):
        return fixer_util.is_tuple(parse(string, strip_levels=2))

    def test_valid(self):
        self.assertTrue(self.is_tuple("(a, b)"))
        self.assertTrue(self.is_tuple("(a, (b, c))"))
        self.assertTrue(self.is_tuple("((a, (b, c)),)"))
        self.assertTrue(self.is_tuple("(a,)"))
        self.assertTrue(self.is_tuple("()"))

    def test_invalid(self):
        self.assertFalse(self.is_tuple("(a)"))
        self.assertFalse(self.is_tuple("('foo') % (b, c)"))


class Test_is_list(support.TestCase):
    def is_list(self, string):
        return fixer_util.is_list(parse(string, strip_levels=2))

    def test_valid(self):
        self.assertTrue(self.is_list("[]"))
        self.assertTrue(self.is_list("[a]"))
        self.assertTrue(self.is_list("[a, b]"))
        self.assertTrue(self.is_list("[a, [b, c]]"))
        self.assertTrue(self.is_list("[[a, [b, c]],]"))

    def test_invalid(self):
        self.assertFalse(self.is_list("[]+[]"))


class Test_Attr(MacroTestCase):
    def test(self):
        call = parse("foo()", strip_levels=2)

        self.assertStr(Attr(Name("a"), Name("b")), "a.b")
        self.assertStr(Attr(call, Name("b")), "foo().b")

    def test_returns(self):
        attr = Attr(Name("a"), Name("b"))
        self.assertEqual(type(attr), list)


class Test_Name(MacroTestCase):
    def test(self):
        self.assertStr(Name("a"), "a")
        self.assertStr(Name("foo.foo().bar"), "foo.foo().bar")
        self.assertStr(Name("a", prefix="b"), "ba")


class Test_Call(MacroTestCase):
    def _Call(self, name, args=None, prefix=None):
        """Help the next test"""
        children = []
        if isinstance(args, list):
            for arg in args:
                children.append(arg)
                children.append(Comma())
            children.pop()
        return Call(Name(name), children, prefix)

    def test(self):
        kids = [None,
                [Leaf(token.NUMBER, 1), Leaf(token.NUMBER, 2),
                 Leaf(token.NUMBER, 3)],
                [Leaf(token.NUMBER, 1), Leaf(token.NUMBER, 3),
                 Leaf(token.NUMBER, 2), Leaf(token.NUMBER, 4)],
                [Leaf(token.STRING, "b"), Leaf(token.STRING, "j", prefix=" ")]
                ]
        self.assertStr(self._Call("A"), "A()")
        self.assertStr(self._Call("b", kids[1]), "b(1,2,3)")
        self.assertStr(self._Call("a.b().c", kids[2]), "a.b().c(1,3,2,4)")
        self.assertStr(self._Call("d", kids[3], prefix=" "), " d(b, j)")


class Test_does_tree_import(support.TestCase):
    def _find_bind_rec(self, name, node):
        # Search a tree for a binding -- used to find the starting
        # point for these tests.
        c = fixer_util.find_binding(name, node)
        if c: return c
        for child in node.children:
            c = self._find_bind_rec(name, child)
            if c: return c

    def does_tree_import(self, package, name, string):
        node = parse(string)
        # Find the binding of start -- that's what we'll go from
        node = self._find_bind_rec('start', node)
        return fixer_util.does_tree_import(package, name, node)

    def try_with(self, string):
        failing_tests = (("a", "a", "from a import b"),
                         ("a.d", "a", "from a.d import b"),
                         ("d.a", "a", "from d.a import b"),
                         (None, "a", "import b"),
                         (None, "a", "import b, c, d"))
        for package, name, import_ in failing_tests:
            n = self.does_tree_import(package, name, import_ + "\n" + string)
            self.assertFalse(n)
            n = self.does_tree_import(package, name, string + "\n" + import_)
            self.assertFalse(n)

        passing_tests = (("a", "a", "from a import a"),
                         ("x", "a", "from x import a"),
                         ("x", "a", "from x import b, c, a, d"),
                         ("x.b", "a", "from x.b import a"),
                         ("x.b", "a", "from x.b import b, c, a, d"),
                         (None, "a", "import a"),
                         (None, "a", "import b, c, a, d"))
        for package, name, import_ in passing_tests:
            n = self.does_tree_import(package, name, import_ + "\n" + string)
            self.assertTrue(n)
            n = self.does_tree_import(package, name, string + "\n" + import_)
            self.assertTrue(n)

    def test_in_function(self):
        self.try_with("def foo():\n\tbar.baz()\n\tstart=3")

class Test_find_binding(support.TestCase):
    def find_binding(self, name, string, package=None):
        return fixer_util.find_binding(name, parse(string), package)

    def test_simple_assignment(self):
        self.assertTrue(self.find_binding("a", "a = b"))
        self.assertTrue(self.find_binding("a", "a = [b, c, d]"))
        self.assertTrue(self.find_binding("a", "a = foo()"))
        self.assertTrue(self.find_binding("a", "a = foo().foo.foo[6][foo]"))
        self.assertFalse(self.find_binding("a", "foo = a"))
        self.assertFalse(self.find_binding("a", "foo = (a, b, c)"))

    def test_tuple_assignment(self):
        self.assertTrue(self.find_binding("a", "(a,) = b"))
        self.assertTrue(self.find_binding("a", "(a, b, c) = [b, c, d]"))
        self.assertTrue(self.find_binding("a", "(c, (d, a), b) = foo()"))
        self.assertTrue(self.find_binding("a", "(a, b) = foo().foo[6][foo]"))
        self.assertFalse(self.find_binding("a", "(foo, b) = (b, a)"))
        self.assertFalse(self.find_binding("a", "(foo, (b, c)) = (a, b, c)"))

    def test_list_assignment(self):
        self.assertTrue(self.find_binding("a", "[a] = b"))
        self.assertTrue(self.find_binding("a", "[a, b, c] = [b, c, d]"))
        self.assertTrue(self.find_binding("a", "[c, [d, a], b] = foo()"))
        self.assertTrue(self.find_binding("a", "[a, b] = foo().foo[a][foo]"))
        self.assertFalse(self.find_binding("a", "[foo, b] = (b, a)"))
        self.assertFalse(self.find_binding("a", "[foo, [b, c]] = (a, b, c)"))

    def test_invalid_assignments(self):
        self.assertFalse(self.find_binding("a", "foo.a = 5"))
        self.assertFalse(self.find_binding("a", "foo[a] = 5"))
        self.assertFalse(self.find_binding("a", "foo(a) = 5"))
        self.assertFalse(self.find_binding("a", "foo(a, b) = 5"))

    def test_simple_import(self):
        self.assertTrue(self.find_binding("a", "import a"))
        self.assertTrue(self.find_binding("a", "import b, c, a, d"))
        self.assertFalse(self.find_binding("a", "import b"))
        self.assertFalse(self.find_binding("a", "import b, c, d"))

    def test_from_import(self):
        self.assertTrue(self.find_binding("a", "from x import a"))
        self.assertTrue(self.find_binding("a", "from a import a"))
        self.assertTrue(self.find_binding("a", "from x import b, c, a, d"))
        self.assertTrue(self.find_binding("a", "from x.b import a"))
        self.assertTrue(self.find_binding("a", "from x.b import b, c, a, d"))
        self.assertFalse(self.find_binding("a", "from a import b"))
        self.assertFalse(self.find_binding("a", "from a.d import b"))
        self.assertFalse(self.find_binding("a", "from d.a import b"))

    def test_import_as(self):
        self.assertTrue(self.find_binding("a", "import b as a"))
        self.assertTrue(self.find_binding("a", "import b as a, c, a as f, d"))
        self.assertFalse(self.find_binding("a", "import a as f"))
        self.assertFalse(self.find_binding("a", "import b, c as f, d as e"))

    def test_from_import_as(self):
        self.assertTrue(self.find_binding("a", "from x import b as a"))
        self.assertTrue(self.find_binding("a", "from x import g as a, d as b"))
        self.assertTrue(self.find_binding("a", "from x.b import t as a"))
        self.assertTrue(self.find_binding("a", "from x.b import g as a, d"))
        self.assertFalse(self.find_binding("a", "from a import b as t"))
        self.assertFalse(self.find_binding("a", "from a.d import b as t"))
        self.assertFalse(self.find_binding("a", "from d.a import b as t"))

    def test_simple_import_with_package(self):
        self.assertTrue(self.find_binding("b", "import b"))
        self.assertTrue(self.find_binding("b", "import b, c, d"))
        self.assertFalse(self.find_binding("b", "import b", "b"))
        self.assertFalse(self.find_binding("b", "import b, c, d", "c"))

    def test_from_import_with_package(self):
        self.assertTrue(self.find_binding("a", "from x import a", "x"))
        self.assertTrue(self.find_binding("a", "from a import a", "a"))
        self.assertTrue(self.find_binding("a", "from x import *", "x"))
        self.assertTrue(self.find_binding("a", "from x import b, c, a, d", "x"))
        self.assertTrue(self.find_binding("a", "from x.b import a", "x.b"))
        self.assertTrue(self.find_binding("a", "from x.b import *", "x.b"))
        self.assertTrue(self.find_binding("a", "from x.b import b, c, a, d", "x.b"))
        self.assertFalse(self.find_binding("a", "from a import b", "a"))
        self.assertFalse(self.find_binding("a", "from a.d import b", "a.d"))
        self.assertFalse(self.find_binding("a", "from d.a import b", "a.d"))
        self.assertFalse(self.find_binding("a", "from x.y import *", "a.b"))

    def test_import_as_with_package(self):
        self.assertFalse(self.find_binding("a", "import b.c as a", "b.c"))
        self.assertFalse(self.find_binding("a", "import a as f", "f"))
        self.assertFalse(self.find_binding("a", "import a as f", "a"))

    def test_from_import_as_with_package(self):
        # Because it would take a lot of special-case code in the fixers
        # to deal with from foo import bar as baz, we'll simply always
        # fail if there is an "from ... import ... as ..."
        self.assertFalse(self.find_binding("a", "from x import b as a", "x"))
        self.assertFalse(self.find_binding("a", "from x import g as a, d as b", "x"))
        self.assertFalse(self.find_binding("a", "from x.b import t as a", "x.b"))
        self.assertFalse(self.find_binding("a", "from x.b import g as a, d", "x.b"))
        self.assertFalse(self.find_binding("a", "from a import b as t", "a"))
        self.assertFalse(self.find_binding("a", "from a import b as t", "b"))
        self.assertFalse(self.find_binding("a", "from a import b as t", "t"))

    def test_function_def(self):
        self.assertTrue(self.find_binding("a", "def a(): pass"))
        self.assertTrue(self.find_binding("a", "def a(b, c, d): pass"))
        self.assertTrue(self.find_binding("a", "def a(): b = 7"))
        self.assertFalse(self.find_binding("a", "def d(b, (c, a), e): pass"))
        self.assertFalse(self.find_binding("a", "def d(a=7): pass"))
        self.assertFalse(self.find_binding("a", "def d(a): pass"))
        self.assertFalse(self.find_binding("a", "def d(): a = 7"))

        s = """
            def d():
                def a():
                    pass"""
        self.assertFalse(self.find_binding("a", s))

    def test_class_def(self):
        self.assertTrue(self.find_binding("a", "class a: pass"))
        self.assertTrue(self.find_binding("a", "class a(): pass"))
        self.assertTrue(self.find_binding("a", "class a(b): pass"))
        self.assertTrue(self.find_binding("a", "class a(b, c=8): pass"))
        self.assertFalse(self.find_binding("a", "class d: pass"))
        self.assertFalse(self.find_binding("a", "class d(a): pass"))
        self.assertFalse(self.find_binding("a", "class d(b, a=7): pass"))
        self.assertFalse(self.find_binding("a", "class d(b, *a): pass"))
        self.assertFalse(self.find_binding("a", "class d(b, **a): pass"))
        self.assertFalse(self.find_binding("a", "class d: a = 7"))

        s = """
            class d():
                class a():
                    pass"""
        self.assertFalse(self.find_binding("a", s))

    def test_for(self):
        self.assertTrue(self.find_binding("a", "for a in r: pass"))
        self.assertTrue(self.find_binding("a", "for a, b in r: pass"))
        self.assertTrue(self.find_binding("a", "for (a, b) in r: pass"))
        self.assertTrue(self.find_binding("a", "for c, (a,) in r: pass"))
        self.assertTrue(self.find_binding("a", "for c, (a, b) in r: pass"))
        self.assertTrue(self.find_binding("a", "for c in r: a = c"))
        self.assertFalse(self.find_binding("a", "for c in a: pass"))

    def test_for_nested(self):
        s = """
            for b in r:
                for a in b:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for a, c in b:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for (a, c) in b:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for (a,) in b:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for c, (a, d) in b:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for c in b:
                    a = 7"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            for b in r:
                for c in b:
                    d = a"""
        self.assertFalse(self.find_binding("a", s))

        s = """
            for b in r:
                for c in a:
                    d = 7"""
        self.assertFalse(self.find_binding("a", s))

    def test_if(self):
        self.assertTrue(self.find_binding("a", "if b in r: a = c"))
        self.assertFalse(self.find_binding("a", "if a in r: d = e"))

    def test_if_nested(self):
        s = """
            if b in r:
                if c in d:
                    a = c"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            if b in r:
                if c in d:
                    c = a"""
        self.assertFalse(self.find_binding("a", s))

    def test_while(self):
        self.assertTrue(self.find_binding("a", "while b in r: a = c"))
        self.assertFalse(self.find_binding("a", "while a in r: d = e"))

    def test_while_nested(self):
        s = """
            while b in r:
                while c in d:
                    a = c"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            while b in r:
                while c in d:
                    c = a"""
        self.assertFalse(self.find_binding("a", s))

    def test_try_except(self):
        s = """
            try:
                a = 6
            except:
                b = 8"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except KeyError:
                pass
            except:
                a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                b = 6"""
        self.assertFalse(self.find_binding("a", s))

    def test_try_except_nested(self):
        s = """
            try:
                try:
                    a = 6
                except:
                    pass
            except:
                b = 8"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                try:
                    a = 6
                except:
                    pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                try:
                    pass
                except:
                    a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                try:
                    b = 8
                except KeyError:
                    pass
                except:
                    a = 6
            except:
                pass"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                pass
            except:
                try:
                    b = 8
                except KeyError:
                    pass
                except:
                    a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                b = 6"""
        self.assertFalse(self.find_binding("a", s))

        s = """
            try:
                try:
                    b = 8
                except:
                    c = d
            except:
                try:
                    b = 6
                except:
                    t = 8
                except:
                    o = y"""
        self.assertFalse(self.find_binding("a", s))

    def test_try_except_finally(self):
        s = """
            try:
                c = 6
            except:
                b = 8
            finally:
                a = 9"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            finally:
                a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            finally:
                b = 6"""
        self.assertFalse(self.find_binding("a", s))

        s = """
            try:
                b = 8
            except:
                b = 9
            finally:
                b = 6"""
        self.assertFalse(self.find_binding("a", s))

    def test_try_except_finally_nested(self):
        s = """
            try:
                c = 6
            except:
                b = 8
            finally:
                try:
                    a = 9
                except:
                    b = 9
                finally:
                    c = 9"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            finally:
                try:
                    pass
                finally:
                    a = 6"""
        self.assertTrue(self.find_binding("a", s))

        s = """
            try:
                b = 8
            finally:
                try:
                    b = 6
                finally:
                    b = 7"""
        self.assertFalse(self.find_binding("a", s))

class Test_touch_import(support.TestCase):

    def test_after_docstring(self):
        node = parse('"""foo"""\nbar()')
        fixer_util.touch_import(None, "foo", node)
        self.assertEqual(str(node), '"""foo"""\nimport foo\nbar()\n\n')

    def test_after_imports(self):
        node = parse('"""foo"""\nimport bar\nbar()')
        fixer_util.touch_import(None, "foo", node)
        self.assertEqual(str(node), '"""foo"""\nimport bar\nimport foo\nbar()\n\n')

    def test_beginning(self):
        node = parse('bar()')
        fixer_util.touch_import(None, "foo", node)
        self.assertEqual(str(node), 'import foo\nbar()\n\n')

    def test_from_import(self):
        node = parse('bar()')
        fixer_util.touch_import("html", "escape", node)
        self.assertEqual(str(node), 'from html import escape\nbar()\n\n')

    def test_name_import(self):
        node = parse('bar()')
        fixer_util.touch_import(None, "cgi", node)
        self.assertEqual(str(node), 'import cgi\nbar()\n\n')

class Test_find_indentation(support.TestCase):

    def test_nothing(self):
        fi = fixer_util.find_indentation
        node = parse("node()")
        self.assertEqual(fi(node), "")
        node = parse("")
        self.assertEqual(fi(node), "")

    def test_simple(self):
        fi = fixer_util.find_indentation
        node = parse("def f():\n    x()")
        self.assertEqual(fi(node), "")
        self.assertEqual(fi(node.children[0].children[4].children[2]), "    ")
        node = parse("def f():\n    x()\n    y()")
        self.assertEqual(fi(node.children[0].children[4].children[4]), "    ")
