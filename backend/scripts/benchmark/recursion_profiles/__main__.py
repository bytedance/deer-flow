"""Run from backend: python -m scripts.benchmark.recursion_profiles --profile swebench-lite."""

import sys

from .profiles import main

if __name__ == "__main__":
    sys.exit(main())
