#!/usr/bin/env python3
"""
Bridge script: reuse the News Extractor CLI on URLs that already exist
inside the News Gatherer SQLite database so we can inspect full-text results.

Usage (from the news-extractor project root, after `pip install -e .`):

    python examples/scrape_news_gatherer_backlog.py \
        --db ../news-gatherer/output/news-gatherer.db \
        --limit 25 \
        --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if SRC_PATH.exists():
    sys.path.insert(0, str(SRC_PATH))

from news_extractor.backlog import load_records, print_pretty, reextract, summarize
from news_extractor.article_extractor import _safe_terminal_text


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run News Extractor on the existing News Gatherer URLs."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "news-gatherer" / "output" / "news-gatherer.db",
        help="Path to news-gatherer SQLite file (default: ../news-gatherer/output/news-gatherer.db).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="How many rows to pull from the articles table (default: 20).",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Start offset when scanning the articles table (default: 0).",
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=100,
        help="Minimum characters to accept an extraction (default: 100).",
    )
    parser.add_argument(
        "--format",
        choices=["json", "pretty"],
        default="pretty",
        help="json = newline-delimited JSON, pretty = human readable (default: pretty).",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.db.exists():
        print(f"Database not found: {_safe_terminal_text(args.db)}", file=sys.stderr)
        return 2

    records = load_records(args.db, args.limit, args.offset)
    if not records:
        print("No rows returned from the articles table.", file=sys.stderr)
        return 1

    results = reextract(records, min_text_length=args.min_text_length)

    if args.format == "json":
        for entry in results:
            print(json.dumps(entry, ensure_ascii=False))
    else:
        print_pretty(results)

    stats = summarize(results)
    summary_stream = sys.stderr if args.format == "json" else sys.stdout
    if stats["total"]:
        print(
            f"\nSummary: {stats['successes']}/{stats['total']} extractions succeeded "
            f"({stats['success_rate']:.1f}% with min_text_length={args.min_text_length}).",
            file=summary_stream,
        )
    else:
        print("\nSummary: no rows processed.", file=summary_stream)

    return 0 if stats["successes"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
