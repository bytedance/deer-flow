# Common utility functions used by various script execution tests
#  e.g. test_cmd_line, test_cmd_line_script and test_runpy

import collections
import importlib
import sys
import os
import os.path
import subprocess
import py_compile
import zipfile

from importlib.util import source_from_cache
from test import support
from test.support.import_helper import make_legacy_pyc


# Cached result of the expensive test performed in the function below.
__cached_interp_requires_environment = None


def interpreter_requires_environment():
    """
    Returns True if our sys.executable interpreter requires environment
    variables in order to be able to run at all.

    This is designed to be used with @unittest.skipIf() to annotate tests
    that need to use an assert_python*() function to launch an isolated
    mode (-I) or no environment mode (-E) sub-interpreter process.

    A normal build & test does not run into this situation but it can happen
    when trying to run the standard library test suite from an interpreter that
    doesn't have an obvious home with Python's current home finding logic.

    Setting PYTHONHOME is one way to get most of the testsuite to run in that
    situation.  PYTHONPATH or PYTHONUSERSITE are other common environment
    variables that might impact whether or not the interpreter can start.
    """
    global __cached_interp_requires_environment
    if __cached_interp_requires_environment is None:
        # If PYTHONHOME is set, assume that we need it
        if 'PYTHONHOME' in os.environ:
            __cached_interp_requires_environment = True
            return True

        # Try running an interpreter with -E to see if it works or not.
        try:
            subprocess.check_call([sys.executable, '-E',
                                   '-c', 'import sys; sys.exit(0)'])
        except subprocess.CalledProcessError:
            __cached_interp_requires_environment = True
        else:
            __cached_interp_requires_environment = False

    return __cached_interp_requires_environment


class _PythonRunResult(collections.namedtuple("_PythonRunResult",
                                          ("rc", "out", "err"))):
    """Helper for reporting Python subprocess run results"""
    def fail(self, cmd_line):
        """Provide helpful details about failed subcommand runs"""
        # Limit to 80 lines to ASCII characters
        maxlen = 80 * 100
        out, err = self.out, self.err
        if len(out) > maxlen:
            out = b'(... truncated stdout ...)' + out[-maxlen:]
        if len(err) > maxlen:
            err = b'(... truncated stderr ...)' + err[-maxlen:]
        out = out.decode('ascii', 'replace').rstrip()
        err = err.decode('ascii', 'replace').rstrip()
        raise AssertionError("Process return code is %d\n"
                             "command line: %r\n"
                             "\n"
                             "stdout:\n"
                             "---\n"
                             "%s\n"
                             "---\n"
                             "\n"
                             "stderr:\n"
                             "---\n"
                             "%s\n"
                             "---"
                             % (self.rc, cmd_line,
                                out,
                                err))


# Executing the interpreter in a subprocess
def run_python_until_end(*args, **env_vars):
    env_required = interpreter_requires_environment()
    cwd = env_vars.pop('__cwd', None)
    if '__isolated' in env_vars:
        isolated = env_vars.pop('__isolated')
    else:
        isolated = not env_vars and not env_required
    cmd_line = [sys.executable, '-X', 'faulthandler']
    if isolated:
        # isolated mode: ignore Python environment variables, ignore user
        # site-packages, and don't add the current directory to sys.path
        cmd_line.append('-I')
    elif not env_vars and not env_required:
        # ignore Python environment variables
        cmd_line.append('-E')

    # But a special flag that can be set to override -- in this case, the
    # caller is responsible to pass the full environment.
    if env_vars.pop('__cleanenv', None):
        env = {}
        if sys.platform == 'win32':
            # Windows requires at least the SYSTEMROOT environment variable to
            # start Python.
            env['SYSTEMROOT'] = os.environ['SYSTEMROOT']

        # Other interesting environment variables, not copied currently:
        # COMSPEC, HOME, PATH, TEMP, TMPDIR, TMP.
    else:
        # Need to preserve the original environment, for in-place testing of
        # shared library builds.
        env = os.environ.copy()

    # set TERM='' unless the TERM environment variable is passed explicitly
    # see issues #11390 and #18300
    if 'TERM' not in env_vars:
        env['TERM'] = ''

    env.update(env_vars)
    cmd_line.extend(args)
    proc = subprocess.Popen(cmd_line, stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         env=env, cwd=cwd)
    with proc:
        try:
            out, err = proc.communicate()
        finally:
            proc.kill()
            subprocess._cleanup()
    rc = proc.returncode
    return _PythonRunResult(rc, out, err), cmd_line


def _assert_python(expected_success, /, *args, **env_vars):
    res, cmd_line = run_python_until_end(*args, **env_vars)
    if (res.rc and expected_success) or (not res.rc and not expected_success):
        res.fail(cmd_line)
    return res


def assert_python_ok(*args, **env_vars):
    """
    Assert that running the interpreter with `args` and optional environment
    variables `env_vars` succeeds (rc == 0) and return a (return code, stdout,
    stderr) tuple.

    If the __cleanenv keyword is set, env_vars is used as a fresh environment.

    Python is started in isolated mode (command line option -I),
    except if the __isolated keyword is set to False.
    """
    return _assert_python(True, *args, **env_vars)


def assert_python_failure(*args, **env_vars):
    """
    Assert that running the interpreter with `args` and optional environment
    variables `env_vars` fails (rc != 0) and return a (return code, stdout,
    stderr) tuple.

    See assert_python_ok() for more options.
    """
    return _assert_python(False, *args, **env_vars)


def spawn_python(*args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw):
    """Run a Python subprocess with the given arguments.

    kw is extra keyword args to pass to subprocess.Popen. Returns a Popen
    object.
    """
    cmd_line = [sys.executable]
    if not interpreter_requires_environment():
        cmd_line.append('-E')
    cmd_line.extend(args)
    # Under Fedora (?), GNU readline can output junk on stderr when initialized,
    # depending on the TERM setting.  Setting TERM=vt100 is supposed to disable
    # that.  References:
    # - http://reinout.vanrees.org/weblog/2009/08/14/readline-invisible-character-hack.html
    # - http://stackoverflow.com/questions/15760712/python-readline-module-prints-escape-character-during-import
    # - http://lists.gnu.org/archive/html/bug-readline/2007-08/msg00004.html
    env = kw.setdefault('env', dict(os.environ))
    env['TERM'] = 'vt100'
    return subprocess.Popen(cmd_line, stdin=subprocess.PIPE,
                            stdout=stdout, stderr=stderr,
                            **kw)


def kill_python(p):
    """Run the given Popen process until completion and return stdout."""
    p.stdin.close()
    data = p.stdout.read()
    p.stdout.close()
    # try to cleanup the child so we don't appear to leak when running
    # with regrtest -R.
    p.wait()
    subprocess._cleanup()
    return data


def make_script(script_dir, script_basename, source, omit_suffix=False):
    script_filename = script_basename
    if not omit_suffix:
        script_filename += os.extsep + 'py'
    script_name = os.path.join(script_dir, script_filename)
    # The script should be encoded to UTF-8, the default string encoding
    with open(script_name, 'w', encoding='utf-8') as script_file:
        script_file.write(source)
    importlib.invalidate_caches()
    return script_name


def make_zip_script(zip_dir, zip_basename, script_name, name_in_zip=None):
    zip_filename = zip_basename+os.extsep+'zip'
    zip_name = os.path.join(zip_dir, zip_filename)
    with zipfile.ZipFile(zip_name, 'w') as zip_file:
        if name_in_zip is None:
            parts = script_name.split(os.sep)
            if len(parts) >= 2 and parts[-2] == '__pycache__':
                legacy_pyc = make_legacy_pyc(source_from_cache(script_name))
                name_in_zip = os.path.basename(legacy_pyc)
                script_name = legacy_pyc
            else:
                name_in_zip = os.path.basename(script_name)
        zip_file.write(script_name, name_in_zip)
    #if test.support.verbose:
    #    with zipfile.ZipFile(zip_name, 'r') as zip_file:
    #        print 'Contents of %r:' % zip_name
    #        zip_file.printdir()
    return zip_name, os.path.join(zip_name, name_in_zip)


def make_pkg(pkg_dir, init_source=''):
    os.mkdir(pkg_dir)
    make_script(pkg_dir, '__init__', init_source)


def make_zip_pkg(zip_dir, zip_basename, pkg_name, script_basename,
                 source, depth=1, compiled=False):
    unlink = []
    init_name = make_script(zip_dir, '__init__', '')
    unlink.append(init_name)
    init_basename = os.path.basename(init_name)
    script_name = make_script(zip_dir, script_basename, source)
    unlink.append(script_name)
    if compiled:
        init_name = py_compile.compile(init_name, doraise=True)
        script_name = py_compile.compile(script_name, doraise=True)
        unlink.extend((init_name, script_name))
    pkg_names = [os.sep.join([pkg_name]*i) for i in range(1, depth+1)]
    script_name_in_zip = os.path.join(pkg_names[-1], os.path.basename(script_name))
    zip_filename = zip_basename+os.extsep+'zip'
    zip_name = os.path.join(zip_dir, zip_filename)
    with zipfile.ZipFile(zip_name, 'w') as zip_file:
        for name in pkg_names:
            init_name_in_zip = os.path.join(name, init_basename)
            zip_file.write(init_name, init_name_in_zip)
        zip_file.write(script_name, script_name_in_zip)
    for name in unlink:
        os.unlink(name)
    #if test.support.verbose:
    #    with zipfile.ZipFile(zip_name, 'r') as zip_file:
    #        print 'Contents of %r:' % zip_name
    #        zip_file.printdir()
    return zip_name, os.path.join(zip_name, script_name_in_zip)


def run_test_script(script):
    # use -u to try to get the full output if the test hangs or crash
    if support.verbose:
        def title(text):
            return f"===== {text} ======"

        name = f"script {os.path.basename(script)}"
        print()
        print(title(name), flush=True)
        # In verbose mode, the child process inherit stdout and stdout,
        # to see output in realtime and reduce the risk of losing output.
        args = [sys.executable, "-E", "-X", "faulthandler", "-u", script, "-v"]
        proc = subprocess.run(args)
        print(title(f"{name} completed: exit code {proc.returncode}"),
              flush=True)
        if proc.returncode:
            raise AssertionError(f"{name} failed")
    else:
        assert_python_ok("-u", script, "-v")
