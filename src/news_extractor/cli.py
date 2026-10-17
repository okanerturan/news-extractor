from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any, Dict, Iterable

from .article_extractor import ArticleExtractor, _safe_terminal_text, _safe_url_for_log

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
        help=(
            "Absolute wall-clock budget in seconds for DNS, redirects, connection, "
            "request, headers, and response body (default: 10)."
        ),
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
    print(f"URL: {_safe_url_for_log(url)}")
    print(f"Method: {_safe_terminal_text(article['method'])}")
    print(f"Title: {_safe_terminal_text(article['title'])}")
    authors = (
        ", ".join(_safe_terminal_text(author) for author in article["authors"])
        if article.get("authors")
        else "N/A"
    )
    print(f"Authors: {authors}")
    print(f"Date: {_safe_terminal_text(article.get('date'))}")
    keywords = ", ".join(
        _safe_terminal_text(keyword) for keyword in article.get("keywords", [])[:5]
    ) or "N/A"
    print(f"Keywords: {keywords}")
    print(f"Text length: {article['text_length']} chars")
    print("-" * 80)
    preview = _safe_terminal_text(
        (article.get("text") or "")[:300],
        preserve_newlines=True,
    )
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
        logger.error("Invalid configuration: %s", _safe_terminal_text(exc))
        return 2

    successes = 0
    for url in args.urls:
        article = extractor.extract(url)
        if article:
            successes += 1
            if args.format == "json":
                display_article = dict(article)
                for key in ("url", "final_url", "image"):
                    if display_article.get(key):
                        display_article[key] = _safe_url_for_log(display_article[key])
                print(json.dumps(display_article, ensure_ascii=False, indent=2))
            else:
                _print_pretty(url, article)
        else:
            safe_url = _safe_url_for_log(url)
            reason = _safe_terminal_text(extractor.last_error or "unknown")
            logger.error("Extraction failed for url=%s reason=%s", safe_url, reason)
            print(f"❌ Failed to extract: {safe_url} ({reason})", file=sys.stderr)

    all_success = successes == len(args.urls)
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
