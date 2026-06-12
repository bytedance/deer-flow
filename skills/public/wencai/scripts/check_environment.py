#!/usr/bin/env python3
"""
Environment check script for pywencai

Verifies that all required dependencies are installed:
- Node.js v16+
- pywencai package
"""

import sys
import subprocess
import shutil

def check_nodejs():
    """Check if Node.js is installed and version >= 16"""
    if not shutil.which('node'):
        return False, "Node.js not found"

    try:
        result = subprocess.run(['node', '--version'], capture_output=True, text=True)
        version_str = result.stdout.strip()
        # Extract major version (e.g., "v18.12.0" -> 18)
        major_version = int(version_str.lstrip('v').split('.')[0])

        if major_version < 16:
            return False, f"Node.js version {version_str} is too old (requires v16+)"

        return True, f"Node.js {version_str} ✓"
    except Exception as e:
        return False, f"Error checking Node.js version: {e}"

def check_pywencai():
    """Check if pywencai is installed"""
    try:
        import pywencai
        return True, f"pywencai installed ✓"
    except ImportError:
        return False, "pywencai not installed"

def main():
    print("Checking pywencai environment...\n")

    all_ok = True

    # Check Node.js
    ok, msg = check_nodejs()
    print(f"Node.js: {msg}")
    if not ok:
        all_ok = False
        print("  → Install from: https://nodejs.org/")

    # Check pywencai
    ok, msg = check_pywencai()
    print(f"pywencai: {msg}")
    if not ok:
        all_ok = False
        print("  → Install with: pip install pywencai")

    print()
    if all_ok:
        print("✓ All dependencies are installed!")
        return 0
    else:
        print("✗ Some dependencies are missing. Please install them.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
