from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from news_extractor.backlog import BacklogRecord, load_records, reextract, summarize, write_jsonl


class FakeExtractor:
    def extract(self, url: str) -> dict[str, object] | None:
        if url.endswith("/error"):
            raise RuntimeError("synthetic failure")
        if url.endswith("/empty"):
            return None
        return {"method": "newspaper4k", "text": "content", "text_length": 7}


def create_backlog(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE articles (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                stored_at INTEGER NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, "https://example.test/old", "https://example.test/old", "Old", "example.test", 10),
                (2, "https://example.test/new", "https://example.test/new", "New", "example.test", 30),
                (3, "https://example.test/middle", "https://example.test/middle", "Middle", "example.test", 20),
            ],
        )
        connection.commit()
    finally:
        connection.close()


def record(article_id: int, suffix: str) -> BacklogRecord:
    url = f"https://example.test/{suffix}"
    return BacklogRecord(article_id, url, url, suffix.title(), "example.test", article_id)


def test_load_records_applies_newest_first_pagination(tmp_path: Path) -> None:
    database = tmp_path / "articles.db"
    create_backlog(database)

    records = load_records(database, limit=2, offset=1)

    assert [item.article_id for item in records] == [3, 1]
    assert [item.title for item in records] == ["Middle", "Old"]


def test_reextract_captures_success_empty_and_unexpected_errors() -> None:
    results = reextract(
        [record(1, "ok"), record(2, "empty"), record(3, "error")],
        extractor=FakeExtractor(),
    )

    assert results[0]["extraction"]["method"] == "newspaper4k"
    assert results[0]["error"] is None
    assert results[1]["extraction"] is None
    assert results[1]["error"] is None
    assert results[2]["extraction"] is None
    assert results[2]["error"] == "RuntimeError: synthetic failure"
    summary = summarize(results)
    assert summary["total"] == 3
    assert summary["successes"] == 1
    assert summary["success_rate"] == pytest.approx(100 / 3)
    assert summarize([]) == {"total": 0, "successes": 0, "success_rate": 0.0}


def test_write_jsonl_preserves_unicode_and_creates_parent_directory(tmp_path: Path) -> None:
    destination = tmp_path / "nested" / "results.jsonl"
    entries = [{"title": "Türkçe başlık", "extraction": None}]

    write_jsonl(entries, destination)

    assert json.loads(destination.read_text(encoding="utf-8")) == entries[0]
