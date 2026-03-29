#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
libreoffice_recalc.py — Tier 2 dynamic formula recalculation via LibreOffice headless.

Opens the xlsx file with the LibreOffice Calc engine, executes all formulas, writes
the computed values into the <v> cache elements, and saves the result. This is the
closest server-side equivalent of "open in Excel and save."

After recalculation, run formula_check.py on the output file to detect runtime errors
(#DIV/0!, #N/A, etc.) that only surface after actual computation.

Usage:
    python3 libreoffice_recalc.py input.xlsx output.xlsx
    python3 libreoffice_recalc.py input.xlsx output.xlsx --timeout 90
    python3 libreoffice_recalc.py --check          # check LibreOffice availability only

Exit codes:
    0 — recalculation succeeded, output file written
    2 — LibreOffice not found (Tier 2 unavailable — not a hard failure, note in report)
    1 — LibreOffice found but recalculation failed (timeout, crash, bad file)
"""

import subprocess
import sys
import shutil
import os
import tempfile
import argparse


# ── LibreOffice discovery ───────────────────────────────────────────────────

def find_soffice() -> str | None:
    """
    Locate the soffice (LibreOffice) binary.

    Search order:
      1. macOS application bundle (default install location)
      2. PATH lookup for 'soffice'
      3. PATH lookup for 'libreoffice' (common on Linux)
    """
    candidates = [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
        "soffice",     # Linux / macOS if on PATH
        "libreoffice", # alternative Linux name
    ]
    for c in candidates:
        # shutil.which handles PATH lookup; also check absolute paths directly
        found = shutil.which(c)
        if found:
            return found
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def get_libreoffice_version(soffice: str) -> str:
    """Return LibreOffice version string, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            [soffice, "--version"],
            capture_output=True,
            timeout=10,
        )
        return result.stdout.decode(errors="replace").strip()
    except Exception:
        return "unknown"


# ── Recalculation ───────────────────────────────────────────────────────────

def recalculate(
    input_path: str,
    output_path: str,
    timeout: int = 60,
) -> tuple[bool, str]:
    """
    Run LibreOffice headless recalculation on input_path, write result to output_path.

    Returns:
        (success: bool, message: str)

    The message explains what happened (success or failure reason).
    """
    soffice = find_soffice()
    if not soffice:
        return False, (
            "LibreOffice not found. Tier 2 validation is unavailable in this environment. "
            "Install LibreOffice to enable dynamic formula recalculation.\n"
            "  macOS:  brew install --cask libreoffice\n"
            "  Linux:  sudo apt-get install -y libreoffice"
        )

    version = get_libreoffice_version(soffice)

    # Work on a copy in a temp directory to avoid side effects on the source file.
    # LibreOffice writes the output using the same filename stem in --outdir.
    with tempfile.TemporaryDirectory(prefix="xlsx_recalc_") as tmpdir:
        tmp_input = os.path.join(tmpdir, os.path.basename(input_path))
        shutil.copy(input_path, tmp_input)

        cmd = [
            soffice,
            "--headless",
            "--norestore",           # do not attempt to restore crashed sessions
            "--infilter=Calc MS Excel 2007 XML",
            "--convert-to", "xlsx",
            "--outdir", tmpdir,
            tmp_input,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, (
                f"LibreOffice timed out after {timeout}s. "
                "The file may be too large or contain constructs that cause LibreOffice to hang. "
                "Try increasing --timeout or simplify the file."
            )
        except FileNotFoundError:
            return False, f"LibreOffice binary not executable: {soffice}"

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace").strip()
            stdout = result.stdout.decode(errors="replace").strip()
            return False, (
                f"LibreOffice exited with code {result.returncode}.\n"
                f"stderr: {stderr}\n"
                f"stdout: {stdout}"
            )

        # LibreOffice writes: <tmpdir>/<stem>.xlsx
        stem = os.path.splitext(os.path.basename(tmp_input))[0]
        tmp_output = os.path.join(tmpdir, stem + ".xlsx")

        if not os.path.isfile(tmp_output):
            # Try to find any .xlsx file in tmpdir (LibreOffice may behave differently)
            xlsx_files = [f for f in os.listdir(tmpdir) if f.endswith(".xlsx") and f != os.path.basename(tmp_input)]
            if xlsx_files:
                tmp_output = os.path.join(tmpdir, xlsx_files[0])
            else:
                stdout = result.stdout.decode(errors="replace").strip()
                return False, (
                    f"LibreOffice succeeded (exit 0) but output file not found in {tmpdir}.\n"
                    f"stdout: {stdout}\n"
                    f"Files in tmpdir: {os.listdir(tmpdir)}"
                )

        # Copy recalculated file to final destination
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        shutil.copy(tmp_output, output_path)

    return True, f"Recalculation complete. LibreOffice {version}. Output: {output_path}"


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LibreOffice headless formula recalculation for xlsx files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic recalculation
  python3 libreoffice_recalc.py report.xlsx report_recalc.xlsx

  # With extended timeout for large files
  python3 libreoffice_recalc.py big_model.xlsx big_model_recalc.xlsx --timeout 120

  # Check if LibreOffice is available (useful in CI)
  python3 libreoffice_recalc.py --check

  # Full validation pipeline
  python3 libreoffice_recalc.py input.xlsx /tmp/recalc.xlsx && \\
    python3 formula_check.py /tmp/recalc.xlsx
""",
    )
    parser.add_argument("input", nargs="?", help="Input xlsx file path")
    parser.add_argument("output", nargs="?", help="Output xlsx file path (recalculated)")
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        metavar="SECONDS",
        help="Maximum time to wait for LibreOffice (default: 60)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only check if LibreOffice is available, then exit",
    )

    args = parser.parse_args()

    # ── --check mode ─────────────────────────────────────────────────────────
    if args.check:
        soffice = find_soffice()
        if soffice:
            version = get_libreoffice_version(soffice)
            print(f"LibreOffice available: {soffice}")
            print(f"Version: {version}")
            sys.exit(0)
        else:
            print("LibreOffice NOT available.")
            print("Tier 2 dynamic validation requires LibreOffice.")
            print("  macOS:  brew install --cask libreoffice")
            print("  Linux:  sudo apt-get install -y libreoffice")
            sys.exit(2)

    # ── Recalculation mode ────────────────────────────────────────────────────
    if not args.input or not args.output:
        parser.print_help()
        sys.exit(1)

    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        sys.exit(1)

    print(f"Input  : {args.input}")
    print(f"Output : {args.output}")
    print(f"Timeout: {args.timeout}s")
    print()

    success, message = recalculate(args.input, args.output, timeout=args.timeout)

    if success:
        print(f"OK: {message}")
        print()
        print("Next step: run formula_check.py on the recalculated file to detect runtime errors:")
        print(f"  python3 formula_check.py {args.output}")
        sys.exit(0)
    else:
        # Distinguish "not installed" (exit 2) from "failed" (exit 1)
        if "not found" in message.lower() or "not available" in message.lower():
            print(f"SKIP (Tier 2 unavailable): {message}")
            sys.exit(2)
        else:
            print(f"ERROR: {message}")
            sys.exit(1)


if __name__ == "__main__":
    main()
