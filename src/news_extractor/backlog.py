from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from news_extractor import ArticleExtractor
from news_extractor.article_extractor import _safe_terminal_text, _safe_url_for_log


@dataclass(frozen=True)
class BacklogRecord:
    article_id: int
    url: str
    canonical_url: str
    title: str
    domain: str
    stored_at: int


def load_records(db_path: Path, limit: int, offset: int) -> List[BacklogRecord]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            """
            SELECT id, url, canonical_url, title, domain, stored_at
            FROM articles
            ORDER BY stored_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    return [
        BacklogRecord(
            article_id=row["id"],
            url=row["url"],
            canonical_url=row["canonical_url"],
            title=row["title"],
            domain=row["domain"],
            stored_at=row["stored_at"],
        )
        for row in rows
    ]


def reextract(
    records: Iterable[BacklogRecord],
    *,
    min_text_length: int = 100,
    extractor: Optional[ArticleExtractor] = None,
) -> List[Dict[str, Any]]:
    extractor = extractor or ArticleExtractor(min_text_length=min_text_length)
    results: List[Dict[str, Any]] = []

    for record in records:
        payload: Dict[str, Any] = {
            "article_id": record.article_id,
            "canonical_url": record.canonical_url,
            "source_url": record.url,
            "title": record.title,
            "domain": record.domain,
            "stored_at": record.stored_at,
        }

        article: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        try:
            article = extractor.extract(record.url)
        except Exception as exc:  # capture unexpected failures
            error = f"{type(exc).__name__}: extraction failed"

        payload["extraction"] = article
        payload["error"] = error
        results.append(payload)

    return results


def summarize(results: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    results_list = list(results)
    successes = sum(1 for entry in results_list if entry.get("extraction"))
    total = len(results_list)
    pct = (successes / total * 100) if total else 0.0
    return {
        "total": total,
        "successes": successes,
        "success_rate": pct,
    }


def write_jsonl(results: Iterable[Dict[str, Any]], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as fh:
        for entry in results:
            fh.write(json.dumps(entry, ensure_ascii=False))
            fh.write("\n")


def print_pretty(results: Iterable[Dict[str, Any]]) -> None:
    for entry in results:
        print("=" * 100)
        print(
            f"[{_safe_terminal_text(entry['article_id'])}] "
            f"{_safe_terminal_text(entry['title'])} "
            f"({_safe_terminal_text(entry['domain'])})"
        )
        print(f"URL: {_safe_url_for_log(entry['source_url'])}")
        print(f"Canonical: {_safe_url_for_log(entry['canonical_url'])}")
        extraction = entry.get("extraction")

        if extraction:
            print(f"Method: {_safe_terminal_text(extraction['method'])}")
            print(f"Text length: {_safe_terminal_text(extraction['text_length'])}")
            keywords = ", ".join(
                _safe_terminal_text(keyword)
                for keyword in (extraction.get("keywords") or [])
            ) or "N/A"
            print(f"Keywords: {keywords}")
            raw_preview = (extraction.get("text") or "")[:280]
            preview = _safe_terminal_text(
                raw_preview,
                preserve_newlines=True,
                preserve_tabs=True,
            )
            print("-" * 100)
            print(preview + ("..." if len(raw_preview) == 280 else ""))
        else:
            print("Extraction: ❌")
            error = entry.get("error")
            if error:
                print(f"Error: {_safe_terminal_text(error)}")
        print()
