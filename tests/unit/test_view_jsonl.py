from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


VIEWER_PATH = Path(__file__).resolve().parents[2] / "examples" / "view_jsonl.py"


def load_viewer():
    spec = importlib.util.spec_from_file_location("news_extractor_view_jsonl", VIEWER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ViewJsonlOutputTests(unittest.TestCase):
    def test_pretty_table_strips_controls_and_redacts_url_secrets(self) -> None:
        viewer = load_viewer()
        row = {
            "title": "\x1b]0;hidden\x07Visible\x1b[31m title\x1b[0m\x85",
            "error": (
                "failed \x9b31mred\x9b0m at "
                "https://alice:super-secret@example.test/failure"
                "?token=top-secret#private"
            ),
            "source_url": (
                "https://alice:super-secret@example.test/article"
                "?token=top-secret#private"
            ),
            "extraction": {
                "image": (
                    "https://alice:credential-secret@example.test/img"
                    "?token=query-secret#fragment-secret"
                )
            },
            "metadata": {
                (
                    "https://alice:key-secret@example.test/key"
                    "?token=key-query#key-fragment"
                ): "key value",
                "references": [
                    {
                        "primary": (
                            "https://bob:nested-secret@example.test/reference"
                            "?key=nested-query#nested-fragment"
                        )
                    }
                ]
            },
            "notes": (
                "see https://alice:prose-secret@example.test/p"
                "?token=prose-query#prose-fragment now"
            ),
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hostile.jsonl"
            path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    viewer.main(
                        [
                            "--file",
                            str(path),
                            "--fields",
                            "title",
                            "error",
                            "source_url",
                            "extraction.image",
                            "metadata",
                            "notes",
                            "--wrap",
                            "0",
                        ]
                    ),
                    0,
                )

        output = stdout.getvalue()
        self.assertIn("Visible title", output)
        self.assertIn("https://example.test/failure", output)
        self.assertIn("https://example.test/article", output)
        self.assertIn("https://example.test/img", output)
        self.assertIn("https://example.test/reference", output)
        self.assertIn('"https://example.test/key": "key value"', output)
        self.assertIn("see https://example.test/p now", output)
        for forbidden in (
            "\x1b",
            "\x07",
            "\x85",
            "\x9b",
            "alice",
            "super-secret",
            "top-secret",
            "#private",
            "credential-secret",
            "query-secret",
            "fragment-secret",
            "nested-secret",
            "nested-query",
            "nested-fragment",
            "key-secret",
            "key-query",
            "key-fragment",
            "prose-secret",
            "prose-query",
            "prose-fragment",
        ):
            self.assertNotIn(forbidden, output)

    def test_wrap_keeps_intended_multiline_table_rows(self) -> None:
        viewer = load_viewer()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrapped.jsonl"
            path.write_text(
                json.dumps({"title": "alpha beta gamma delta"}) + "\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(
                    viewer.main(
                        [
                            "--file",
                            str(path),
                            "--fields",
                            "title",
                            "--wrap",
                            "10",
                        ]
                    ),
                    0,
                )

        output = stdout.getvalue()
        self.assertIn("| alpha beta |", output)
        self.assertIn("| gamma      |", output)
        self.assertIn("| delta      |", output)


if __name__ == "__main__":
    unittest.main()
