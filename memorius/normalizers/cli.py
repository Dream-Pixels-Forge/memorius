#!/usr/bin/env python3
"""
Normalizer CLI — entry point for `memorius-normalize`.

Usage:
  memorius-normalize detect file.json
  memorius-normalize convert file.json
  memorius-normalize convert file.json --format discord
  memorius-normalize batch ./chat-exports/
  memorius-normalize batch ./chat-exports/ --output ./normalized/
  memorius-normalize pipe < input.json         # read from stdin, write to stdout
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from . import (
    NORMALIZERS,
    detect_format,
    normalize,
    normalize_file,
)

logger = logging.getLogger("memorius.normalizers.cli")


def _init_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def cmd_detect(parsed: argparse.Namespace):
    """Detect the format of one or more files."""
    _init_logging(parsed.verbose)

    for filepath in parsed.files:
        path = Path(filepath)
        if not path.exists():
            print(f"{filepath}: (not found)")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        fmt = detect_format(content, path.name)
        if fmt:
            print(f"{filepath}: {fmt}")
        else:
            print(f"{filepath}: unknown format")


def cmd_convert(parsed: argparse.Namespace):
    """Convert a single file to Memorius transcript format."""
    _init_logging(parsed.verbose)

    path = Path(parsed.file)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8", errors="replace")
    result = normalize(content, path.name, format=parsed.format)

    if parsed.output:
        output_path = Path(parsed.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result)
        print(f"Written: {output_path}")
    else:
        print(result)


def cmd_batch(parsed: argparse.Namespace):
    """Batch convert a directory of chat exports."""
    _init_logging(parsed.verbose)

    input_dir = Path(parsed.directory)
    if not input_dir.is_dir():
        print(f"Directory not found: {input_dir}", file=sys.stderr)
        return 1

    output_dir = Path(parsed.output) if parsed.output else input_dir / "normalized"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Common chat export extensions
    exts = {".json", ".jsonl", ".txt", ".csv", ".md", ".html"}
    files = [f for f in sorted(input_dir.iterdir()) if f.suffix in exts and f.is_file()]
    known_extras = {"discord", "telegram", "whatsapp", "result", "chat", "export", "conversation"}
    files = [f for f in files if (
        parsed.format
        or any(kw in f.stem.lower() for kw in known_extras)
    )]

    if not files:
        print("No detectable export files found.")
        print(f"Looked in: {input_dir}")
        print(f"Extensions: {', '.join(exts)}")
        return 1

    results = {"converted": 0, "errors": 0, "skipped": 0}
    for filepath in files:
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            result = normalize(content, filepath.name, format=parsed.format)

            if result.startswith("[error"):
                logger.warning(f"Skipped {filepath.name}: {result[:60]}")
                results["skipped"] += 1
                continue

            ext = ".txt"  # all transcripts become .txt
            out_path = output_dir / f"{filepath.stem}-transcript{ext}"
            out_path.write_text(result)
            results["converted"] += 1
            logger.info(f"Converted: {filepath.name} → {out_path.name}")
        except Exception as e:
            logger.error(f"Error converting {filepath.name}: {e}")
            results["errors"] += 1

    print(f"\nDone: {results['converted']} converted, {results['errors']} errors, {results['skipped']} skipped")
    print(f"Output: {output_dir}")


def cmd_pipe(parsed: argparse.Namespace):
    """Read from stdin, write normalized transcript to stdout."""
    _init_logging(parsed.verbose)

    content = sys.stdin.read()
    result = normalize(content, parsed.name, format=parsed.format)
    print(result)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        "memorius-normalize",
        description="Conversation format normalizers for Memorius (Discord, Telegram, WhatsApp, etc.)",
    )
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    subparsers = parser.add_subparsers(dest="command")

    detect_p = subparsers.add_parser("detect", help="Detect format of chat export files")
    detect_p.add_argument("files", nargs="+", help="Files to detect")
    detect_p.add_argument("--verbose", "-v", action="store_true")

    convert_p = subparsers.add_parser("convert", help="Convert a single file to transcript format")
    convert_p.add_argument("file", help="File to convert")
    convert_p.add_argument("--format", "-f", default=None,
                           choices=list(NORMALIZERS.keys()) + [None],
                           help="Force format (auto-detect if omitted)")
    convert_p.add_argument("--output", "-o", default=None, help="Output path (default: stdout)")
    convert_p.add_argument("--verbose", "-v", action="store_true")

    batch_p = subparsers.add_parser("batch", help="Batch convert a directory of chat exports")
    batch_p.add_argument("directory", help="Directory of chat exports")
    batch_p.add_argument("--output", "-o", default=None,
                         help="Output directory (default: <dir>/normalized/)")
    batch_p.add_argument("--format", "-f", default=None,
                         choices=list(NORMALIZERS.keys()) + [None],
                         help="Force format for all files")
    batch_p.add_argument("--verbose", "-v", action="store_true")

    pipe_p = subparsers.add_parser("pipe", help="Read from stdin, write normalized transcript to stdout")
    pipe_p.add_argument("--format", "-f", default=None,
                        choices=list(NORMALIZERS.keys()) + [None],
                        help="Force format (auto-detect if omitted)")
    pipe_p.add_argument("--name", "-n", default="stdin",
                        help="Source name (for transcript header)")
    pipe_p.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.version:
        from .. import __version__
        print(f"memorius-normalize v{__version__}")
        return 0

    if args.command == "detect":
        return cmd_detect(args)
    elif args.command == "convert":
        return cmd_convert(args)
    elif args.command == "batch":
        return cmd_batch(args)
    elif args.command == "pipe":
        return cmd_pipe(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    main()
