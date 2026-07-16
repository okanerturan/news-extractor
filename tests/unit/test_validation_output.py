from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


VALIDATOR_PATH = Path(__file__).resolve().parents[1] / "validation" / "validate_live.py"


def load_validator():
    spec = importlib.util.spec_from_file_location("news_extractor_validate_live", VALIDATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ValidationOutputTests(unittest.TestCase):
    def test_json_report_redacts_url_secrets(self) -> None:
        validator = load_validator()
        raw_url = "https://alice:super-secret@example.test/a?token=top-secret#private"
        stdout = io.StringIO()
        with mock.patch.object(validator, "ArticleExtractor") as extractor_class:
            extractor_class.return_value.extract.return_value = None
            with redirect_stdout(stdout):
                self.assertEqual(
                    validator.main(["--skip-legacy", "--url", raw_url, "--json"]),
                    0,
                )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["url"], "https://example.test/a")
        self.assertNotIn("super-secret", stdout.getvalue())
        self.assertNotIn("top-secret", stdout.getvalue())

    def test_human_report_strips_title_terminal_controls(self) -> None:
        validator = load_validator()
        article = {
            "title": "\x1b[31mOwned\x1b[0m\x85title",
            "text": "safe text",
            "method": "semantic-html",
            "text_length": 9,
        }
        stdout = io.StringIO()
        with mock.patch.object(validator, "ArticleExtractor") as extractor_class:
            extractor_class.return_value.extract.return_value = article
            with redirect_stdout(stdout):
                self.assertEqual(
                    validator.main(
                        ["--skip-legacy", "--url", "https://example.test/article"]
                    ),
                    0,
                )

        output = stdout.getvalue()
        self.assertIn("Ownedtitle", output)
        self.assertNotIn("\x1b", output)
        self.assertNotIn("\x85", output)


if __name__ == "__main__":
    unittest.main()
