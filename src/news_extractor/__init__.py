"""Top-level package for the News Extractor article extraction toolkit."""

from .article_extractor import (
    ArticleExtractor,
    DownloadedDocument,
    FetchError,
    SafeHTTPClient,
    UnsafeUrlError,
    extract_article,
)

__all__ = [
    "ArticleExtractor",
    "DownloadedDocument",
    "FetchError",
    "SafeHTTPClient",
    "UnsafeUrlError",
    "extract_article",
]
__version__ = "0.2.0"
