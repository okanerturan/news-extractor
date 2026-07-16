from __future__ import annotations

import json

import pytest
import requests

import news_extractor.article_extractor as extractor_module
from news_extractor import ArticleExtractor


class SuccessfulArticle:
    def __init__(self, url: str, config: object) -> None:
        self.url = url
        self.config = config
        self.title = "Test article"
        self.text = "A" * 180
        self.authors = ["Author"]
        self.publish_date = None
        self.meta_keywords = ["test"]
        self.meta_description = "Description"
        self.top_image = "https://example.test/image.jpg"

    def download(self) -> None:
        return None

    def parse(self) -> None:
        return None


class ShortArticle(SuccessfulArticle):
    def __init__(self, url: str, config: object) -> None:
        super().__init__(url, config)
        self.text = "too short"


class BrokenArticle(SuccessfulArticle):
    def download(self) -> None:
        raise RuntimeError("download failed")


class FakeResponse:
    text = "<html><article>fallback</article></html>"

    def raise_for_status(self) -> None:
        return None


def test_primary_extractor_returns_structured_article(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor_module, "Article", SuccessfulArticle)
    extractor = ArticleExtractor(min_text_length=100)
    monkeypatch.setattr(
        extractor,
        "_extract_trafilatura",
        lambda url: pytest.fail(f"fallback should not run for {url}"),
    )

    result = extractor.extract("https://example.test/primary")

    assert result is not None
    assert result["method"] == "newspaper4k"
    assert result["title"] == "Test article"
    assert result["authors"] == ["Author"]
    assert result["keywords"] == ["test"]
    assert result["text_length"] == 180
    assert result["extracted_at"].endswith("+00:00")


def test_short_primary_result_uses_trafilatura_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor_module, "Article", ShortArticle)

    def fake_get(url: str, *, headers: dict[str, str], timeout: int) -> FakeResponse:
        assert url == "https://example.test/fallback"
        assert headers["User-Agent"].startswith("Mozilla/")
        assert timeout == 7
        return FakeResponse()

    def fake_extract(html: str, **options: object) -> str:
        assert html == FakeResponse.text
        assert options == {
            "output_format": "json",
            "include_comments": False,
            "include_tables": True,
            "with_metadata": True,
        }
        return json.dumps(
            {
                "title": "Fallback article",
                "text": "B" * 160,
                "author": "Fallback Author",
                "date": "2026-07-16",
                "excerpt": "Fallback description",
                "image": "https://example.test/fallback.jpg",
                "categories": "NEWS",
            }
        )

    monkeypatch.setattr(extractor_module.requests, "get", fake_get)
    monkeypatch.setattr(extractor_module.trafilatura, "extract", fake_extract)

    result = ArticleExtractor(min_text_length=100, timeout=7).extract(
        "https://example.test/fallback"
    )

    assert result is not None
    assert result["method"] == "trafilatura"
    assert result["title"] == "Fallback article"
    assert result["authors"] == ["Fallback Author"]
    assert result["text_length"] == 160
    assert result["extracted_at"].endswith("+00:00")


def test_both_extraction_failures_return_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extractor_module, "Article", BrokenArticle)

    def fail_request(*args: object, **kwargs: object) -> FakeResponse:
        raise requests.Timeout("timed out")

    monkeypatch.setattr(extractor_module.requests, "get", fail_request)

    assert ArticleExtractor().extract("https://example.test/failure") is None


def test_batch_statistics_count_methods_and_empty_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    extractor = ArticleExtractor()
    outcomes = {
        "https://example.test/one": {"method": "newspaper4k"},
        "https://example.test/two": {"method": "trafilatura"},
        "https://example.test/three": None,
    }
    monkeypatch.setattr(extractor, "extract", outcomes.get)

    results = extractor.extract_batch(list(outcomes))

    assert extractor.get_stats(results) == {
        "total": 3,
        "successful": 2,
        "failed": 1,
        "success_rate": pytest.approx(66.6666666667),
        "methods": {"newspaper4k": 1, "trafilatura": 1},
    }
    assert extractor.get_stats({}) == {
        "total": 0,
        "successful": 0,
        "failed": 0,
        "success_rate": 0,
        "methods": {},
    }
