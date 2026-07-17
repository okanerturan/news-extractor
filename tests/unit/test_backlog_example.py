from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[2] / "examples" / "scrape_news_gatherer_backlog.py"


def load_script():
    spec = importlib.util.spec_from_file_location("news_extractor_backlog_example", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load backlog example")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BacklogExampleTests(unittest.TestCase):
    def test_json_mode_keeps_stdout_valid_jsonl_and_sends_summary_to_stderr(self) -> None:
        script = load_script()
        results = [
            {
                "article_id": 1,
                "title": "Türkçe başlık",
                "extraction": {"method": "semantic-html", "text_length": 20},
                "error": None,
            }
        ]

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "news-gatherer.db"
            database.touch()
            stdout = io.StringIO()
            stderr = io.StringIO()
            with (
                mock.patch.object(script, "load_records", return_value=[object()]),
                mock.patch.object(script, "reextract", return_value=results),
                mock.patch.object(
                    script,
                    "summarize",
                    return_value={"total": 1, "successes": 1, "success_rate": 100.0},
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = script.main(["--db", str(database), "--format", "json"])

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout.getvalue().splitlines() if line]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), results[0])
        self.assertNotIn("Summary:", stdout.getvalue())
        self.assertIn("Summary: 1/1 extractions succeeded", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
