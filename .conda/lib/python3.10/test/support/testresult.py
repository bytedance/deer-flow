'''Test runner and result class for the regression test suite.

'''

import functools
import io
import sys
import time
import traceback
import unittest

class RegressionTestResult(unittest.TextTestResult):
    USE_XML = False

    def __init__(self, stream, descriptions, verbosity):
        super().__init__(stream=stream, descriptions=descriptions,
                         verbosity=2 if verbosity else 0)
        self.buffer = True
        if self.USE_XML:
            from xml.etree import ElementTree as ET
            from datetime import datetime
            self.__ET = ET
            self.__suite = ET.Element('testsuite')
            self.__suite.set('start', datetime.utcnow().isoformat(' '))
            self.__e = None
        self.__start_time = None

    @classmethod
    def __getId(cls, test):
        try:
            test_id = test.id
        except AttributeError:
            return str(test)
        try:
            return test_id()
        except TypeError:
            return str(test_id)
        return repr(test)

    def startTest(self, test):
        super().startTest(test)
        if self.USE_XML:
            self.__e = e = self.__ET.SubElement(self.__suite, 'testcase')
        self.__start_time = time.perf_counter()

    def _add_result(self, test, capture=False, **args):
        if not self.USE_XML:
            return
        e = self.__e
        self.__e = None
        if e is None:
            return
        ET = self.__ET

        e.set('name', args.pop('name', self.__getId(test)))
        e.set('status', args.pop('status', 'run'))
        e.set('result', args.pop('result', 'completed'))
        if self.__start_time:
            e.set('time', f'{time.perf_counter() - self.__start_time:0.6f}')

        if capture:
            if self._stdout_buffer is not None:
                stdout = self._stdout_buffer.getvalue().rstrip()
                ET.SubElement(e, 'system-out').text = stdout
            if self._stderr_buffer is not None:
                stderr = self._stderr_buffer.getvalue().rstrip()
                ET.SubElement(e, 'system-err').text = stderr

        for k, v in args.items():
            if not k or not v:
                continue
            e2 = ET.SubElement(e, k)
            if hasattr(v, 'items'):
                for k2, v2 in v.items():
                    if k2:
                        e2.set(k2, str(v2))
                    else:
                        e2.text = str(v2)
            else:
                e2.text = str(v)

    @classmethod
    def __makeErrorDict(cls, err_type, err_value, err_tb):
        if isinstance(err_type, type):
            if err_type.__module__ == 'builtins':
                typename = err_type.__name__
            else:
                typename = f'{err_type.__module__}.{err_type.__name__}'
        else:
            typename = repr(err_type)

        msg = traceback.format_exception(err_type, err_value, None)
        tb = traceback.format_exception(err_type, err_value, err_tb)

        return {
            'type': typename,
            'message': ''.join(msg),
            '': ''.join(tb),
        }

    def addError(self, test, err):
        self._add_result(test, True, error=self.__makeErrorDict(*err))
        super().addError(test, err)

    def addExpectedFailure(self, test, err):
        self._add_result(test, True, output=self.__makeErrorDict(*err))
        super().addExpectedFailure(test, err)

    def addFailure(self, test, err):
        self._add_result(test, True, failure=self.__makeErrorDict(*err))
        super().addFailure(test, err)

    def addSkip(self, test, reason):
        self._add_result(test, skipped=reason)
        super().addSkip(test, reason)

    def addSuccess(self, test):
        self._add_result(test)
        super().addSuccess(test)

    def addUnexpectedSuccess(self, test):
        self._add_result(test, outcome='UNEXPECTED_SUCCESS')
        super().addUnexpectedSuccess(test)

    def get_xml_element(self):
        if not self.USE_XML:
            raise ValueError("USE_XML is false")
        e = self.__suite
        e.set('tests', str(self.testsRun))
        e.set('errors', str(len(self.errors)))
        e.set('failures', str(len(self.failures)))
        return e

class QuietRegressionTestRunner:
    def __init__(self, stream, buffer=False):
        self.result = RegressionTestResult(stream, None, 0)
        self.result.buffer = buffer

    def run(self, test):
        test(self.result)
        return self.result

def get_test_runner_class(verbosity, buffer=False):
    if verbosity:
        return functools.partial(unittest.TextTestRunner,
                                 resultclass=RegressionTestResult,
                                 buffer=buffer,
                                 verbosity=verbosity)
    return functools.partial(QuietRegressionTestRunner, buffer=buffer)

def get_test_runner(stream, verbosity, capture_output=False):
    return get_test_runner_class(verbosity, capture_output)(stream)

if __name__ == '__main__':
    import xml.etree.ElementTree as ET
    RegressionTestResult.USE_XML = True

    class TestTests(unittest.TestCase):
        def test_pass(self):
            pass

        def test_pass_slow(self):
            time.sleep(1.0)

        def test_fail(self):
            print('stdout', file=sys.stdout)
            print('stderr', file=sys.stderr)
            self.fail('failure message')

        def test_error(self):
            print('stdout', file=sys.stdout)
            print('stderr', file=sys.stderr)
            raise RuntimeError('error message')

    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestTests))
    stream = io.StringIO()
    runner_cls = get_test_runner_class(sum(a == '-v' for a in sys.argv))
    runner = runner_cls(sys.stdout)
    result = runner.run(suite)
    print('Output:', stream.getvalue())
    print('XML: ', end='')
    for s in ET.tostringlist(result.get_xml_element()):
        print(s.decode(), end='')
    print()
