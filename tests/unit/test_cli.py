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
                self.assertEqual(cli.main(["https://example.test/failure"]), 1)
        self.assertIn("Failed to extract", stderr.getvalue())

        self.assertEqual(cli.main(["https://example.test", "--timeout", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
