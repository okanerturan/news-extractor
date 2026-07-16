from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from news_extractor import cli


class CLITests(unittest.TestCase):
    def test_json_mode_preserves_unicode_and_passes_security_bounds(self) -> None:
        article = {
            "url": "https://example.test/article",
            "title": "Türkçe başlık",
            "text": "Güvenli içerik",
            "authors": ["Ayşe"],
            "keywords": ["güvenlik"],
            "date": None,
            "method": "json-ld",
            "text_length": 15,
        }
        stdout = io.StringIO()
        with mock.patch("news_extractor.cli.ArticleExtractor") as extractor_class:
            extractor_class.return_value.extract.return_value = article
            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "https://example.test/article",
                        "--format",
                        "json",
                        "--timeout",
                        "4",
                        "--max-bytes",
                        "4096",
                        "--max-redirects",
                        "2",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["title"], "Türkçe başlık")
        extractor_class.assert_called_once_with(
            min_text_length=100,
            timeout=4.0,
            max_response_bytes=4096,
            max_redirects=2,
            allow_private_networks=False,
        )

    def test_failed_extraction_and_invalid_configuration_return_nonzero(self) -> None:
        stderr = io.StringIO()
        with mock.patch("news_extractor.cli.ArticleExtractor") as extractor_class:
            extractor_class.return_value.extract.return_value = None
            with redirect_stderr(stderr):
                self.assertEqual(
                    cli.main(
                        [
                            "https://alice:super-secret@example.test/failure"
                            "?token=top-secret#private"
                        ]
                    ),
                    1,
                )
        self.assertIn("Failed to extract", stderr.getvalue())
        self.assertIn("https://example.test/failure", stderr.getvalue())
        self.assertNotIn("super-secret", stderr.getvalue())
        self.assertNotIn("top-secret", stderr.getvalue())

        self.assertEqual(cli.main(["https://example.test", "--timeout", "0"]), 2)

    def test_pretty_output_redacts_urls_and_strips_terminal_controls(self) -> None:
        article = {
            "url": "https://alice:super-secret@example.test/article?token=top-secret",
            "title": "\x1b[31mOwned\x1b[0m\x85title",
            "text": "safe\n\t\x1b]0;hijack\x07body\x9b31m",
            "authors": ["A\x1b[2Juthor"],
            "keywords": ["key\x90word"],
            "date": "2026-01-01\x1b[5m",
            "method": "json-ld",
            "text_length": 12,
        }
        stdout = io.StringIO()
        raw_url = "https://alice:super-secret@example.test/article?token=top-secret#frag"
        with mock.patch("news_extractor.cli.ArticleExtractor") as extractor_class:
            extractor_class.return_value.extract.return_value = article
            with redirect_stdout(stdout):
                self.assertEqual(cli.main([raw_url]), 0)

        output = stdout.getvalue()
        self.assertIn("https://example.test/article", output)
        self.assertIn("Ownedtitle", output)
        self.assertNotIn("super-secret", output)
        self.assertNotIn("top-secret", output)
        self.assertNotIn("\t", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x85", output)
        self.assertNotIn("\x90", output)
        self.assertNotIn("\x9b", output)


if __name__ == "__main__":
    unittest.main()
