import contextlib
import errno
import socket
import unittest
import sys

from .. import support


HOST = "localhost"
HOSTv4 = "127.0.0.1"
HOSTv6 = "::1"


def find_unused_port(family=socket.AF_INET, socktype=socket.SOCK_STREAM):
    """Returns an unused port that should be suitable for binding.  This is
    achieved by creating a temporary socket with the same family and type as
    the 'sock' parameter (default is AF_INET, SOCK_STREAM), and binding it to
    the specified host address (defaults to 0.0.0.0) with the port set to 0,
    eliciting an unused ephemeral port from the OS.  The temporary socket is
    then closed and deleted, and the ephemeral port is returned.

    Either this method or bind_port() should be used for any tests where a
    server socket needs to be bound to a particular port for the duration of
    the test.  Which one to use depends on whether the calling code is creating
    a python socket, or if an unused port needs to be provided in a constructor
    or passed to an external program (i.e. the -accept argument to openssl's
    s_server mode).  Always prefer bind_port() over find_unused_port() where
    possible.  Hard coded ports should *NEVER* be used.  As soon as a server
    socket is bound to a hard coded port, the ability to run multiple instances
    of the test simultaneously on the same host is compromised, which makes the
    test a ticking time bomb in a buildbot environment. On Unix buildbots, this
    may simply manifest as a failed test, which can be recovered from without
    intervention in most cases, but on Windows, the entire python process can
    completely and utterly wedge, requiring someone to log in to the buildbot
    and manually kill the affected process.

    (This is easy to reproduce on Windows, unfortunately, and can be traced to
    the SO_REUSEADDR socket option having different semantics on Windows versus
    Unix/Linux.  On Unix, you can't have two AF_INET SOCK_STREAM sockets bind,
    listen and then accept connections on identical host/ports.  An EADDRINUSE
    OSError will be raised at some point (depending on the platform and
    the order bind and listen were called on each socket).

    However, on Windows, if SO_REUSEADDR is set on the sockets, no EADDRINUSE
    will ever be raised when attempting to bind two identical host/ports. When
    accept() is called on each socket, the second caller's process will steal
    the port from the first caller, leaving them both in an awkwardly wedged
    state where they'll no longer respond to any signals or graceful kills, and
    must be forcibly killed via OpenProcess()/TerminateProcess().

    The solution on Windows is to use the SO_EXCLUSIVEADDRUSE socket option
    instead of SO_REUSEADDR, which effectively affords the same semantics as
    SO_REUSEADDR on Unix.  Given the propensity of Unix developers in the Open
    Source world compared to Windows ones, this is a common mistake.  A quick
    look over OpenSSL's 0.9.8g source shows that they use SO_REUSEADDR when
    openssl.exe is called with the 's_server' option, for example. See
    http://bugs.python.org/issue2550 for more info.  The following site also
    has a very thorough description about the implications of both REUSEADDR
    and EXCLUSIVEADDRUSE on Windows:
    https://learn.microsoft.com/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse

    XXX: although this approach is a vast improvement on previous attempts to
    elicit unused ports, it rests heavily on the assumption that the ephemeral
    port returned to us by the OS won't immediately be dished back out to some
    other process when we close and delete our temporary socket but before our
    calling code has a chance to bind the returned port.  We can deal with this
    issue if/when we come across it.
    """

    with socket.socket(family, socktype) as tempsock:
        port = bind_port(tempsock)
    del tempsock
    return port

def bind_port(sock, host=HOST):
    """Bind the socket to a free port and return the port number.  Relies on
    ephemeral ports in order to ensure we are using an unbound port.  This is
    important as many tests may be running simultaneously, especially in a
    buildbot environment.  This method raises an exception if the sock.family
    is AF_INET and sock.type is SOCK_STREAM, *and* the socket has SO_REUSEADDR
    or SO_REUSEPORT set on it.  Tests should *never* set these socket options
    for TCP/IP sockets.  The only case for setting these options is testing
    multicasting via multiple UDP sockets.

    Additionally, if the SO_EXCLUSIVEADDRUSE socket option is available (i.e.
    on Windows), it will be set on the socket.  This will prevent anyone else
    from bind()'ing to our host/port for the duration of the test.
    """

    if sock.family == socket.AF_INET and sock.type == socket.SOCK_STREAM:
        if hasattr(socket, 'SO_REUSEADDR'):
            if sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 1:
                raise support.TestFailed("tests should never set the "
                                         "SO_REUSEADDR socket option on "
                                         "TCP/IP sockets!")
        if hasattr(socket, 'SO_REUSEPORT'):
            try:
                if sock.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 1:
                    raise support.TestFailed("tests should never set the "
                                             "SO_REUSEPORT socket option on "
                                             "TCP/IP sockets!")
            except OSError:
                # Python's socket module was compiled using modern headers
                # thus defining SO_REUSEPORT but this process is running
                # under an older kernel that does not support SO_REUSEPORT.
                pass
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)

    sock.bind((host, 0))
    port = sock.getsockname()[1]
    return port

def bind_unix_socket(sock, addr):
    """Bind a unix socket, raising SkipTest if PermissionError is raised."""
    assert sock.family == socket.AF_UNIX
    try:
        sock.bind(addr)
    except PermissionError:
        sock.close()
        raise unittest.SkipTest('cannot bind AF_UNIX sockets')

def _is_ipv6_enabled():
    """Check whether IPv6 is enabled on this host."""
    if socket.has_ipv6:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            sock.bind((HOSTv6, 0))
            return True
        except OSError:
            pass
        finally:
            if sock:
                sock.close()
    return False

IPV6_ENABLED = _is_ipv6_enabled()


_bind_nix_socket_error = None
def skip_unless_bind_unix_socket(test):
    """Decorator for tests requiring a functional bind() for unix sockets."""
    if not hasattr(socket, 'AF_UNIX'):
        return unittest.skip('No UNIX Sockets')(test)
    global _bind_nix_socket_error
    if _bind_nix_socket_error is None:
        from .os_helper import TESTFN, unlink
        path = TESTFN + "can_bind_unix_socket"
        with socket.socket(socket.AF_UNIX) as sock:
            try:
                sock.bind(path)
                _bind_nix_socket_error = False
            except OSError as e:
                _bind_nix_socket_error = e
            finally:
                unlink(path)
    if _bind_nix_socket_error:
        msg = 'Requires a functional unix bind(): %s' % _bind_nix_socket_error
        return unittest.skip(msg)(test)
    else:
        return test


def get_socket_conn_refused_errs():
    """
    Get the different socket error numbers ('errno') which can be received
    when a connection is refused.
    """
    errors = [errno.ECONNREFUSED]
    if hasattr(errno, 'ENETUNREACH'):
        # On Solaris, ENETUNREACH is returned sometimes instead of ECONNREFUSED
        errors.append(errno.ENETUNREACH)
    if hasattr(errno, 'EADDRNOTAVAIL'):
        # bpo-31910: socket.create_connection() fails randomly
        # with EADDRNOTAVAIL on Travis CI
        errors.append(errno.EADDRNOTAVAIL)
    if hasattr(errno, 'EHOSTUNREACH'):
        # bpo-37583: The destination host cannot be reached
        errors.append(errno.EHOSTUNREACH)
    if not IPV6_ENABLED:
        errors.append(errno.EAFNOSUPPORT)
    return errors


_NOT_SET = object()

@contextlib.contextmanager
def transient_internet(resource_name, *, timeout=_NOT_SET, errnos=()):
    """Return a context manager that raises ResourceDenied when various issues
    with the internet connection manifest themselves as exceptions."""
    import nntplib
    import urllib.error
    if timeout is _NOT_SET:
        timeout = support.INTERNET_TIMEOUT

    default_errnos = [
        ('ECONNREFUSED', 111),
        ('ECONNRESET', 104),
        ('EHOSTUNREACH', 113),
        ('ENETUNREACH', 101),
        ('ETIMEDOUT', 110),
        # socket.create_connection() fails randomly with
        # EADDRNOTAVAIL on Travis CI.
        ('EADDRNOTAVAIL', 99),
    ]
    default_gai_errnos = [
        ('EAI_AGAIN', -3),
        ('EAI_FAIL', -4),
        ('EAI_NONAME', -2),
        ('EAI_NODATA', -5),
        # Encountered when trying to resolve IPv6-only hostnames
        ('WSANO_DATA', 11004),
    ]

    denied = support.ResourceDenied("Resource %r is not available" % resource_name)
    captured_errnos = errnos
    gai_errnos = []
    if not captured_errnos:
        captured_errnos = [getattr(errno, name, num)
                           for (name, num) in default_errnos]
        gai_errnos = [getattr(socket, name, num)
                      for (name, num) in default_gai_errnos]

    def filter_error(err):
        n = getattr(err, 'errno', None)
        if (isinstance(err, TimeoutError) or
            (isinstance(err, socket.gaierror) and n in gai_errnos) or
            (isinstance(err, urllib.error.HTTPError) and
             500 <= err.code <= 599) or
            (isinstance(err, urllib.error.URLError) and
                 (("ConnectionRefusedError" in err.reason) or
                  ("TimeoutError" in err.reason) or
                  ("EOFError" in err.reason))) or
            n in captured_errnos):
            if not support.verbose:
                sys.stderr.write(denied.args[0] + "\n")
            raise denied from err

    old_timeout = socket.getdefaulttimeout()
    try:
        if timeout is not None:
            socket.setdefaulttimeout(timeout)
        yield
    except nntplib.NNTPTemporaryError as err:
        if support.verbose:
            sys.stderr.write(denied.args[0] + "\n")
        raise denied from err
    except OSError as err:
        # urllib can wrap original socket errors multiple times (!), we must
        # unwrap to get at the original error.
        while True:
            a = err.args
            if len(a) >= 1 and isinstance(a[0], OSError):
                err = a[0]
            # The error can also be wrapped as args[1]:
            #    except socket.error as msg:
            #        raise OSError('socket error', msg).with_traceback(sys.exc_info()[2])
            elif len(a) >= 2 and isinstance(a[1], OSError):
                err = a[1]
            else:
                break
        filter_error(err)
        raise
    # XXX should we catch generic exceptions and look for their
    # __cause__ or __context__?
    finally:
        socket.setdefaulttimeout(old_timeout)
