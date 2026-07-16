from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, Iterable

from .article_extractor import ArticleExtractor

logger = logging.getLogger(__name__)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Turkish news articles with a dependency-free, SSRF-aware parser."
    )
    parser.add_argument("urls", nargs="+", help="One or more article URLs to extract.")
    parser.add_argument(
        "--timeout",
        type=float,
        default=10,
        help="Per-request timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=2_000_000,
        help="Maximum response body size in bytes (default: 2000000).",
    )
    parser.add_argument(
        "--max-redirects",
        type=int,
        default=5,
        help="Maximum validated redirect hops (default: 5).",
    )
    parser.add_argument(
        "--allow-private-network",
        action="store_true",
        help=(
            "Allow private, loopback, and link-local destinations. "
            "Use only for trusted internal URLs."
        ),
    )
    parser.add_argument(
        "--min-text-length",
        type=int,
        default=100,
        help="Minimum number of characters required to accept an extraction (default: 100)."
    )
    parser.add_argument(
        "--format",
        choices=["pretty", "json"],
        default="pretty",
        help="Output format for extracted articles (default: pretty)."
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging verbosity for diagnostics (default: INFO).",
    )
    return parser.parse_args(argv)


def _print_pretty(url: str, article: Dict[str, Any]) -> None:
    print("=" * 80)
    print(f"URL: {url}")
    print(f"Method: {article['method']}")
    print(f"Title: {article['title']}")
    authors = ", ".join(article["authors"]) if article.get("authors") else "N/A"
    print(f"Authors: {authors}")
    print(f"Date: {article.get('date')}")
    keywords = ", ".join(article.get("keywords", [])[:5]) or "N/A"
    print(f"Keywords: {keywords}")
    print(f"Text length: {article['text_length']} chars")
    print("-" * 80)
    preview = (article.get("text") or "")[:300]
    print(preview + ("..." if preview else ""))
    print()


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )
    try:
        extractor = ArticleExtractor(
            min_text_length=args.min_text_length,
            timeout=args.timeout,
            max_response_bytes=args.max_bytes,
            max_redirects=args.max_redirects,
            allow_private_networks=args.allow_private_network,
        )
    except ValueError as exc:
        logger.error("Invalid configuration: %s", exc)
        return 2

    successes = 0
    for url in args.urls:
        article = extractor.extract(url)
        if article:
            successes += 1
            if args.format == "json":
                print(json.dumps(article, ensure_ascii=False, indent=2))
            else:
                _print_pretty(url, article)
        else:
            logger.error("Extraction failed for url=%s", url)
            print(f"❌ Failed to extract: {url}", file=sys.stderr)

    all_success = successes == len(args.urls)
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
