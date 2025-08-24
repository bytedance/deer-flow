"Test rpc, coverage 20%."

from idlelib import rpc
import unittest



class CodePicklerTest(unittest.TestCase):

    def test_pickle_unpickle(self):
        def f(): return a + b + c
        func, (cbytes,) = rpc.pickle_code(f.__code__)
        self.assertIs(func, rpc.unpickle_code)
        self.assertIn(b'test_rpc.py', cbytes)
        code = rpc.unpickle_code(cbytes)
        self.assertEqual(code.co_names, ('a', 'b', 'c'))

    def test_code_pickler(self):
        self.assertIn(type((lambda:None).__code__),
                      rpc.CodePickler.dispatch_table)

    def test_dumps(self):
        def f(): pass
        # The main test here is that pickling code does not raise.
        self.assertIn(b'test_rpc.py', rpc.dumps(f.__code__))


if __name__ == '__main__':
    unittest.main(verbosity=2)
