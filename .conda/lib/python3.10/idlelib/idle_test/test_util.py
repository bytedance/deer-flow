"""Test util, coverage 100%"""

import unittest
from idlelib import util


class UtilTest(unittest.TestCase):
    def test_extensions(self):
        for extension in {'.pyi', '.py', '.pyw'}:
            self.assertIn(extension, util.py_extensions)


if __name__ == '__main__':
    unittest.main(verbosity=2)
