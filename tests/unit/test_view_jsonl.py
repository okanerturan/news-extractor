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
        for forbidden in (
            "\x1b",
            "\x07",
            "\x85",
            "\x9b",
            "alice",
            "super-secret",
            "top-secret",
            "#private",
        ):
            self.assertNotIn(forbidden, output)


if __name__ == "__main__":
    unittest.main()
