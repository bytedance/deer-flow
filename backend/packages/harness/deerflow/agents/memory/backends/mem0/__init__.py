"""mem0 memory backend -- HTTP client against the mem0 Platform API.

Drop-in contract: folder name == backend name == ``manager_class: mem0``.
"""

from .mem0_manager import Mem0Manager

#: Discovered by the factory's ``_scan_backends`` under the folder name ``mem0``.
MANAGER_CLASS = Mem0Manager
