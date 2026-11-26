"""Fixed, model-independent cleanup for Linux AIO commands carrying a run marker."""

import re
import shlex

# pidfds keep a recycled PID from receiving a late cancellation signal. Only
# exact inherited execution markers are selected; no command-name matching.
# The shell running the command exported the marker after it started, so its
# own environ lacks it, and terminating only the marked children lets it run
# the rest of the command. Interrupting their process groups first, as Ctrl-C
# would, makes the shell drop the remaining statements: an interactive shell
# keeps its state, and a one-off `bash -c` exits. A process group never spans
# sessions, so this reaches only the shell session that ran the command.
_SCRIPT = r"""import json, os, select, signal, sys, time
probe = os.pidfd_open(os.getpid())
os.close(probe)
needle = b'DEERFLOW_COMMAND_OWNER=' + sys.argv[1].encode('ascii')
def group(name):
    with open('/proc/' + name + '/stat', 'rb') as stream:
        return int(stream.read().rsplit(b')', 1)[1].split()[2])
def interrupt():
    groups = set()
    for name in os.listdir('/proc'):
        if not name.isdecimal() or int(name) == os.getpid():
            continue
        try:
            with open('/proc/' + name + '/environ', 'rb') as stream:
                if needle not in stream.read().split(b'\0'):
                    continue
            groups.add(group(name))
        except OSError:
            continue
    for name in os.listdir('/proc') if groups else ():
        if not name.isdecimal() or int(name) == os.getpid():
            continue
        try:
            fd = os.pidfd_open(int(name))
        except OSError:
            continue
        try:
            if group(name) in groups:
                signal.pidfd_send_signal(fd, signal.SIGINT)
        except OSError:
            pass
        finally:
            os.close(fd)
    return bool(groups)
deadline = time.monotonic() + 4
stopped = set()
empty = 0
interrupted = False
while time.monotonic() < deadline:
    if not interrupted and interrupt():
        interrupted = True
        time.sleep(0.1)
    owned = []
    blocked = False
    for name in os.listdir('/proc'):
        if not name.isdecimal() or int(name) == os.getpid():
            continue
        fd = None
        matched = False
        try:
            fd = os.pidfd_open(int(name))
            with open('/proc/' + name + '/environ', 'rb') as stream:
                environment = stream.read()
            if needle not in environment.split(b'\0'):
                os.close(fd)
                continue
            matched = True
            signal.pidfd_send_signal(fd, signal.SIGTERM)
            owned.append((int(name), fd))
        except OSError as error:
            if matched and not isinstance(error, ProcessLookupError):
                blocked = True
            if fd is not None:
                os.close(fd)
    if not owned and not blocked:
        empty += 1
        if empty >= 2:
            break
        time.sleep(0.05)
        continue
    empty = 0
    time.sleep(0.15)
    for pid, fd in owned:
        try:
            if not select.select([fd], [], [], 0)[0]:
                signal.pidfd_send_signal(fd, signal.SIGKILL)
            stopped.add(pid)
        except ProcessLookupError:
            pass
        finally:
            os.close(fd)
    time.sleep(0.05)
print(json.dumps({'stopped': len(stopped), 'remaining': 0 if empty >= 2 else 1}))
"""


def cleanup_command(token: str) -> str:
    if re.fullmatch(r"[0-9a-f]{32}", token) is None:
        raise ValueError("Invalid execution marker")
    return "python3 -c " + shlex.quote("exec(" + repr(_SCRIPT) + ")") + " " + shlex.quote(token)
