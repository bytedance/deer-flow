"""Support code for test_*.py files"""
# Author: Collin Winter

# Python imports
import unittest
import os
import os.path
from textwrap import dedent

# Local imports
from lib2to3 import pytree, refactor
from lib2to3.pgen2 import driver as pgen2_driver

test_dir = os.path.dirname(__file__)
proj_dir = os.path.normpath(os.path.join(test_dir, ".."))
grammar_path = os.path.join(test_dir, "..", "Grammar.txt")
grammar = pgen2_driver.load_grammar(grammar_path)
grammar_no_print_statement = pgen2_driver.load_grammar(grammar_path)
del grammar_no_print_statement.keywords["print"]
driver = pgen2_driver.Driver(grammar, convert=pytree.convert)
driver_no_print_statement = pgen2_driver.Driver(
    grammar_no_print_statement,
    convert=pytree.convert
)

def parse_string(string):
    return driver.parse_string(reformat(string), debug=True)

def run_all_tests(test_mod=None, tests=None):
    if tests is None:
        tests = unittest.TestLoader().loadTestsFromModule(test_mod)
    unittest.TextTestRunner(verbosity=2).run(tests)

def reformat(string):
    return dedent(string) + "\n\n"

def get_refactorer(fixer_pkg="lib2to3", fixers=None, options=None):
    """
    A convenience function for creating a RefactoringTool for tests.

    fixers is a list of fixers for the RefactoringTool to use. By default
    "lib2to3.fixes.*" is used. options is an optional dictionary of options to
    be passed to the RefactoringTool.
    """
    if fixers is not None:
        fixers = [fixer_pkg + ".fixes.fix_" + fix for fix in fixers]
    else:
        fixers = refactor.get_fixers_from_package(fixer_pkg + ".fixes")
    options = options or {}
    return refactor.RefactoringTool(fixers, options, explicit=True)

def all_project_files():
    for dirpath, dirnames, filenames in os.walk(proj_dir):
        for filename in filenames:
            if filename.endswith(".py"):
                yield os.path.join(dirpath, filename)

TestCase = unittest.TestCase
