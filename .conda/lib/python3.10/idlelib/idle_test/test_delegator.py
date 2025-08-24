"Test delegator, coverage 100%."

from idlelib.delegator import Delegator
import unittest


class DelegatorTest(unittest.TestCase):

    def test_mydel(self):
        # Test a simple use scenario.

        # Initialize an int delegator.
        mydel = Delegator(int)
        self.assertIs(mydel.delegate, int)
        self.assertEqual(mydel._Delegator__cache, set())
        # Trying to access a non-attribute of int fails.
        self.assertRaises(AttributeError, mydel.__getattr__, 'xyz')

        # Add real int attribute 'bit_length' by accessing it.
        bl = mydel.bit_length
        self.assertIs(bl, int.bit_length)
        self.assertIs(mydel.__dict__['bit_length'], int.bit_length)
        self.assertEqual(mydel._Delegator__cache, {'bit_length'})

        # Add attribute 'numerator'.
        mydel.numerator
        self.assertEqual(mydel._Delegator__cache, {'bit_length', 'numerator'})

        # Delete 'numerator'.
        del mydel.numerator
        self.assertNotIn('numerator', mydel.__dict__)
        # The current implementation leaves  it in the name cache.
        # self.assertIn('numerator', mydel._Delegator__cache)
        # However, this is not required and not part of the specification

        # Change delegate to float, first resetting the attributes.
        mydel.setdelegate(float)  # calls resetcache
        self.assertNotIn('bit_length', mydel.__dict__)
        self.assertEqual(mydel._Delegator__cache, set())
        self.assertIs(mydel.delegate, float)


if __name__ == '__main__':
    unittest.main(verbosity=2, exit=2)
