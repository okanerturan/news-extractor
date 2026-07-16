from __future__ import annotations

import json
import unittest
from pathlib import Path


VIEWER = Path(__file__).resolve().parents[2] / "examples" / "backlog_viewer.html"


class BacklogViewerSecurityTests(unittest.TestCase):
    def test_hostile_scalars_use_dom_text_and_javascript_urls_are_rejected(self) -> None:
        hostile_jsonl = json.dumps(
            {
                "article_id": '<img src=x onerror="alert(1)">',
                "title": "</div><script>alert(2)</script>",
                "date": '<svg onload="alert(3)">',
                "source_url": "javascript:alert(4)",
                "canonical_url": "data:text/html,<script>alert(5)</script>",
                "extraction": {
                    "method": '<img src=x onerror="alert(6)">',
                    "text_length": '<iframe srcdoc="<script>alert(7)</script>">',
                    "text": "<script>alert(8)</script>",
                },
            }
        )
        row = json.loads(hostile_jsonl)
        self.assertEqual(row["source_url"].split(":", 1)[0], "javascript")

        source = VIEWER.read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML", source)
        self.assertNotIn("insertAdjacentHTML", source)
        self.assertNotIn("document.write", source)
        self.assertIn('if (!["http:", "https:"].includes(url.protocol)) return null;', source)
        self.assertIn("identifier.textContent =", source)
        self.assertIn("title.textContent =", source)
        self.assertIn("subtitle.textContent =", source)
        self.assertIn("option.textContent = method", source)
        self.assertIn("pre.textContent = summaryText", source)
        self.assertIn("cardsRoot.replaceChildren", source)
        self.assertNotIn('href="${', source)


if __name__ == "__main__":
    unittest.main()
