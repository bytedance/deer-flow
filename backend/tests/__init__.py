"""Backend test package organized by stable source ownership domains."""

import sys
from pathlib import Path

# Test modules historically import shared helpers as ``support.*``.  Keep that
# package visible while tests are imported through the new ``tests.<domain>``
# package hierarchy.
_TESTS_ROOT = str(Path(__file__).resolve().parent)
if _TESTS_ROOT not in sys.path:
    sys.path.insert(0, _TESTS_ROOT)
