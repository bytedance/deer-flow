"""
Unit tests for refactor.py.
"""

import sys
import os
import codecs
import io
import re
import tempfile
import shutil
import unittest

from lib2to3 import refactor, pygram, fixer_base
from lib2to3.pgen2 import token


TEST_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FIXER_DIR = os.path.join(TEST_DATA_DIR, "fixers")

sys.path.append(FIXER_DIR)
try:
    _DEFAULT_FIXERS = refactor.get_fixers_from_package("myfixes")
finally:
    sys.path.pop()

_2TO3_FIXERS = refactor.get_fixers_from_package("lib2to3.fixes")

class TestRefactoringTool(unittest.TestCase):

    def setUp(self):
        sys.path.append(FIXER_DIR)

    def tearDown(self):
        sys.path.pop()

    def check_instances(self, instances, classes):
        for inst, cls in zip(instances, classes):
            if not isinstance(inst, cls):
                self.fail("%s are not instances of %s" % instances, classes)

    def rt(self, options=None, fixers=_DEFAULT_FIXERS, explicit=None):
        return refactor.RefactoringTool(fixers, options, explicit)

    def test_print_function_option(self):
        rt = self.rt({"print_function" : True})
        self.assertNotIn("print", rt.grammar.keywords)
        self.assertNotIn("print", rt.driver.grammar.keywords)

    def test_exec_function_option(self):
        rt = self.rt({"exec_function" : True})
        self.assertNotIn("exec", rt.grammar.keywords)
        self.assertNotIn("exec", rt.driver.grammar.keywords)

    def test_write_unchanged_files_option(self):
        rt = self.rt()
        self.assertFalse(rt.write_unchanged_files)
        rt = self.rt({"write_unchanged_files" : True})
        self.assertTrue(rt.write_unchanged_files)

    def test_fixer_loading_helpers(self):
        contents = ["explicit", "first", "last", "parrot", "preorder"]
        non_prefixed = refactor.get_all_fix_names("myfixes")
        prefixed = refactor.get_all_fix_names("myfixes", False)
        full_names = refactor.get_fixers_from_package("myfixes")
        self.assertEqual(prefixed, ["fix_" + name for name in contents])
        self.assertEqual(non_prefixed, contents)
        self.assertEqual(full_names,
                         ["myfixes.fix_" + name for name in contents])

    def test_detect_future_features(self):
        run = refactor._detect_future_features
        fs = frozenset
        empty = fs()
        self.assertEqual(run(""), empty)
        self.assertEqual(run("from __future__ import print_function"),
                         fs(("print_function",)))
        self.assertEqual(run("from __future__ import generators"),
                         fs(("generators",)))
        self.assertEqual(run("from __future__ import generators, feature"),
                         fs(("generators", "feature")))
        inp = "from __future__ import generators, print_function"
        self.assertEqual(run(inp), fs(("generators", "print_function")))
        inp ="from __future__ import print_function, generators"
        self.assertEqual(run(inp), fs(("print_function", "generators")))
        inp = "from __future__ import (print_function,)"
        self.assertEqual(run(inp), fs(("print_function",)))
        inp = "from __future__ import (generators, print_function)"
        self.assertEqual(run(inp), fs(("generators", "print_function")))
        inp = "from __future__ import (generators, nested_scopes)"
        self.assertEqual(run(inp), fs(("generators", "nested_scopes")))
        inp = """from __future__ import generators
from __future__ import print_function"""
        self.assertEqual(run(inp), fs(("generators", "print_function")))
        invalid = ("from",
                   "from 4",
                   "from x",
                   "from x 5",
                   "from x im",
                   "from x import",
                   "from x import 4",
                   )
        for inp in invalid:
            self.assertEqual(run(inp), empty)
        inp = "'docstring'\nfrom __future__ import print_function"
        self.assertEqual(run(inp), fs(("print_function",)))
        inp = "'docstring'\n'somng'\nfrom __future__ import print_function"
        self.assertEqual(run(inp), empty)
        inp = "# comment\nfrom __future__ import print_function"
        self.assertEqual(run(inp), fs(("print_function",)))
        inp = "# comment\n'doc'\nfrom __future__ import print_function"
        self.assertEqual(run(inp), fs(("print_function",)))
        inp = "class x: pass\nfrom __future__ import print_function"
        self.assertEqual(run(inp), empty)

    def test_get_headnode_dict(self):
        class NoneFix(fixer_base.BaseFix):
            pass

        class FileInputFix(fixer_base.BaseFix):
            PATTERN = "file_input< any * >"

        class SimpleFix(fixer_base.BaseFix):
            PATTERN = "'name'"

        no_head = NoneFix({}, [])
        with_head = FileInputFix({}, [])
        simple = SimpleFix({}, [])
        d = refactor._get_headnode_dict([no_head, with_head, simple])
        top_fixes = d.pop(pygram.python_symbols.file_input)
        self.assertEqual(top_fixes, [with_head, no_head])
        name_fixes = d.pop(token.NAME)
        self.assertEqual(name_fixes, [simple, no_head])
        for fixes in d.values():
            self.assertEqual(fixes, [no_head])

    def test_fixer_loading(self):
        from myfixes.fix_first import FixFirst
        from myfixes.fix_last import FixLast
        from myfixes.fix_parrot import FixParrot
        from myfixes.fix_preorder import FixPreorder

        rt = self.rt()
        pre, post = rt.get_fixers()

        self.check_instances(pre, [FixPreorder])
        self.check_instances(post, [FixFirst, FixParrot, FixLast])

    def test_naughty_fixers(self):
        self.assertRaises(ImportError, self.rt, fixers=["not_here"])
        self.assertRaises(refactor.FixerError, self.rt, fixers=["no_fixer_cls"])
        self.assertRaises(refactor.FixerError, self.rt, fixers=["bad_order"])

    def test_refactor_string(self):
        rt = self.rt()
        input = "def parrot(): pass\n\n"
        tree = rt.refactor_string(input, "<test>")
        self.assertNotEqual(str(tree), input)

        input = "def f(): pass\n\n"
        tree = rt.refactor_string(input, "<test>")
        self.assertEqual(str(tree), input)

    def test_refactor_stdin(self):

        class MyRT(refactor.RefactoringTool):

            def print_output(self, old_text, new_text, filename, equal):
                results.extend([old_text, new_text, filename, equal])

        results = []
        rt = MyRT(_DEFAULT_FIXERS)
        save = sys.stdin
        sys.stdin = io.StringIO("def parrot(): pass\n\n")
        try:
            rt.refactor_stdin()
        finally:
            sys.stdin = save
        expected = ["def parrot(): pass\n\n",
                    "def cheese(): pass\n\n",
                    "<stdin>", False]
        self.assertEqual(results, expected)

    def check_file_refactoring(self, test_file, fixers=_2TO3_FIXERS,
                               options=None, mock_log_debug=None,
                               actually_write=True):
        test_file = self.init_test_file(test_file)
        old_contents = self.read_file(test_file)
        rt = self.rt(fixers=fixers, options=options)
        if mock_log_debug:
            rt.log_debug = mock_log_debug

        rt.refactor_file(test_file)
        self.assertEqual(old_contents, self.read_file(test_file))

        if not actually_write:
            return
        rt.refactor_file(test_file, True)
        new_contents = self.read_file(test_file)
        self.assertNotEqual(old_contents, new_contents)
        return new_contents

    def init_test_file(self, test_file):
        tmpdir = tempfile.mkdtemp(prefix="2to3-test_refactor")
        self.addCleanup(shutil.rmtree, tmpdir)
        shutil.copy(test_file, tmpdir)
        test_file = os.path.join(tmpdir, os.path.basename(test_file))
        os.chmod(test_file, 0o644)
        return test_file

    def read_file(self, test_file):
        with open(test_file, "rb") as fp:
            return fp.read()

    def refactor_file(self, test_file, fixers=_2TO3_FIXERS):
        test_file = self.init_test_file(test_file)
        old_contents = self.read_file(test_file)
        rt = self.rt(fixers=fixers)
        rt.refactor_file(test_file, True)
        new_contents = self.read_file(test_file)
        return old_contents, new_contents

    def test_refactor_file(self):
        test_file = os.path.join(FIXER_DIR, "parrot_example.py")
        self.check_file_refactoring(test_file, _DEFAULT_FIXERS)

    def test_refactor_file_write_unchanged_file(self):
        test_file = os.path.join(FIXER_DIR, "parrot_example.py")
        debug_messages = []
        def recording_log_debug(msg, *args):
            debug_messages.append(msg % args)
        self.check_file_refactoring(test_file, fixers=(),
                                    options={"write_unchanged_files": True},
                                    mock_log_debug=recording_log_debug,
                                    actually_write=False)
        # Testing that it logged this message when write=False was passed is
        # sufficient to see that it did not bail early after "No changes".
        message_regex = r"Not writing changes to .*%s" % \
                re.escape(os.sep + os.path.basename(test_file))
        for message in debug_messages:
            if "Not writing changes" in message:
                self.assertRegex(message, message_regex)
                break
        else:
            self.fail("%r not matched in %r" % (message_regex, debug_messages))

    def test_refactor_dir(self):
        def check(structure, expected):
            def mock_refactor_file(self, f, *args):
                got.append(f)
            save_func = refactor.RefactoringTool.refactor_file
            refactor.RefactoringTool.refactor_file = mock_refactor_file
            rt = self.rt()
            got = []
            dir = tempfile.mkdtemp(prefix="2to3-test_refactor")
            try:
                os.mkdir(os.path.join(dir, "a_dir"))
                for fn in structure:
                    open(os.path.join(dir, fn), "wb").close()
                rt.refactor_dir(dir)
            finally:
                refactor.RefactoringTool.refactor_file = save_func
                shutil.rmtree(dir)
            self.assertEqual(got,
                             [os.path.join(dir, path) for path in expected])
        check([], [])
        tree = ["nothing",
                "hi.py",
                ".dumb",
                ".after.py",
                "notpy.npy",
                "sappy"]
        expected = ["hi.py"]
        check(tree, expected)
        tree = ["hi.py",
                os.path.join("a_dir", "stuff.py")]
        check(tree, tree)

    def test_file_encoding(self):
        fn = os.path.join(TEST_DATA_DIR, "different_encoding.py")
        self.check_file_refactoring(fn)

    def test_false_file_encoding(self):
        fn = os.path.join(TEST_DATA_DIR, "false_encoding.py")
        data = self.check_file_refactoring(fn)

    def test_bom(self):
        fn = os.path.join(TEST_DATA_DIR, "bom.py")
        data = self.check_file_refactoring(fn)
        self.assertTrue(data.startswith(codecs.BOM_UTF8))

    def test_crlf_newlines(self):
        old_sep = os.linesep
        os.linesep = "\r\n"
        try:
            fn = os.path.join(TEST_DATA_DIR, "crlf.py")
            fixes = refactor.get_fixers_from_package("lib2to3.fixes")
            self.check_file_refactoring(fn, fixes)
        finally:
            os.linesep = old_sep

    def test_crlf_unchanged(self):
        fn = os.path.join(TEST_DATA_DIR, "crlf.py")
        old, new = self.refactor_file(fn)
        self.assertIn(b"\r\n", old)
        self.assertIn(b"\r\n", new)
        self.assertNotIn(b"\r\r\n", new)

    def test_refactor_docstring(self):
        rt = self.rt()

        doc = """
>>> example()
42
"""
        out = rt.refactor_docstring(doc, "<test>")
        self.assertEqual(out, doc)

        doc = """
>>> def parrot():
...      return 43
"""
        out = rt.refactor_docstring(doc, "<test>")
        self.assertNotEqual(out, doc)

    def test_explicit(self):
        from myfixes.fix_explicit import FixExplicit

        rt = self.rt(fixers=["myfixes.fix_explicit"])
        self.assertEqual(len(rt.post_order), 0)

        rt = self.rt(explicit=["myfixes.fix_explicit"])
        for fix in rt.post_order:
            if isinstance(fix, FixExplicit):
                break
        else:
            self.fail("explicit fixer not loaded")
