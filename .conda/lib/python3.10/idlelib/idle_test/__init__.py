'''idlelib.idle_test is a private implementation of test.test_idle,
which tests the IDLE application as part of the stdlib test suite.
Run IDLE tests alone with "python -m test.test_idle".
Starting with Python 3.6, IDLE requires tcl/tk 8.5 or later.

This package and its contained modules are subject to change and
any direct use is at your own risk.
'''
from os.path import dirname

def load_tests(loader, standard_tests, pattern):
    this_dir = dirname(__file__)
    top_dir = dirname(dirname(this_dir))
    package_tests = loader.discover(start_dir=this_dir, pattern='test*.py',
                                    top_level_dir=top_dir)
    standard_tests.addTests(package_tests)
    return standard_tests
