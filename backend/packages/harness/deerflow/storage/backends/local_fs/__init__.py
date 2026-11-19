"""local_fs backend -- the default blob store (content-addressed files).

Holds the store class (:mod:`local_fs_store`): content-addressed files under
``<root>/<kind>/<sha256[:2]>/<sha256>`` plus a JSON sidecar carrying what the
bytes cannot say, published atomically and verified on read.
"""

from .local_fs_store import LocalFsBlobStore

#: The :class:`~deerflow.storage.contract.BlobStore` subclass this
#: backend exposes. Discovered by the factory's ``_scan_backends`` drop-in
#: mechanism under the folder name ``local_fs``.
STORE_CLASS = LocalFsBlobStore
