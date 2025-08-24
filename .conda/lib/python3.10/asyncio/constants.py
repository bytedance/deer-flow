import enum

# After the connection is lost, log warnings after this many write()s.
LOG_THRESHOLD_FOR_CONNLOST_WRITES = 5

# Seconds to wait before retrying accept().
ACCEPT_RETRY_DELAY = 1

# Number of stack entries to capture in debug mode.
# The larger the number, the slower the operation in debug mode
# (see extract_stack() in format_helpers.py).
DEBUG_STACK_DEPTH = 10

# Number of seconds to wait for SSL handshake to complete
# The default timeout matches that of Nginx.
SSL_HANDSHAKE_TIMEOUT = 60.0

# Used in sendfile fallback code.  We use fallback for platforms
# that don't support sendfile, or for TLS connections.
SENDFILE_FALLBACK_READBUFFER_SIZE = 1024 * 256

# The enum should be here to break circular dependencies between
# base_events and sslproto
class _SendfileMode(enum.Enum):
    UNSUPPORTED = enum.auto()
    TRY_NATIVE = enum.auto()
    FALLBACK = enum.auto()
