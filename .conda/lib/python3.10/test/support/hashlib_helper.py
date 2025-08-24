import functools
import hashlib
import unittest

try:
    import _hashlib
except ImportError:
    _hashlib = None


def requires_hashdigest(digestname, openssl=None, usedforsecurity=True):
    """Decorator raising SkipTest if a hashing algorithm is not available

    The hashing algorithm could be missing or blocked by a strict crypto
    policy.

    If 'openssl' is True, then the decorator checks that OpenSSL provides
    the algorithm. Otherwise the check falls back to built-in
    implementations. The usedforsecurity flag is passed to the constructor.

    ValueError: [digital envelope routines: EVP_DigestInit_ex] disabled for FIPS
    ValueError: unsupported hash type md4
    """
    def decorator(func_or_class):
        if isinstance(func_or_class, type):
            setUpClass = func_or_class.__dict__.get('setUpClass')
            if setUpClass is None:
                def setUpClass(cls):
                    super(func_or_class, cls).setUpClass()
                setUpClass.__qualname__ = func_or_class.__qualname__ + '.setUpClass'
                setUpClass.__module__ = func_or_class.__module__
            else:
                setUpClass = setUpClass.__func__
            setUpClass = classmethod(decorator(setUpClass))
            func_or_class.setUpClass = setUpClass
            return func_or_class

        @functools.wraps(func_or_class)
        def wrapper(*args, **kwargs):
            try:
                if openssl and _hashlib is not None:
                    _hashlib.new(digestname, usedforsecurity=usedforsecurity)
                else:
                    hashlib.new(digestname, usedforsecurity=usedforsecurity)
            except ValueError:
                raise unittest.SkipTest(
                    f"hash digest '{digestname}' is not available."
                )
            return func_or_class(*args, **kwargs)
        return wrapper
    return decorator
