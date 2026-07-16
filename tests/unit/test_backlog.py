from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from news_extractor.backlog import (
    BacklogRecord,
    load_records,
    print_pretty,
    reextract,
    summarize,
    write_jsonl,
)


class FakeExtractor:
    def extract(self, url: str) -> dict[str, object] | None:
        if url.endswith("/error"):
            raise RuntimeError("synthetic failure")
        if url.endswith("/empty"):
            return None
        return {"method": "semantic-html", "text": "content", "text_length": 7}


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


class BacklogTests(unittest.TestCase):
    def test_load_records_applies_newest_first_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "articles.db"
            create_backlog(database)

            records = load_records(database, limit=2, offset=1)

        self.assertEqual([item.article_id for item in records], [3, 1])
        self.assertEqual([item.title for item in records], ["Middle", "Old"])

    def test_reextract_captures_success_empty_and_unexpected_errors(self) -> None:
        results = reextract(
            [record(1, "ok"), record(2, "empty"), record(3, "error")],
            extractor=FakeExtractor(),  # type: ignore[arg-type]
        )

        self.assertEqual(results[0]["extraction"]["method"], "semantic-html")
        self.assertIsNone(results[0]["error"])
        self.assertIsNone(results[1]["extraction"])
        self.assertIsNone(results[1]["error"])
        self.assertIsNone(results[2]["extraction"])
        self.assertEqual(results[2]["error"], "RuntimeError: extraction failed")
        summary = summarize(results)
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["successes"], 1)
        self.assertAlmostEqual(summary["success_rate"], 100 / 3)
        self.assertEqual(summarize([]), {"total": 0, "successes": 0, "success_rate": 0.0})

    def test_write_jsonl_preserves_unicode_and_creates_parent_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "nested" / "results.jsonl"
            entries = [{"title": "Türkçe başlık", "extraction": None}]

            write_jsonl(entries, destination)

            self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), entries[0])

    def test_pretty_output_redacts_urls_and_terminal_controls(self) -> None:
        entries = [
            {
                "article_id": "7\x9b31m",
                "title": "\x1b[31mOwned\x1b[0m\x85title",
                "domain": "example.test\x90",
                "source_url": "https://alice:super-secret@example.test/a?token=top-secret",
                "canonical_url": "https://example.test/a?token=top-secret#private",
                "extraction": {
                    "method": "semantic-html\x1b[2J",
                    "text_length": 20,
                    "keywords": ["safe\x9b31m"],
                    "text": "line one\n\x1b]0;hijack\x07line two",
                },
                "error": None,
            },
            {
                "article_id": 8,
                "title": "Failed",
                "domain": "example.test",
                "source_url": "https://example.test/failure",
                "canonical_url": "https://example.test/failure",
                "extraction": None,
                "error": (
                    "failed\t\x1b[31mred\x1b[0m at "
                    "https://alice:super-secret@example.test/failure"
                    "?token=top-secret#private"
                ),
            },
        ]
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            print_pretty(entries)

        output = stdout.getvalue()
        self.assertIn("https://example.test/a", output)
        self.assertIn("https://example.test/failure", output)
        self.assertIn("Ownedtitle", output)
        self.assertNotIn("super-secret", output)
        self.assertNotIn("top-secret", output)
        for control in ("\t", "\x1b", "\x85", "\x90", "\x9b"):
            self.assertNotIn(control, output)


if __name__ == "__main__":
    unittest.main()
