from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from news_extractor import ArticleExtractor, DownloadedDocument, cli
from news_extractor.cleaning import (
    clean_body,
    filter_keywords,
    fix_glued_sentences,
    normalize_whitespace,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class CleaningTests(unittest.TestCase):
    def test_glued_sentences_get_a_space_but_numbers_and_domains_survive(self) -> None:
        self.assertEqual(fix_glued_sentences("lira.Bu kapsamda"), "lira. Bu kapsamda")
        self.assertEqual(fix_glued_sentences("ayrıldı.ÖZEL BÜTÇELİ"), "ayrıldı. ÖZEL BÜTÇELİ")
        self.assertEqual(fix_glued_sentences("yüzde 3.5 arttı, sabah.com.tr"), "yüzde 3.5 arttı, sabah.com.tr")
        self.assertEqual(fix_glued_sentences("1.894.412.000"), "1.894.412.000")

    def test_whitespace_is_normalized_but_paragraphs_survive(self) -> None:
        text = "Merhaba    dünya ,​ tamam .\r\n  İkinci   satır"
        self.assertEqual(normalize_whitespace(text), "Merhaba dünya, tamam.\nİkinci satır")

    def test_follow_us_phrases_are_removed_wherever_they_sit(self) -> None:
        for phrase in (
            "Haberlerimizi Google'da Takip Edin",
            "Google News'te takip edin",
            "WhatsApp kanalımıza katılın",
            "Telegram kanalımıza katılın",
        ):
            with self.subTest(phrase=phrase):
                cleaned = clean_body(f"{phrase} Asıl haber metni burada başlıyor.")
                self.assertEqual(cleaned, "Asıl haber metni burada başlıyor.")

    def test_leading_byline_and_trailing_related_list_are_dropped(self) -> None:
        text = "\n".join(
            [
                "Unvan, Avrupa Editörü",
                "Yayın tarihi 3 saat önce",
                "Asıl haber paragrafı burada duruyor.",
                "İkinci haber paragrafı da burada duruyor.",
                "Başka bir haberin başlığı 12 Ekim 2026",
            ]
        )
        self.assertEqual(
            clean_body(text),
            "Asıl haber paragrafı burada duruyor.\n\nİkinci haber paragrafı da burada duruyor.",
        )

    def test_related_heading_ends_the_body(self) -> None:
        text = "Haber paragrafı bir.\nHaber paragrafı iki.\nİlgili Haberler\nBaşka haber başlığı"
        self.assertEqual(clean_body(text), "Haber paragrafı bir.\n\nHaber paragrafı iki.")

    def test_leading_title_repeat_is_dropped(self) -> None:
        self.assertEqual(clean_body("Başlık burada\nGövde paragrafı.", "Başlık burada"), "Gövde paragrafı.")

    def test_generic_keywords_are_filtered(self) -> None:
        self.assertEqual(filter_keywords(["video", "Fransa", "Paris", "Avrupa"]), ["Fransa", "Paris", "Avrupa"])
        navigation = [
            "fotoğraf", "video", "haber", "anadolu ajansı", "son dakika",
            "ekonomi", "spor", "politika",
        ]
        self.assertEqual(filter_keywords(navigation), [])
        self.assertEqual(filter_keywords(["ekonomi", "enflasyon"]), ["ekonomi", "enflasyon"])


class FixtureShapeTests(unittest.TestCase):
    def extract(self, name: str, **kwargs):
        extractor = ArticleExtractor(min_text_length=100, **kwargs)
        return extractor, extractor.extract_html(load(name), url="https://haber.example/x")

    def test_glued_jsonld_body_loses_boilerplate_glue_and_table(self) -> None:
        _, result = self.extract("glued_jsonld_with_table.html")
        assert result is not None
        text = result["text"]
        self.assertNotIn("Takip Edin", text)
        self.assertNotIn("Google", text)
        self.assertIn("ayrıldı. Bu kapsamda", text)
        self.assertNotIn("ödeneğin yüzde 28,8 arttığı görüldü.ÖZEL", text)
        self.assertNotIn("19.398.588.000", text)
        self.assertNotIn("Bütçe tablosu şöyle", text)
        self.assertTrue(text.startswith("Bütçe teklifine göre"))
        self.assertEqual(result["text_length"], len(text))

    def test_bbc_shape_drops_byline_related_list_and_disclaimer(self) -> None:
        _, result = self.extract("bbc_style_semantic.html")
        assert result is not None
        self.assertEqual(result["method"], "semantic-html")
        text = result["text"]
        self.assertTrue(text.startswith("Fransızların protesto tutkusu"))
        for junk in ("Unvan", "Yayın tarihi", "Yazan", "Avrupa Editörü", "süpermarket", "meslek hastalığı", "yapay zekadan"):
            self.assertNotIn(junk, text)
        self.assertIn("Hükümet ise protestoların seçim avantajı için", text)
        self.assertIn("sendikalar, öğrencilere katılacak", text)
        self.assertEqual(result["keywords"], ["Fransa", "Avrupa", "Paris"])

    def test_short_jsonld_body_yields_to_the_fuller_page_body(self) -> None:
        _, result = self.extract("short_jsonld_long_page.html")
        assert result is not None
        self.assertEqual(result["method"], "semantic-html")
        self.assertIn("ortak bir eylem gündeminin", result["text"])
        for junk in ("***", "[1]", "AA Haber Akış", "Ombudsman"):
            self.assertNotIn(junk, result["text"])
        self.assertEqual(result["keywords"], [])

    def test_jsonld_body_is_kept_when_it_is_the_fuller_one(self) -> None:
        _, result = self.extract("jsonld_news_article.html")
        assert result is not None
        self.assertEqual(result["method"], "json-ld")

    def test_example_domain_and_section_front_pages_are_rejected(self) -> None:
        for name in ("example_domain.html", "section_front_page.html"):
            with self.subTest(name=name):
                extractor, result = self.extract(name)
                self.assertIsNone(result)
                self.assertIn("not-an-article", extractor.last_error or "")

    def test_cli_reports_reason_and_exits_nonzero_for_non_articles(self) -> None:
        class Client:
            def fetch(self, url: str) -> DownloadedDocument:
                return DownloadedDocument(load("example_domain.html"), url, "text/html")

        from unittest import mock

        real = ArticleExtractor

        def build(**kwargs):
            return real(http_client=Client(), **kwargs)

        stderr = io.StringIO()
        with mock.patch("news_extractor.cli.ArticleExtractor", side_effect=build):
            with redirect_stderr(stderr):
                code = cli.main(["https://example.com/", "--log-level", "ERROR"])
        self.assertEqual(code, 1)
        self.assertIn("not-an-article", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
