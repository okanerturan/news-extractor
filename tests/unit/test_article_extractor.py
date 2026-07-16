from __future__ import annotations

import unittest
from pathlib import Path

from news_extractor import ArticleExtractor, DownloadedDocument, FetchError


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeHTTPClient:
    def __init__(self, document: DownloadedDocument | None = None, error: Exception | None = None):
        self.document = document
        self.error = error
        self.urls: list[str] = []

    def fetch(self, url: str) -> DownloadedDocument:
        self.urls.append(url)
        if self.error:
            raise self.error
        assert self.document is not None
        return self.document


class ArticleExtractorTests(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_json_ld_news_article_is_preferred_and_preserves_turkish(self) -> None:
        result = ArticleExtractor(min_text_length=100).extract_html(
            self.fixture("jsonld_news_article.html"),
            url="https://haber.example/haber/42",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["method"], "json-ld")
        self.assertEqual(result["title"], "İstanbul'da kültür ve teknoloji buluşması")
        self.assertEqual(result["authors"], ["Ayşe Şahin", "Mehmet Öztürk"])
        self.assertEqual(result["keywords"], ["İstanbul", "açık kaynak", "teknoloji"])
        self.assertEqual(result["categories"], ["Teknoloji", "Kültür"])
        self.assertEqual(result["image"], "https://haber.example/images/bulusma.jpg")
        self.assertIn("Türkçe dil araçlarını", result["text"])
        self.assertNotIn("kısa sayfa metni", result["text"])
        self.assertEqual(result["text_length"], len(result["text"]))
        self.assertTrue(result["extracted_at"].endswith("+00:00"))

    def test_semantic_fallback_uses_main_article_and_excludes_chrome(self) -> None:
        result = ArticleExtractor(min_text_length=100).extract_html(
            self.fixture("semantic_article.html"),
            url="https://haber.example/gundem/calistay",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["method"], "semantic-html")
        self.assertEqual(result["title"], "Yapısal başlık ama gövde yok")
        self.assertEqual(result["authors"], ["Elif Işık"])
        self.assertEqual(result["date"], "2026-07-15T14:00:00+03:00")
        self.assertEqual(result["image"], "https://haber.example/media/calistay.jpg")
        self.assertIn("bağımlılık yönetimi", result["text"])
        self.assertIn("Güvenlik sonradan", result["text"])
        self.assertNotIn("Üye ol", result["text"])
        self.assertNotIn("reklam", result["text"])
        self.assertNotIn("Telif", result["text"])

    def test_malformed_json_ld_falls_back_to_semantic_html(self) -> None:
        html = """
        <script type="application/ld+json">{"@type": "NewsArticle", broken}</script>
        <article><h1>Başlık</h1>
        <p>Bu paragraf, bozuk yapılandırılmış veriye rağmen güvenli anlamsal çıkarımın çalıştığını gösteren yeterince uzun bir Türkçe metindir.</p>
        </article>
        """
        result = ArticleExtractor(min_text_length=80).extract_html(
            html,
            url="https://example.test/article",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["method"], "semantic-html")
        self.assertEqual(result["title"], "Başlık")

    def test_deep_json_ld_cannot_crash_semantic_fallback(self) -> None:
        deeply_nested = "[" * 2_000 + "0" + "]" * 2_000
        html = (
            f'<script type="application/ld+json">{deeply_nested}</script>'
            "<article><h1>Derin veri testi</h1>"
            "<p>Yapılandırılmış veri aşırı derin olsa bile anlamsal çıkarımın çalışmaya devam etmesini sağlayan yeterince uzun güvenli Türkçe içerik.</p>"
            "</article>"
        )

        result = ArticleExtractor(min_text_length=80).extract_html(
            html,
            url="https://example.test/deep-json",
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["method"], "semantic-html")

    def test_short_or_navigation_only_documents_are_rejected(self) -> None:
        html = "<html><nav><p>Gündem Spor</p></nav><article><p>Kısa.</p></article></html>"
        self.assertIsNone(
            ArticleExtractor(min_text_length=50).extract_html(
                html,
                url="https://example.test/short",
            )
        )

    def test_extract_uses_download_final_url_and_returns_none_on_fetch_error(self) -> None:
        html = self.fixture("semantic_article.html")
        client = FakeHTTPClient(
            DownloadedDocument(html, "https://cdn.example/final", "text/html")
        )
        extractor = ArticleExtractor(min_text_length=100, http_client=client)

        result = extractor.extract("https://haber.example/start")

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["url"], "https://haber.example/start")
        self.assertEqual(result["final_url"], "https://cdn.example/final")
        self.assertEqual(client.urls, ["https://haber.example/start"])

        failing = ArticleExtractor(
            http_client=FakeHTTPClient(error=FetchError("synthetic failure"))
        )
        with self.assertLogs("news_extractor.article_extractor", level="WARNING"):
            self.assertIsNone(failing.extract("https://example.test/failure"))

    def test_batch_statistics_preserve_public_contract(self) -> None:
        extractor = ArticleExtractor()
        outcomes = {
            "https://example.test/one": {"method": "json-ld"},
            "https://example.test/two": {"method": "semantic-html"},
            "https://example.test/three": None,
        }
        extractor.extract = outcomes.get  # type: ignore[method-assign]

        results = extractor.extract_batch(list(outcomes))

        stats = extractor.get_stats(results)
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["successful"], 2)
        self.assertEqual(stats["failed"], 1)
        self.assertAlmostEqual(stats["success_rate"], 200 / 3)
        self.assertEqual(stats["methods"], {"json-ld": 1, "semantic-html": 1})
        self.assertEqual(
            extractor.get_stats({}),
            {"total": 0, "successful": 0, "failed": 0, "success_rate": 0, "methods": {}},
        )

    def test_constructor_rejects_unbounded_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_text_length"):
            ArticleExtractor(min_text_length=0)
        with self.assertRaisesRegex(ValueError, "timeout"):
            ArticleExtractor(timeout=0)
        with self.assertRaisesRegex(ValueError, "timeout"):
            ArticleExtractor(timeout=float("nan"))
        with self.assertRaisesRegex(ValueError, "max_response_bytes"):
            ArticleExtractor(max_response_bytes=0)
        with self.assertRaisesRegex(ValueError, "max_redirects"):
            ArticleExtractor(max_redirects=-1)


if __name__ == "__main__":
    unittest.main()
