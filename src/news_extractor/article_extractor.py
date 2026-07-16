#!/usr/bin/env python3
"""
Turkish News Article Extractor
===============================

Article extraction with a two-tier fallback strategy.

Strategy:
    1. Primary: Newspaper4k (fast, clean extraction)
    2. Fallback: Trafilatura JSON (robust, handles edge cases)

Recorded November 2025 snapshot:
    - Success rate: 5/6 fixed URLs
    - Average time: 0.55s per article
    - Primary usage: 3/6 URLs
    - Fallback usage: 2/6 URLs

These figures are dated research evidence, not a permanent service-level guarantee.

Dependencies:
    pip install newspaper4k trafilatura requests
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import trafilatura
from newspaper import Article, Config

logger = logging.getLogger(__name__)


class ArticleExtractor:
    """
    Extract article content from Turkish news websites.

    Features:
        - Two-tier extraction (Newspaper4k → Trafilatura)
        - Clean article-only text
        - Metadata extraction (title, authors, date, keywords)
        - Fast (<1s average)
        - Free and open-source

    Example:
        >>> extractor = ArticleExtractor()
        >>> article = extractor.extract('https://bianet.org/haber/...')
        >>> print(article['title'])
        >>> print(article['text'][:200])
    """

    def __init__(
        self,
        language: str = 'tr',
        min_text_length: int = 100,
        timeout: int = 10
    ):
        """
        Initialize the extractor.

        Args:
            language: Article language code (default: 'tr' for Turkish)
            min_text_length: Minimum chars to consider extraction successful
            timeout: HTTP request timeout in seconds
        """
        self.language = language
        self.min_text_length = min_text_length
        self.timeout = timeout

        # Configure Newspaper4k
        self.n4k_config = Config()
        self.n4k_config.language = language
        self.n4k_config.request_timeout = timeout

        # User-agent for Trafilatura fallback
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

    def extract(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract article from URL using two-tier strategy.

        Args:
            url: Article URL

        Returns:
            Dictionary with article data, or None if extraction failed

        Example:
            >>> result = extractor.extract('https://bianet.org/...')
            >>> print(result)
            {
                'url': 'https://...',
                'title': 'Article title',
                'text': 'Article content...',
                'authors': ['Author Name'],
                'date': '2025-11-06',
                'keywords': ['keyword1', 'keyword2'],
                'image': 'https://...',
                'method': 'newspaper4k',
                'text_length': 1027,
                'extracted_at': '2025-11-07T...'
            }
        """
        # Try primary method
        result = self._extract_newspaper4k(url)
        if result:
            return result

        # Try fallback
        result = self._extract_trafilatura(url)
        if result:
            return result

        logger.error("Article extraction failed for url=%s (both methods)", url)
        return None

    def _extract_newspaper4k(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract using Newspaper4k (primary method).

        Fast and clean extraction, works on 50% of URLs.
        """
        try:
            article = Article(url, config=self.n4k_config)
            article.download()
            article.parse()

            # Check if we got meaningful text
            if len(article.text) < self.min_text_length:
                logger.debug(
                    "Newspaper4k text too short for url=%s (len=%s)",
                    url,
                    len(article.text),
                )
                return None

            return {
                'url': url,
                'title': article.title,
                'text': article.text,
                'authors': article.authors,
                'date': article.publish_date.isoformat() if article.publish_date else None,
                'keywords': article.meta_keywords or [],
                'description': article.meta_description,
                'image': article.top_image,
                'method': 'newspaper4k',
                'text_length': len(article.text),
                'extracted_at': datetime.now(timezone.utc).isoformat()
            }

        except Exception as exc:  # Newspaper4k raises several internal exceptions
            logger.warning("Newspaper4k failed for url=%s: %s", url, exc)
            return None

    def _extract_trafilatura(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Extract using Trafilatura (fallback method).

        More robust, handles edge cases that Newspaper4k misses.
        Adds ~200ms overhead but rescues ~33% of extractions.
        """
        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("HTTP request failed for url=%s: %s", url, exc)
            return None

        json_str = trafilatura.extract(
            response.text,
            output_format='json',
            include_comments=False,
            include_tables=True,
            with_metadata=True
        )

        if not json_str:
            logger.debug("Trafilatura returned empty payload for url=%s", url)
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as exc:
            logger.warning("Unable to decode Trafilatura JSON for url=%s: %s", url, exc)
            return None

        text = data.get('text', '')

        if len(text) < self.min_text_length:
            logger.debug(
                "Trafilatura text too short for url=%s (len=%s)",
                url,
                len(text),
            )
            return None

        return {
            'url': url,
            'title': data.get('title'),
            'text': text,
            'authors': [data.get('author')] if data.get('author') else [],
            'date': data.get('date'),
            'keywords': [],
            'description': data.get('excerpt'),
            'image': data.get('image'),
            'categories': data.get('categories'),
            'method': 'trafilatura',
            'text_length': len(text),
            'extracted_at': datetime.now(timezone.utc).isoformat()
        }

    def extract_batch(self, urls: List[str]) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Extract multiple articles.

        Args:
            urls: List of article URLs

        Returns:
            Dictionary mapping URLs to extraction results

        Example:
            >>> urls = ['https://...', 'https://...']
            >>> results = extractor.extract_batch(urls)
            >>> for url, article in results.items():
            ...     if article:
            ...         print(f"{url}: {article['title']}")
        """
        results = {}
        for url in urls:
            results[url] = self.extract(url)
        return results

    def get_stats(self, results: Dict[str, Optional[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Get statistics from batch extraction results.

        Args:
            results: Output from extract_batch()

        Returns:
            Statistics dictionary

        Example:
            >>> stats = extractor.get_stats(results)
            >>> print(f"Success rate: {stats['success_rate']:.1f}%")
        """
        total = len(results)
        successful = sum(1 for r in results.values() if r is not None)

        methods = {}
        for result in results.values():
            if result:
                method = result['method']
                methods[method] = methods.get(method, 0) + 1

        return {
            'total': total,
            'successful': successful,
            'failed': total - successful,
            'success_rate': (successful / total * 100) if total > 0 else 0,
            'methods': methods
        }


# Convenience function for single extraction
def extract_article(url: str) -> Optional[Dict[str, Any]]:
    """
    Quick extraction of a single article.

    Args:
        url: Article URL

    Returns:
        Article dictionary or None

    Example:
        >>> from news_extractor import extract_article
        >>> article = extract_article('https://bianet.org/...')
        >>> print(article['title'])
    """
    extractor = ArticleExtractor()
    return extractor.extract(url)


__all__ = ["ArticleExtractor", "extract_article"]
