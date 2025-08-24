"Test pyparse, coverage 96%."

from idlelib import pyparse
import unittest
from collections import namedtuple


class ParseMapTest(unittest.TestCase):

    def test_parsemap(self):
        keepwhite = {ord(c): ord(c) for c in ' \t\n\r'}
        mapping = pyparse.ParseMap(keepwhite)
        self.assertEqual(mapping[ord('\t')], ord('\t'))
        self.assertEqual(mapping[ord('a')], ord('x'))
        self.assertEqual(mapping[1000], ord('x'))

    def test_trans(self):
        # trans is the production instance of ParseMap, used in _study1
        parser = pyparse.Parser(4, 4)
        self.assertEqual('\t a([{b}])b"c\'d\n'.translate(pyparse.trans),
                         'xxx(((x)))x"x\'x\n')


class PyParseTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.parser = pyparse.Parser(indentwidth=4, tabwidth=4)

    @classmethod
    def tearDownClass(cls):
        del cls.parser

    def test_init(self):
        self.assertEqual(self.parser.indentwidth, 4)
        self.assertEqual(self.parser.tabwidth, 4)

    def test_set_code(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code

        # Not empty and doesn't end with newline.
        with self.assertRaises(AssertionError):
            setcode('a')

        tests = ('',
                 'a\n')

        for string in tests:
            with self.subTest(string=string):
                setcode(string)
                eq(p.code, string)
                eq(p.study_level, 0)

    def test_find_good_parse_start(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        start = p.find_good_parse_start
        def char_in_string_false(index): return False

        # First line starts with 'def' and ends with ':', then 0 is the pos.
        setcode('def spam():\n')
        eq(start(char_in_string_false), 0)

        # First line begins with a keyword in the list and ends
        # with an open brace, then 0 is the pos.  This is how
        # hyperparser calls this function as the newline is not added
        # in the editor, but rather on the call to setcode.
        setcode('class spam( ' + ' \n')
        eq(start(char_in_string_false), 0)

        # Split def across lines.
        setcode('"""This is a module docstring"""\n'
                'class C:\n'
                '    def __init__(self, a,\n'
                '                 b=True):\n'
                '        pass\n'
                )
        pos0, pos = 33, 42  # Start of 'class...', '    def' lines.

        # Passing no value or non-callable should fail (issue 32989).
        with self.assertRaises(TypeError):
            start()
        with self.assertRaises(TypeError):
            start(False)

        # Make text look like a string.  This returns pos as the start
        # position, but it's set to None.
        self.assertIsNone(start(is_char_in_string=lambda index: True))

        # Make all text look like it's not in a string.  This means that it
        # found a good start position.
        eq(start(char_in_string_false), pos)

        # If the beginning of the def line is not in a string, then it
        # returns that as the index.
        eq(start(is_char_in_string=lambda index: index > pos), pos)
        # If the beginning of the def line is in a string, then it
        # looks for a previous index.
        eq(start(is_char_in_string=lambda index: index >= pos), pos0)
        # If everything before the 'def' is in a string, then returns None.
        # The non-continuation def line returns 44 (see below).
        eq(start(is_char_in_string=lambda index: index < pos), None)

        # Code without extra line break in def line - mostly returns the same
        # values.
        setcode('"""This is a module docstring"""\n'
                'class C:\n'
                '    def __init__(self, a, b=True):\n'
                '        pass\n'
                )  # Does not affect class, def positions.
        eq(start(char_in_string_false), pos)
        eq(start(is_char_in_string=lambda index: index > pos), pos)
        eq(start(is_char_in_string=lambda index: index >= pos), pos0)
        # When the def line isn't split, this returns which doesn't match the
        # split line test.
        eq(start(is_char_in_string=lambda index: index < pos), pos)

    def test_set_lo(self):
        code = (
                '"""This is a module docstring"""\n'
                'class C:\n'
                '    def __init__(self, a,\n'
                '                 b=True):\n'
                '        pass\n'
                )
        pos = 42
        p = self.parser
        p.set_code(code)

        # Previous character is not a newline.
        with self.assertRaises(AssertionError):
            p.set_lo(5)

        # A value of 0 doesn't change self.code.
        p.set_lo(0)
        self.assertEqual(p.code, code)

        # An index that is preceded by a newline.
        p.set_lo(pos)
        self.assertEqual(p.code, code[pos:])

    def test_study1(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        study = p._study1

        (NONE, BACKSLASH, FIRST, NEXT, BRACKET) = range(5)
        TestInfo = namedtuple('TestInfo', ['string', 'goodlines',
                                           'continuation'])
        tests = (
            TestInfo('', [0], NONE),
            # Docstrings.
            TestInfo('"""This is a complete docstring."""\n', [0, 1], NONE),
            TestInfo("'''This is a complete docstring.'''\n", [0, 1], NONE),
            TestInfo('"""This is a continued docstring.\n', [0, 1], FIRST),
            TestInfo("'''This is a continued docstring.\n", [0, 1], FIRST),
            TestInfo('"""Closing quote does not match."\n', [0, 1], FIRST),
            TestInfo('"""Bracket in docstring [\n', [0, 1], FIRST),
            TestInfo("'''Incomplete two line docstring.\n\n", [0, 2], NEXT),
            # Single-quoted strings.
            TestInfo('"This is a complete string."\n', [0, 1], NONE),
            TestInfo('"This is an incomplete string.\n', [0, 1], NONE),
            TestInfo("'This is more incomplete.\n\n", [0, 1, 2], NONE),
            # Comment (backslash does not continue comments).
            TestInfo('# Comment\\\n', [0, 1], NONE),
            # Brackets.
            TestInfo('("""Complete string in bracket"""\n', [0, 1], BRACKET),
            TestInfo('("""Open string in bracket\n', [0, 1], FIRST),
            TestInfo('a = (1 + 2) - 5 *\\\n', [0, 1], BACKSLASH),  # No bracket.
            TestInfo('\n   def function1(self, a,\n                 b):\n',
                     [0, 1, 3], NONE),
            TestInfo('\n   def function1(self, a,\\\n', [0, 1, 2], BRACKET),
            TestInfo('\n   def function1(self, a,\n', [0, 1, 2], BRACKET),
            TestInfo('())\n', [0, 1], NONE),                    # Extra closer.
            TestInfo(')(\n', [0, 1], BRACKET),                  # Extra closer.
            # For the mismatched example, it doesn't look like continuation.
            TestInfo('{)(]\n', [0, 1], NONE),                   # Mismatched.
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)  # resets study_level
                study()
                eq(p.study_level, 1)
                eq(p.goodlines, test.goodlines)
                eq(p.continuation, test.continuation)

        # Called again, just returns without reprocessing.
        self.assertIsNone(study())

    def test_get_continuation_type(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        gettype = p.get_continuation_type

        (NONE, BACKSLASH, FIRST, NEXT, BRACKET) = range(5)
        TestInfo = namedtuple('TestInfo', ['string', 'continuation'])
        tests = (
            TestInfo('', NONE),
            TestInfo('"""This is a continuation docstring.\n', FIRST),
            TestInfo("'''This is a multiline-continued docstring.\n\n", NEXT),
            TestInfo('a = (1 + 2) - 5 *\\\n', BACKSLASH),
            TestInfo('\n   def function1(self, a,\\\n', BRACKET)
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                eq(gettype(), test.continuation)

    def test_study2(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        study = p._study2

        TestInfo = namedtuple('TestInfo', ['string', 'start', 'end', 'lastch',
                                           'openbracket', 'bracketing'])
        tests = (
            TestInfo('', 0, 0, '', None, ((0, 0),)),
            TestInfo("'''This is a multiline continuation docstring.\n\n",
                     0, 48, "'", None, ((0, 0), (0, 1), (48, 0))),
            TestInfo(' # Comment\\\n',
                     0, 12, '', None, ((0, 0), (1, 1), (12, 0))),
            # A comment without a space is a special case
            TestInfo(' #Comment\\\n',
                     0, 0, '', None, ((0, 0),)),
            # Backslash continuation.
            TestInfo('a = (1 + 2) - 5 *\\\n',
                     0, 19, '*', None, ((0, 0), (4, 1), (11, 0))),
            # Bracket continuation with close.
            TestInfo('\n   def function1(self, a,\n                 b):\n',
                     1, 48, ':', None, ((1, 0), (17, 1), (46, 0))),
            # Bracket continuation with unneeded backslash.
            TestInfo('\n   def function1(self, a,\\\n',
                     1, 28, ',', 17, ((1, 0), (17, 1))),
            # Bracket continuation.
            TestInfo('\n   def function1(self, a,\n',
                     1, 27, ',', 17, ((1, 0), (17, 1))),
            # Bracket continuation with comment at end of line with text.
            TestInfo('\n   def function1(self, a,  # End of line comment.\n',
                     1, 51, ',', 17, ((1, 0), (17, 1), (28, 2), (51, 1))),
            # Multi-line statement with comment line in between code lines.
            TestInfo('  a = ["first item",\n  # Comment line\n    "next item",\n',
                     0, 55, ',', 6, ((0, 0), (6, 1), (7, 2), (19, 1),
                                     (23, 2), (38, 1), (42, 2), (53, 1))),
            TestInfo('())\n',
                     0, 4, ')', None, ((0, 0), (0, 1), (2, 0), (3, 0))),
            TestInfo(')(\n', 0, 3, '(', 1, ((0, 0), (1, 0), (1, 1))),
            # Wrong closers still decrement stack level.
            TestInfo('{)(]\n',
                     0, 5, ']', None, ((0, 0), (0, 1), (2, 0), (2, 1), (4, 0))),
            # Character after backslash.
            TestInfo(':\\a\n', 0, 4, '\\a', None, ((0, 0),)),
            TestInfo('\n', 0, 0, '', None, ((0, 0),)),
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                study()
                eq(p.study_level, 2)
                eq(p.stmt_start, test.start)
                eq(p.stmt_end, test.end)
                eq(p.lastch, test.lastch)
                eq(p.lastopenbracketpos, test.openbracket)
                eq(p.stmt_bracketing, test.bracketing)

        # Called again, just returns without reprocessing.
        self.assertIsNone(study())

    def test_get_num_lines_in_stmt(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        getlines = p.get_num_lines_in_stmt

        TestInfo = namedtuple('TestInfo', ['string', 'lines'])
        tests = (
            TestInfo('[x for x in a]\n', 1),      # Closed on one line.
            TestInfo('[x\nfor x in a\n', 2),      # Not closed.
            TestInfo('[x\\\nfor x in a\\\n', 2),  # "", unneeded backslashes.
            TestInfo('[x\nfor x in a\n]\n', 3),   # Closed on multi-line.
            TestInfo('\n"""Docstring comment L1"""\nL2\nL3\nL4\n', 1),
            TestInfo('\n"""Docstring comment L1\nL2"""\nL3\nL4\n', 1),
            TestInfo('\n"""Docstring comment L1\\\nL2\\\nL3\\\nL4\\\n', 4),
            TestInfo('\n\n"""Docstring comment L1\\\nL2\\\nL3\\\nL4\\\n"""\n', 5)
            )

        # Blank string doesn't have enough elements in goodlines.
        setcode('')
        with self.assertRaises(IndexError):
            getlines()

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                eq(getlines(), test.lines)

    def test_compute_bracket_indent(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        indent = p.compute_bracket_indent

        TestInfo = namedtuple('TestInfo', ['string', 'spaces'])
        tests = (
            TestInfo('def function1(self, a,\n', 14),
            # Characters after bracket.
            TestInfo('\n    def function1(self, a,\n', 18),
            TestInfo('\n\tdef function1(self, a,\n', 18),
            # No characters after bracket.
            TestInfo('\n    def function1(\n', 8),
            TestInfo('\n\tdef function1(\n', 8),
            TestInfo('\n    def function1(  \n', 8),  # Ignore extra spaces.
            TestInfo('[\n"first item",\n  # Comment line\n    "next item",\n', 0),
            TestInfo('[\n  "first item",\n  # Comment line\n    "next item",\n', 2),
            TestInfo('["first item",\n  # Comment line\n    "next item",\n', 1),
            TestInfo('(\n', 4),
            TestInfo('(a\n', 1),
             )

        # Must be C_BRACKET continuation type.
        setcode('def function1(self, a, b):\n')
        with self.assertRaises(AssertionError):
            indent()

        for test in tests:
            setcode(test.string)
            eq(indent(), test.spaces)

    def test_compute_backslash_indent(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        indent = p.compute_backslash_indent

        # Must be C_BACKSLASH continuation type.
        errors = (('def function1(self, a, b\\\n'),  # Bracket.
                  ('    """ (\\\n'),                 # Docstring.
                  ('a = #\\\n'),                     # Inline comment.
                  )
        for string in errors:
            with self.subTest(string=string):
                setcode(string)
                with self.assertRaises(AssertionError):
                    indent()

        TestInfo = namedtuple('TestInfo', ('string', 'spaces'))
        tests = (TestInfo('a = (1 + 2) - 5 *\\\n', 4),
                 TestInfo('a = 1 + 2 - 5 *\\\n', 4),
                 TestInfo('    a = 1 + 2 - 5 *\\\n', 8),
                 TestInfo('  a = "spam"\\\n', 6),
                 TestInfo('  a = \\\n"a"\\\n', 4),
                 TestInfo('  a = #\\\n"a"\\\n', 5),
                 TestInfo('a == \\\n', 2),
                 TestInfo('a != \\\n', 2),
                 # Difference between containing = and those not.
                 TestInfo('\\\n', 2),
                 TestInfo('    \\\n', 6),
                 TestInfo('\t\\\n', 6),
                 TestInfo('a\\\n', 3),
                 TestInfo('{}\\\n', 4),
                 TestInfo('(1 + 2) - 5 *\\\n', 3),
                 )
        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                eq(indent(), test.spaces)

    def test_get_base_indent_string(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        baseindent = p.get_base_indent_string

        TestInfo = namedtuple('TestInfo', ['string', 'indent'])
        tests = (TestInfo('', ''),
                 TestInfo('def a():\n', ''),
                 TestInfo('\tdef a():\n', '\t'),
                 TestInfo('    def a():\n', '    '),
                 TestInfo('    def a(\n', '    '),
                 TestInfo('\t\n    def a(\n', '    '),
                 TestInfo('\t\n    # Comment.\n', '    '),
                 )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                eq(baseindent(), test.indent)

    def test_is_block_opener(self):
        yes = self.assertTrue
        no = self.assertFalse
        p = self.parser
        setcode = p.set_code
        opener = p.is_block_opener

        TestInfo = namedtuple('TestInfo', ['string', 'assert_'])
        tests = (
            TestInfo('def a():\n', yes),
            TestInfo('\n   def function1(self, a,\n                 b):\n', yes),
            TestInfo(':\n', yes),
            TestInfo('a:\n', yes),
            TestInfo('):\n', yes),
            TestInfo('(:\n', yes),
            TestInfo('":\n', no),
            TestInfo('\n   def function1(self, a,\n', no),
            TestInfo('def function1(self, a):\n    pass\n', no),
            TestInfo('# A comment:\n', no),
            TestInfo('"""A docstring:\n', no),
            TestInfo('"""A docstring:\n', no),
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                test.assert_(opener())

    def test_is_block_closer(self):
        yes = self.assertTrue
        no = self.assertFalse
        p = self.parser
        setcode = p.set_code
        closer = p.is_block_closer

        TestInfo = namedtuple('TestInfo', ['string', 'assert_'])
        tests = (
            TestInfo('return\n', yes),
            TestInfo('\tbreak\n', yes),
            TestInfo('  continue\n', yes),
            TestInfo('     raise\n', yes),
            TestInfo('pass    \n', yes),
            TestInfo('pass\t\n', yes),
            TestInfo('return #\n', yes),
            TestInfo('raised\n', no),
            TestInfo('returning\n', no),
            TestInfo('# return\n', no),
            TestInfo('"""break\n', no),
            TestInfo('"continue\n', no),
            TestInfo('def function1(self, a):\n    pass\n', yes),
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                test.assert_(closer())

    def test_get_last_stmt_bracketing(self):
        eq = self.assertEqual
        p = self.parser
        setcode = p.set_code
        bracketing = p.get_last_stmt_bracketing

        TestInfo = namedtuple('TestInfo', ['string', 'bracket'])
        tests = (
            TestInfo('', ((0, 0),)),
            TestInfo('a\n', ((0, 0),)),
            TestInfo('()()\n', ((0, 0), (0, 1), (2, 0), (2, 1), (4, 0))),
            TestInfo('(\n)()\n', ((0, 0), (0, 1), (3, 0), (3, 1), (5, 0))),
            TestInfo('()\n()\n', ((3, 0), (3, 1), (5, 0))),
            TestInfo('()(\n)\n', ((0, 0), (0, 1), (2, 0), (2, 1), (5, 0))),
            TestInfo('(())\n', ((0, 0), (0, 1), (1, 2), (3, 1), (4, 0))),
            TestInfo('(\n())\n', ((0, 0), (0, 1), (2, 2), (4, 1), (5, 0))),
            # Same as matched test.
            TestInfo('{)(]\n', ((0, 0), (0, 1), (2, 0), (2, 1), (4, 0))),
            TestInfo('(((())\n',
                     ((0, 0), (0, 1), (1, 2), (2, 3), (3, 4), (5, 3), (6, 2))),
            )

        for test in tests:
            with self.subTest(string=test.string):
                setcode(test.string)
                eq(bracketing(), test.bracket)


if __name__ == '__main__':
    unittest.main(verbosity=2)
