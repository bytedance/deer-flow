#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
shared_strings_builder.py — Generate a valid sharedStrings.xml from a list of strings.

Usage (strings as command-line arguments):
    python3 shared_strings_builder.py "Revenue" "Cost" "Gross Profit" > sharedStrings.xml

Usage (strings from a file, one per line):
    python3 shared_strings_builder.py --file strings.txt > sharedStrings.xml

Usage (print index table instead of XML, for reference):
    python3 shared_strings_builder.py --index "Revenue" "Cost" "Gross Profit"
    python3 shared_strings_builder.py --index --file strings.txt

Output format:
    Valid xl/sharedStrings.xml written to stdout.
    Redirect to the correct path:
        python3 shared_strings_builder.py "A" "B" > /tmp/xlsx_work/xl/sharedStrings.xml

Notes:
    - Strings are de-duplicated: identical strings appear only once in the table.
    - The 'count' attribute equals the number of unique strings (appropriate for new files
      where each string is used in exactly one cell). If a string appears in multiple cells,
      manually increment 'count' by the number of extra references.
    - Special characters (&, <, >) are automatically XML-escaped.
    - Leading/trailing spaces are preserved with xml:space="preserve".
"""

import sys
import html
import argparse


HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
SST_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def escape_text(s: str) -> tuple[str, bool]:
    """
    Return (escaped_text, needs_preserve).
    needs_preserve is True if the string has leading or trailing whitespace.
    """
    escaped = html.escape(s, quote=False)
    needs_preserve = s != s.strip()
    return escaped, needs_preserve


def build_xml(strings: list[str]) -> str:
    """Build sharedStrings.xml content from a list of unique strings."""
    n = len(strings)
    lines = [
        HEADER,
        f'<sst xmlns="{SST_NS}" count="{n}" uniqueCount="{n}">',
    ]
    for i, s in enumerate(strings):
        escaped, preserve = escape_text(s)
        if preserve:
            lines.append(f'  <si><t xml:space="preserve">{escaped}</t></si>'
                         f'  <!-- index {i} -->')
        else:
            lines.append(f'  <si><t>{escaped}</t></si>  <!-- index {i} -->')
    lines.append("</sst>")
    return "\n".join(lines) + "\n"


def build_index_table(strings: list[str]) -> str:
    """Return a human-readable index table (for agent reference, not written to file)."""
    lines = [
        f"{'Index':<6}  String",
        "-" * 50,
    ]
    for i, s in enumerate(strings):
        lines.append(f"{i:<6}  {s!r}")
    lines.append("")
    lines.append(
        f"Total: {len(strings)} unique strings. "
        "Use these indices in <c t=\"s\"><v>N</v></c> cells."
    )
    return "\n".join(lines) + "\n"


def deduplicate(strings: list[str]) -> list[str]:
    """Remove duplicates while preserving first-occurrence order."""
    seen: set[str] = set()
    result: list[str] = []
    for s in strings:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def load_from_file(path: str) -> list[str]:
    """Read one string per non-empty line from a file."""
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate xl/sharedStrings.xml from a list of strings.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "strings",
        nargs="*",
        metavar="STRING",
        help="String values to include in the shared string table.",
    )
    parser.add_argument(
        "--file",
        "-f",
        metavar="PATH",
        help="Read strings from a file (one string per line) instead of arguments.",
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Print a human-readable index table instead of XML output.",
    )
    args = parser.parse_args()

    if args.file:
        try:
            raw = load_from_file(args.file)
        except FileNotFoundError:
            print(f"ERROR: File not found: {args.file}", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(f"ERROR: Cannot read file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        raw = list(args.strings)

    if not raw:
        print(
            "ERROR: No strings provided.\n"
            "Usage: shared_strings_builder.py \"String1\" \"String2\" ...\n"
            "   or: shared_strings_builder.py --file strings.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    strings = deduplicate(raw)

    if len(strings) < len(raw):
        removed = len(raw) - len(strings)
        print(
            f"Note: {removed} duplicate(s) removed. "
            f"{len(strings)} unique strings in table.",
            file=sys.stderr,
        )

    if args.index:
        print(build_index_table(strings))
    else:
        print(build_xml(strings), end="")


if __name__ == "__main__":
    main()
