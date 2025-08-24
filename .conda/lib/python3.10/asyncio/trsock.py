import socket
import warnings


class TransportSocket:

    """A socket-like wrapper for exposing real transport sockets.

    These objects can be safely returned by APIs like
    `transport.get_extra_info('socket')`.  All potentially disruptive
    operations (like "socket.close()") are banned.
    """

    __slots__ = ('_sock',)

    def __init__(self, sock: socket.socket):
        self._sock = sock

    def _na(self, what):
        warnings.warn(
            f"Using {what} on sockets returned from get_extra_info('socket') "
            f"will be prohibited in asyncio 3.9. Please report your use case "
            f"to bugs.python.org.",
            DeprecationWarning, source=self)

    @property
    def family(self):
        return self._sock.family

    @property
    def type(self):
        return self._sock.type

    @property
    def proto(self):
        return self._sock.proto

    def __repr__(self):
        s = (
            f"<asyncio.TransportSocket fd={self.fileno()}, "
            f"family={self.family!s}, type={self.type!s}, "
            f"proto={self.proto}"
        )

        if self.fileno() != -1:
            try:
                laddr = self.getsockname()
                if laddr:
                    s = f"{s}, laddr={laddr}"
            except socket.error:
                pass
            try:
                raddr = self.getpeername()
                if raddr:
                    s = f"{s}, raddr={raddr}"
            except socket.error:
                pass

        return f"{s}>"

    def __getstate__(self):
        raise TypeError("Cannot serialize asyncio.TransportSocket object")

    def fileno(self):
        return self._sock.fileno()

    def dup(self):
        return self._sock.dup()

    def get_inheritable(self):
        return self._sock.get_inheritable()

    def shutdown(self, how):
        # asyncio doesn't currently provide a high-level transport API
        # to shutdown the connection.
        self._sock.shutdown(how)

    def getsockopt(self, *args, **kwargs):
        return self._sock.getsockopt(*args, **kwargs)

    def setsockopt(self, *args, **kwargs):
        self._sock.setsockopt(*args, **kwargs)

    def getpeername(self):
        return self._sock.getpeername()

    def getsockname(self):
        return self._sock.getsockname()

    def getsockbyname(self):
        return self._sock.getsockbyname()

    def accept(self):
        self._na('accept() method')
        return self._sock.accept()

    def connect(self, *args, **kwargs):
        self._na('connect() method')
        return self._sock.connect(*args, **kwargs)

    def connect_ex(self, *args, **kwargs):
        self._na('connect_ex() method')
        return self._sock.connect_ex(*args, **kwargs)

    def bind(self, *args, **kwargs):
        self._na('bind() method')
        return self._sock.bind(*args, **kwargs)

    def ioctl(self, *args, **kwargs):
        self._na('ioctl() method')
        return self._sock.ioctl(*args, **kwargs)

    def listen(self, *args, **kwargs):
        self._na('listen() method')
        return self._sock.listen(*args, **kwargs)

    def makefile(self):
        self._na('makefile() method')
        return self._sock.makefile()

    def sendfile(self, *args, **kwargs):
        self._na('sendfile() method')
        return self._sock.sendfile(*args, **kwargs)

    def close(self):
        self._na('close() method')
        return self._sock.close()

    def detach(self):
        self._na('detach() method')
        return self._sock.detach()

    def sendmsg_afalg(self, *args, **kwargs):
        self._na('sendmsg_afalg() method')
        return self._sock.sendmsg_afalg(*args, **kwargs)

    def sendmsg(self, *args, **kwargs):
        self._na('sendmsg() method')
        return self._sock.sendmsg(*args, **kwargs)

    def sendto(self, *args, **kwargs):
        self._na('sendto() method')
        return self._sock.sendto(*args, **kwargs)

    def send(self, *args, **kwargs):
        self._na('send() method')
        return self._sock.send(*args, **kwargs)

    def sendall(self, *args, **kwargs):
        self._na('sendall() method')
        return self._sock.sendall(*args, **kwargs)

    def set_inheritable(self, *args, **kwargs):
        self._na('set_inheritable() method')
        return self._sock.set_inheritable(*args, **kwargs)

    def share(self, process_id):
        self._na('share() method')
        return self._sock.share(process_id)

    def recv_into(self, *args, **kwargs):
        self._na('recv_into() method')
        return self._sock.recv_into(*args, **kwargs)

    def recvfrom_into(self, *args, **kwargs):
        self._na('recvfrom_into() method')
        return self._sock.recvfrom_into(*args, **kwargs)

    def recvmsg_into(self, *args, **kwargs):
        self._na('recvmsg_into() method')
        return self._sock.recvmsg_into(*args, **kwargs)

    def recvmsg(self, *args, **kwargs):
        self._na('recvmsg() method')
        return self._sock.recvmsg(*args, **kwargs)

    def recvfrom(self, *args, **kwargs):
        self._na('recvfrom() method')
        return self._sock.recvfrom(*args, **kwargs)

    def recv(self, *args, **kwargs):
        self._na('recv() method')
        return self._sock.recv(*args, **kwargs)

    def settimeout(self, value):
        if value == 0:
            return
        raise ValueError(
            'settimeout(): only 0 timeout is allowed on transport sockets')

    def gettimeout(self):
        return 0

    def setblocking(self, flag):
        if not flag:
            return
        raise ValueError(
            'setblocking(): transport sockets cannot be blocking')

    def __enter__(self):
        self._na('context manager protocol')
        return self._sock.__enter__()

    def __exit__(self, *err):
        self._na('context manager protocol')
        return self._sock.__exit__(*err)
