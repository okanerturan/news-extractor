#!/usr/bin/env python3
"""Opt-in live smoke test for the current dependency-free extractor.

This script reports publisher drift separately from deterministic unit tests. It
does not reproduce or compare the November 2025 Newspaper4k/Trafilatura result;
that frozen evidence is documented in RESEARCH.md.
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Iterable

from news_extractor import ArticleExtractor
from news_extractor.article_extractor import _safe_terminal_text, _safe_url_for_log


LEGACY_CORPUS = [
    ("T24 article", "https://t24.com.tr/haber/victor-osimhen-sampiyonlar-ligi-nde-haftanin-11-ine-secildi,1274139"),
    ("Sözcü article", "https://www.sozcu.com.tr/2025/gundem/son-dakika-haberi-rusen-cakir-gozaltina-alindi-8423910/"),
    ("NTV gallery (out of scope)", "https://www.ntv.com.tr/galeri/turkiye/son-dakika-gaziantepte-deprem-kandilli-ve-afad-son-depremler-listesi,9kQ8R0F5pESlN-Nn6_jYxg"),
    ("Cumhuriyet article", "https://www.cumhuriyet.com.tr/turkiye/turkiye-vize-kolayligi-getirilen-ulkeler-listesi-listede-hangi-ulkeler-var-2261093"),
    ("Bianet article", "https://bianet.org/haber/erdogan-ozele-tazminat-davasi-acti-313281"),
    ("OdaTV article", "https://www.odatv.com/guncel/akran-zorbaligi-davasinda-karar-cikti-120122351"),
]
ERROR_MARKERS = ("404", "sayfa bulunamadı", "page not found")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", default=[], help="Validate an additional URL.")
    parser.add_argument(
        "--skip-legacy",
        action="store_true",
        help="Run only URLs supplied with --url instead of the six-URL legacy corpus.",
    )
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    targets = [] if args.skip_legacy else list(LEGACY_CORPUS)
    targets.extend(("Additional URL", url) for url in args.url)
    if not targets:
        raise SystemExit("no validation URLs selected")
    extractor = ArticleExtractor(timeout=args.timeout, max_response_bytes=args.max_bytes)
    rows: list[dict[str, object]] = []

    for name, url in targets:
        started = time.perf_counter()
        article = extractor.extract(url)
        elapsed = time.perf_counter() - started
        combined = " ".join(
            str(value or "") for value in ((article or {}).get("title"), (article or {}).get("text"))
        ).casefold()
        rows.append(
            {
                "name": name,
                "url": _safe_url_for_log(url),
                "success": article is not None,
                "needs_manual_review": any(marker in combined for marker in ERROR_MARKERS),
                "method": (article or {}).get("method"),
                "title": (article or {}).get("title"),
                "text_length": (article or {}).get("text_length", 0),
                "elapsed_seconds": round(elapsed, 3),
            }
        )

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print("Current live validation (network-dependent; not a CI gate)")
        print("=" * 72)
        for row in rows:
            status = "OK" if row["success"] else "FAIL"
            review = " REVIEW" if row["needs_manual_review"] else ""
            print(
                f"[{status}{review}] {_safe_terminal_text(row['name'])}: "
                f"{_safe_terminal_text(row['method'] or '-')} / "
                f"{row['text_length']} chars / {row['elapsed_seconds']}s"
            )
            print(f"  {_safe_url_for_log(row['url'])}")
            if row["title"]:
                print(f"  {_safe_terminal_text(row['title'])}")

        successful = sum(bool(row["success"]) for row in rows)
        print(f"\nObserved successes: {successful}/{len(rows)}")
        print("Publisher removals, bot controls, and gallery pages require manual classification.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
