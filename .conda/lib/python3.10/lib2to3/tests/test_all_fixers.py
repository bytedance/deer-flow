"""Tests that run all fixer modules over an input stream.

This has been broken out into its own test module because of its
running time.
"""
# Author: Collin Winter

# Python imports
import os.path
import sys
import test.support
import unittest

# Local imports
from . import support


@test.support.requires_resource('cpu')
class Test_all(support.TestCase):

    def setUp(self):
        self.refactor = support.get_refactorer()

    def refactor_file(self, filepath):
        if test.support.verbose:
            print(f"Refactor file: {filepath}")
        if os.path.basename(filepath) == 'infinite_recursion.py':
            # bpo-46542: Processing infinite_recursion.py can crash Python
            # if Python is built in debug mode: lower the recursion limit
            # to prevent a crash.
            with test.support.infinite_recursion(150):
                self.refactor.refactor_file(filepath)
        else:
            self.refactor.refactor_file(filepath)

    def test_all_project_files(self):
        for filepath in support.all_project_files():
            with self.subTest(filepath=filepath):
                self.refactor_file(filepath)

if __name__ == '__main__':
    unittest.main()
