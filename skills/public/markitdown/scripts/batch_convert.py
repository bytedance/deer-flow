#!/usr/bin/env python3
"""Convert multiple files to Markdown via markitdown + MinerU OCR fallback."""
import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from markitdown import MarkItDown

import mineru_client


# Module-level constant: short markitdown output => scanned PDF, route to MinerU.
OCR_FALLBACK_THRESHOLD = 50

# File extensions that always go to MinerU (pure image formats).
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def convert_file(file_path: Path, output_dir: Path, verbose: bool = False) -> tuple[bool, str, str]:
    """Convert one file. Returns (success, path_str, message).

    Routing:
      - image suffix (.jpg/.jpeg/.png) -> mineru_client.ocr_to_markdown
      - else: markitdown.convert(); if text < OCR_FALLBACK_THRESHOLD, fall back to mineru
    """
    try:
        suffix = file_path.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            if verbose:
                print(f"OCR (image): {file_path}")
            text = mineru_client.ocr_to_markdown(str(file_path))
        else:
            md = MarkItDown()
            result = md.convert(str(file_path))
            text = result.text_content or ""
            if len(text.strip()) < OCR_FALLBACK_THRESHOLD:
                if verbose:
                    print(
                        f"markitdown returned <{OCR_FALLBACK_THRESHOLD} chars, "
                        f"falling back to MinerU: {file_path}"
                    )
                text = mineru_client.ocr_to_markdown(str(file_path))

        output_file = output_dir / f"{file_path.stem}.md"
        content = f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n---\n\n{text}"
        output_file.write_text(content, encoding="utf-8")
        # Print the body so it surfaces in the chat UI as a tool result block
        # (same pattern as data-analysis `print(result)` in scripts/analyze.py).
        print(content)
        return True, str(file_path), f"✓ Converted to {output_file.name}"

    except FileNotFoundError:
        print(f"⚠ Skipping: {file_path} (not found)")
        return False, str(file_path), "Skipping: not found"
    except mineru_client.MinerUError as e:
        placeholder = output_dir / f"{file_path.stem}.md"
        placeholder.write_text(
            f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n"
            f"---\n\n[ERROR] MinerU failed (status={e.status}): {e}\n",
            encoding="utf-8",
        )
        return False, str(file_path), f"Error: MinerU {e.status or e}"
    except Exception as e:
        placeholder = output_dir / f"{file_path.stem}.md"
        placeholder.write_text(
            f"# {file_path.stem}\n\n**Source**: {file_path.name}\n\n"
            f"---\n\n[ERROR] {type(e).__name__}: {e}\n",
            encoding="utf-8",
        )
        return False, str(file_path), f"Error: {e}"


def batch_convert(
    files: list[Path],
    output_dir: Path,
    workers: int = 4,
    verbose: bool = False,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not files:
        print("No files to convert.")
        return {"total": 0, "success": 0, "failed": 0, "details": []}

    print(f"Converting {len(files)} file(s) with {workers} worker(s)")
    results = {"total": len(files), "success": 0, "failed": 0, "details": []}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(convert_file, fp, output_dir, verbose): fp for fp in files
        }
        for future in as_completed(futures):
            ok, path, msg = future.result()
            if ok:
                results["success"] += 1
            else:
                results["failed"] += 1
            results["details"].append({"file": path, "success": ok, "message": msg})
            print(msg)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert files to Markdown via markitdown + MinerU OCR fallback"
    )
    parser.add_argument(
        "--files", nargs="+", required=True,
        help="Explicit file paths to convert (e.g., /mnt/user-data/uploads/a.pdf)",
    )
    parser.add_argument(
        "--output-dir", required=True, type=Path,
        help="Output directory (e.g., /mnt/user-data/outputs/)",
    )
    parser.add_argument("--workers", "-w", type=int, default=4)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    files = [Path(p) for p in args.files]
    results = batch_convert(files, args.output_dir, workers=args.workers, verbose=args.verbose)

    print("\n" + "=" * 50)
    print("CONVERSION SUMMARY")
    print("=" * 50)
    print(f"Total files:     {results['total']}")
    print(f"Successful:      {results['success']}")
    print(f"Failed:          {results['failed']}")
    if results["failed"] > 0:
        print("\nFailed conversions:")
        for d in results["details"]:
            if not d["success"]:
                print(f"  - {d['file']}: {d['message']}")
    return 0 if results["success"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
