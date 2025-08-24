"Test calltip, coverage 76%"

from idlelib import calltip
import unittest
from unittest.mock import Mock
import textwrap
import types
import re
from idlelib.idle_test.mock_tk import Text


# Test Class TC is used in multiple get_argspec test methods
class TC:
    'doc'
    tip = "(ai=None, *b)"
    def __init__(self, ai=None, *b): 'doc'
    __init__.tip = "(self, ai=None, *b)"
    def t1(self): 'doc'
    t1.tip = "(self)"
    def t2(self, ai, b=None): 'doc'
    t2.tip = "(self, ai, b=None)"
    def t3(self, ai, *args): 'doc'
    t3.tip = "(self, ai, *args)"
    def t4(self, *args): 'doc'
    t4.tip = "(self, *args)"
    def t5(self, ai, b=None, *args, **kw): 'doc'
    t5.tip = "(self, ai, b=None, *args, **kw)"
    def t6(no, self): 'doc'
    t6.tip = "(no, self)"
    def __call__(self, ci): 'doc'
    __call__.tip = "(self, ci)"
    def nd(self): pass  # No doc.
    # attaching .tip to wrapped methods does not work
    @classmethod
    def cm(cls, a): 'doc'
    @staticmethod
    def sm(b): 'doc'


tc = TC()
default_tip = calltip._default_callable_argspec
get_spec = calltip.get_argspec


class Get_argspecTest(unittest.TestCase):
    # The get_spec function must return a string, even if blank.
    # Test a variety of objects to be sure that none cause it to raise
    # (quite aside from getting as correct an answer as possible).
    # The tests of builtins may break if inspect or the docstrings change,
    # but a red buildbot is better than a user crash (as has happened).
    # For a simple mismatch, change the expected output to the actual.

    def test_builtins(self):

        def tiptest(obj, out):
            self.assertEqual(get_spec(obj), out)

        # Python class that inherits builtin methods
        class List(list): "List() doc"

        # Simulate builtin with no docstring for default tip test
        class SB:  __call__ = None

        if List.__doc__ is not None:
            tiptest(List,
                    f'(iterable=(), /)'
                    f'\n{List.__doc__}')
        tiptest(list.__new__,
              '(*args, **kwargs)\n'
              'Create and return a new object.  '
              'See help(type) for accurate signature.')
        tiptest(list.__init__,
              '(self, /, *args, **kwargs)\n'
              'Initialize self.  See help(type(self)) for accurate signature.')
        append_doc = "\nAppend object to the end of the list."
        tiptest(list.append, '(self, object, /)' + append_doc)
        tiptest(List.append, '(self, object, /)' + append_doc)
        tiptest([].append, '(object, /)' + append_doc)

        tiptest(types.MethodType, "method(function, instance)")
        tiptest(SB(), default_tip)

        p = re.compile('')
        tiptest(re.sub, '''\
(pattern, repl, string, count=0, flags=0)
Return the string obtained by replacing the leftmost
non-overlapping occurrences of the pattern in string by the
replacement repl.  repl can be either a string or a callable;
if a string, backslash escapes in it are processed.  If it is
a callable, it's passed the Match object and must return''')
        tiptest(p.sub, '''\
(repl, string, count=0)
Return the string obtained by replacing the leftmost \
non-overlapping occurrences o...''')

    def test_signature_wrap(self):
        if textwrap.TextWrapper.__doc__ is not None:
            self.assertEqual(get_spec(textwrap.TextWrapper), '''\
(width=70, initial_indent='', subsequent_indent='', expand_tabs=True,
    replace_whitespace=True, fix_sentence_endings=False, break_long_words=True,
    drop_whitespace=True, break_on_hyphens=True, tabsize=8, *, max_lines=None,
    placeholder=' [...]')
Object for wrapping/filling text.  The public interface consists of
the wrap() and fill() methods; the other methods are just there for
subclasses to override in order to tweak the default behaviour.
If you want to completely replace the main wrapping algorithm,
you\'ll probably have to override _wrap_chunks().''')

    def test_properly_formatted(self):

        def foo(s='a'*100):
            pass

        def bar(s='a'*100):
            """Hello Guido"""
            pass

        def baz(s='a'*100, z='b'*100):
            pass

        indent = calltip._INDENT

        sfoo = "(s='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\
               "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" + indent + "aaaaaaaaa"\
               "aaaaaaaaaa')"
        sbar = "(s='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\
               "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" + indent + "aaaaaaaaa"\
               "aaaaaaaaaa')\nHello Guido"
        sbaz = "(s='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\
               "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n" + indent + "aaaaaaaaa"\
               "aaaaaaaaaa', z='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"\
               "bbbbbbbbbbbbbbbbb\n" + indent + "bbbbbbbbbbbbbbbbbbbbbb"\
               "bbbbbbbbbbbbbbbbbbbbbb')"

        for func,doc in [(foo, sfoo), (bar, sbar), (baz, sbaz)]:
            with self.subTest(func=func, doc=doc):
                self.assertEqual(get_spec(func), doc)

    def test_docline_truncation(self):
        def f(): pass
        f.__doc__ = 'a'*300
        self.assertEqual(get_spec(f), f"()\n{'a'*(calltip._MAX_COLS-3) + '...'}")

    def test_multiline_docstring(self):
        # Test fewer lines than max.
        self.assertEqual(get_spec(range),
                "range(stop) -> range object\n"
                "range(start, stop[, step]) -> range object")

        # Test max lines
        self.assertEqual(get_spec(bytes), '''\
bytes(iterable_of_ints) -> bytes
bytes(string, encoding[, errors]) -> bytes
bytes(bytes_or_buffer) -> immutable copy of bytes_or_buffer
bytes(int) -> bytes object of size given by the parameter initialized with null bytes
bytes() -> empty bytes object''')

        # Test more than max lines
        def f(): pass
        f.__doc__ = 'a\n' * 15
        self.assertEqual(get_spec(f), '()' + '\na' * calltip._MAX_LINES)

    def test_functions(self):
        def t1(): 'doc'
        t1.tip = "()"
        def t2(a, b=None): 'doc'
        t2.tip = "(a, b=None)"
        def t3(a, *args): 'doc'
        t3.tip = "(a, *args)"
        def t4(*args): 'doc'
        t4.tip = "(*args)"
        def t5(a, b=None, *args, **kw): 'doc'
        t5.tip = "(a, b=None, *args, **kw)"

        doc = '\ndoc' if t1.__doc__ is not None else ''
        for func in (t1, t2, t3, t4, t5, TC):
            with self.subTest(func=func):
                self.assertEqual(get_spec(func), func.tip + doc)

    def test_methods(self):
        doc = '\ndoc' if TC.__doc__ is not None else ''
        for meth in (TC.t1, TC.t2, TC.t3, TC.t4, TC.t5, TC.t6, TC.__call__):
            with self.subTest(meth=meth):
                self.assertEqual(get_spec(meth), meth.tip + doc)
        self.assertEqual(get_spec(TC.cm), "(a)" + doc)
        self.assertEqual(get_spec(TC.sm), "(b)" + doc)

    def test_bound_methods(self):
        # test that first parameter is correctly removed from argspec
        doc = '\ndoc' if TC.__doc__ is not None else ''
        for meth, mtip  in ((tc.t1, "()"), (tc.t4, "(*args)"),
                            (tc.t6, "(self)"), (tc.__call__, '(ci)'),
                            (tc, '(ci)'), (TC.cm, "(a)"),):
            with self.subTest(meth=meth, mtip=mtip):
                self.assertEqual(get_spec(meth), mtip + doc)

    def test_starred_parameter(self):
        # test that starred first parameter is *not* removed from argspec
        class C:
            def m1(*args): pass
        c = C()
        for meth, mtip  in ((C.m1, '(*args)'), (c.m1, "(*args)"),):
            with self.subTest(meth=meth, mtip=mtip):
                self.assertEqual(get_spec(meth), mtip)

    def test_invalid_method_get_spec(self):
        class C:
            def m2(**kwargs): pass
        class Test:
            def __call__(*, a): pass

        mtip = calltip._invalid_method
        self.assertEqual(get_spec(C().m2), mtip)
        self.assertEqual(get_spec(Test()), mtip)

    def test_non_ascii_name(self):
        # test that re works to delete a first parameter name that
        # includes non-ascii chars, such as various forms of A.
        uni = "(A\u0391\u0410\u05d0\u0627\u0905\u1e00\u3042, a)"
        assert calltip._first_param.sub('', uni) == '(a)'

    def test_no_docstring(self):
        for meth, mtip in ((TC.nd, "(self)"), (tc.nd, "()")):
            with self.subTest(meth=meth, mtip=mtip):
                self.assertEqual(get_spec(meth), mtip)

    def test_buggy_getattr_class(self):
        class NoCall:
            def __getattr__(self, name):  # Not invoked for class attribute.
                raise IndexError  # Bug.
        class CallA(NoCall):
            def __call__(self, ci):  # Bug does not matter.
                pass
        class CallB(NoCall):
            def __call__(oui, a, b, c):  # Non-standard 'self'.
                pass

        for meth, mtip  in ((NoCall, default_tip), (CallA, default_tip),
                            (NoCall(), ''), (CallA(), '(ci)'),
                            (CallB(), '(a, b, c)')):
            with self.subTest(meth=meth, mtip=mtip):
                self.assertEqual(get_spec(meth), mtip)

    def test_metaclass_class(self):  # Failure case for issue 38689.
        class Type(type):  # Type() requires 3 type args, returns class.
            __class__ = property({}.__getitem__, {}.__setitem__)
        class Object(metaclass=Type):
            __slots__ = '__class__'
        for meth, mtip  in ((Type, get_spec(type)), (Object, default_tip),
                            (Object(), '')):
            with self.subTest(meth=meth, mtip=mtip):
                self.assertEqual(get_spec(meth), mtip)

    def test_non_callables(self):
        for obj in (0, 0.0, '0', b'0', [], {}):
            with self.subTest(obj=obj):
                self.assertEqual(get_spec(obj), '')


class Get_entityTest(unittest.TestCase):
    def test_bad_entity(self):
        self.assertIsNone(calltip.get_entity('1/0'))
    def test_good_entity(self):
        self.assertIs(calltip.get_entity('int'), int)


# Test the 9 Calltip methods.
# open_calltip is about half the code; the others are fairly trivial.
# The default mocks are what are needed for open_calltip.

class mock_Shell:
    "Return mock sufficient to pass to hyperparser."
    def __init__(self, text):
        text.tag_prevrange = Mock(return_value=None)
        self.text = text
        self.prompt_last_line = ">>> "
        self.indentwidth = 4
        self.tabwidth = 8


class mock_TipWindow:
    def __init__(self):
        pass

    def showtip(self, text, parenleft, parenright):
        self.args = parenleft, parenright
        self.parenline, self.parencol = map(int, parenleft.split('.'))


class WrappedCalltip(calltip.Calltip):
    def _make_tk_calltip_window(self):
        return mock_TipWindow()

    def remove_calltip_window(self, event=None):
        if self.active_calltip:  # Setup to None.
            self.active_calltip = None
            self.tips_removed += 1  # Setup to 0.

    def fetch_tip(self, expression):
        return 'tip'


class CalltipTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.text = Text()
        cls.ct = WrappedCalltip(mock_Shell(cls.text))

    def setUp(self):
        self.text.delete('1.0', 'end')  # Insert and call
        self.ct.active_calltip = None
        # Test .active_calltip, +args
        self.ct.tips_removed = 0

    def open_close(self, testfunc):
        # Open-close template with testfunc called in between.
        opentip = self.ct.open_calltip
        self.text.insert(1.0, 'f(')
        opentip(False)
        self.tip = self.ct.active_calltip
        testfunc(self)  ###
        self.text.insert('insert', ')')
        opentip(False)
        self.assertIsNone(self.ct.active_calltip, None)

    def test_open_close(self):
        def args(self):
            self.assertEqual(self.tip.args, ('1.1', '1.end'))
        self.open_close(args)

    def test_repeated_force(self):
        def force(self):
            for char in 'abc':
                self.text.insert('insert', 'a')
                self.ct.open_calltip(True)
                self.ct.open_calltip(True)
            self.assertIs(self.ct.active_calltip, self.tip)
        self.open_close(force)

    def test_repeated_parens(self):
        def parens(self):
            for context in "a", "'":
                with self.subTest(context=context):
                    self.text.insert('insert', context)
                    for char in '(()())':
                        self.text.insert('insert', char)
                    self.assertIs(self.ct.active_calltip, self.tip)
            self.text.insert('insert', "'")
        self.open_close(parens)

    def test_comment_parens(self):
        def comment(self):
            self.text.insert('insert', "# ")
            for char in '(()())':
                self.text.insert('insert', char)
            self.assertIs(self.ct.active_calltip, self.tip)
            self.text.insert('insert', "\n")
        self.open_close(comment)


if __name__ == '__main__':
    unittest.main(verbosity=2)
