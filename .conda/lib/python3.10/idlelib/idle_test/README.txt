README FOR IDLE TESTS IN IDLELIB.IDLE_TEST

0. Quick Start

Automated unit tests were added in 3.3 for Python 3.x.
To run the tests from a command line:

python -m test.test_idle

Human-mediated tests were added later in 3.4.

python -m idlelib.idle_test.htest


1. Test Files

The idle directory, idlelib, has over 60 xyz.py files. The idle_test
subdirectory contains test_xyz.py for each implementation file xyz.py.
To add a test for abc.py, open idle_test/template.py and immediately
Save As test_abc.py.  Insert 'abc' on the first line, and replace
'zzdummy' with 'abc.

Remove the imports of requires and tkinter if not needed.  Otherwise,
add to the tkinter imports as needed.

Add a prefix to 'Test' for the initial test class.  The template class
contains code needed or possibly needed for gui tests.  See the next
section if doing gui tests.  If not, and not needed for further classes,
this code can be removed.

Add the following at the end of abc.py.  If an htest was added first,
insert the import and main lines before the htest lines.

if __name__ == "__main__":
    from unittest import main
    main('idlelib.idle_test.test_abc', verbosity=2, exit=False)

The ', exit=False' is only needed if an htest follows.



2. GUI Tests

When run as part of the Python test suite, Idle GUI tests need to run
test.support.requires('gui').  A test is a GUI test if it creates a
tkinter.Tk root or master object either directly or indirectly by
instantiating a tkinter or idle class.  GUI tests cannot run in test
processes that either have no graphical environment available or are not
allowed to use it.

To guard a module consisting entirely of GUI tests, start with

from test.support import requires
requires('gui')

To guard a test class, put "requires('gui')" in its setUpClass function.
The template.py file does this.

To avoid interfering with other GUI tests, all GUI objects must be
destroyed and deleted by the end of the test.  The Tk root created in a
setUpX function should be destroyed in the corresponding tearDownX and
the module or class attribute deleted.  Others widgets should descend
from the single root and the attributes deleted BEFORE root is
destroyed.  See https://bugs.python.org/issue20567.

    @classmethod
    def setUpClass(cls):
        requires('gui')
        cls.root = tk.Tk()
        cls.text = tk.Text(root)

    @classmethod
    def tearDownClass(cls):
        del cls.text
        cls.root.update_idletasks()
        cls.root.destroy()
        del cls.root

The update_idletasks call is sometimes needed to prevent the following
warning either when running a test alone or as part of the test suite
(#27196).  It should not hurt if not needed.

  can't invoke "event" command: application has been destroyed
  ...
  "ttk::ThemeChanged"

If a test creates instance 'e' of EditorWindow, call 'e._close()' before
or as the first part of teardown.  The effect of omitting this depends
on the later shutdown.  Then enable the after_cancel loop in the
template.  This prevents messages like the following.

bgerror failed to handle background error.
    Original error: invalid command name "106096696timer_event"
    Error in bgerror: can't invoke "tk" command: application has been destroyed

Requires('gui') causes the test(s) it guards to be skipped if any of
these conditions are met:

 - The tests are being run by regrtest.py, and it was started without
   enabling the "gui" resource with the "-u" command line option.

 - The tests are being run on Windows by a service that is not allowed
   to interact with the graphical environment.

 - The tests are being run on Linux and X Windows is not available.

 - The tests are being run on Mac OSX in a process that cannot make a
   window manager connection.

 - tkinter.Tk cannot be successfully instantiated for some reason.

 - test.support.use_resources has been set by something other than
   regrtest.py and does not contain "gui".

Tests of non-GUI operations should avoid creating tk widgets. Incidental
uses of tk variables and messageboxes can be replaced by the mock
classes in idle_test/mock_tk.py. The mock text handles some uses of the
tk Text widget.


3. Running Unit Tests

Assume that xyz.py and test_xyz.py both end with a unittest.main() call.
Running either from an Idle editor runs all tests in the test_xyz file
with the version of Python running Idle.  Test output appears in the
Shell window.  The 'verbosity=2' option lists all test methods in the
file, which is appropriate when developing tests. The 'exit=False'
option is needed in xyx.py files when an htest follows.

The following command lines also run all test methods, including
GUI tests, in test_xyz.py. (Both '-m idlelib' and '-m idlelib.idle'
start Idle and so cannot run tests.)

python -m idlelib.xyz
python -m idlelib.idle_test.test_xyz

The following runs all idle_test/test_*.py tests interactively.

>>> import unittest
>>> unittest.main('idlelib.idle_test', verbosity=2)

The following run all Idle tests at a command line.  Option '-v' is the
same as 'verbosity=2'.

python -m unittest -v idlelib.idle_test
python -m test -v -ugui test_idle
python -m test.test_idle

The idle tests are 'discovered' by
idlelib.idle_test.__init__.load_tests, which is also imported into
test.test_idle. Normally, neither file should be changed when working on
individual test modules. The third command runs unittest indirectly
through regrtest. The same happens when the entire test suite is run
with 'python -m test'. So that command must work for buildbots to stay
green. Idle tests must not disturb the environment in a way that makes
other tests fail (issue 18081).

To run an individual Testcase or test method, extend the dotted name
given to unittest on the command line or use the test -m option.  The
latter allows use of other regrtest options.  When using the latter,
all components of the pattern must be present, but any can be replaced
by '*'.

python -m unittest -v idlelib.idle_test.test_xyz.Test_case.test_meth
python -m test -m idlelib.idle_test.text_xyz.Test_case.test_meth test_idle

The test suite can be run in an IDLE user process from Shell.
>>> import test.autotest  # Issue 25588, 2017/10/13, 3.6.4, 3.7.0a2.
There are currently failures not usually present, and this does not
work when run from the editor.


4. Human-mediated Tests

Human-mediated tests are widget tests that cannot be automated but need
human verification. They are contained in idlelib/idle_test/htest.py,
which has instructions.  (Some modules need an auxiliary function,
identified with "# htest # on the header line.)  The set is about
complete, though some tests need improvement. To run all htests, run the
htest file from an editor or from the command line with:

python -m idlelib.idle_test.htest


5. Test Coverage

Install the coverage package into your Python 3.6 site-packages
directory.  (Its exact location depends on the OS).
> python3 -m pip install coverage
(On Windows, replace 'python3 with 'py -3.6' or perhaps just 'python'.)

The problem with running coverage with repository python is that
coverage uses absolute imports for its submodules, hence it needs to be
in a directory in sys.path.  One solution: copy the package to the
directory containing the cpython repository.  Call it 'dev'.  Then run
coverage either directly or from a script in that directory so that
'dev' is prepended to sys.path.

Either edit or add dev/.coveragerc so it looks something like this.
---
# .coveragerc sets coverage options.
[run]
branch = True

[report]
# Regexes for lines to exclude from consideration
exclude_lines =
    # Don't complain if non-runnable code isn't run:
    if 0:
    if __name__ == .__main__.:

    .*# htest #
    if not _utest:
    if _htest:
---
The additions for IDLE are 'branch = True', to test coverage both ways,
and the last three exclude lines, to exclude things peculiar to IDLE
that are not executed during tests.

A script like the following cover.bat (for Windows) is very handy.
---
@echo off
rem Usage: cover filename [test_ suffix] # proper case required by coverage
rem filename without .py, 2nd parameter if test is not test_filename
setlocal
set py=f:\dev\3x\pcbuild\win32\python_d.exe
set src=idlelib.%1
if "%2" EQU "" set tst=f:/dev/3x/Lib/idlelib/idle_test/test_%1.py
if "%2" NEQ "" set tst=f:/dev/ex/Lib/idlelib/idle_test/test_%2.py

%py% -m coverage run --pylib --source=%src% %tst%
%py% -m coverage report --show-missing
%py% -m coverage html
start htmlcov\3x_Lib_idlelib_%1_py.html
rem Above opens new report; htmlcov\index.html displays report index
---
The second parameter was added for tests of module x not named test_x.
(There were several before modules were renamed, now only one is left.)
