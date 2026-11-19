"""Fixed, model-independent cleanup for Linux AIO commands carrying a run marker."""

import re
import shlex

# pidfds keep a recycled PID from receiving a late cancellation signal. Only
# exact inherited execution markers are selected; no command-name matching.
_SCRIPT = r"""import json, os, select, signal, sys, time
probe = os.pidfd_open(os.getpid())
os.close(probe)
needle = b'DEERFLOW_COMMAND_OWNER=' + sys.argv[1].encode('ascii')
deadline = time.monotonic() + 4
stopped = set()
empty = 0
while time.monotonic() < deadline:
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
