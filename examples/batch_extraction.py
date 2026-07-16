#!/usr/bin/env python3
"""
Example: Batch article extraction with statistics

Demonstrates:
- Extracting multiple URLs
- Getting extraction statistics
- Handling results
"""

from news_extractor import ArticleExtractor
from news_extractor.article_extractor import _safe_terminal_text, _safe_url_for_log

# Example Turkish news URLs
urls = [
    'https://bianet.org/haber/erdogan-ozele-tazminat-davasi-acti-313281',
    'https://t24.com.tr/haber/victor-osimhen-sampiyonlar-ligi-nde-haftanin-11-ine-secildi,1274139',
    'https://www.odatv.com/guncel/akran-zorbaligi-davasinda-karar-cikti-120122351',
]

print("Turkish News Article Extractor - Batch Example")
print("=" * 80)
print()

# Create the dependency-free extractor. Remote destinations are restricted to
# public HTTP(S) addresses unless private-network access is explicitly enabled.
extractor = ArticleExtractor()

# Extract all articles
print(f"Extracting {len(urls)} articles...")
print()

results = extractor.extract_batch(urls)

# Display results
for url, article in results.items():
    print("-" * 80)
    if article:
        print(f"✅ {_safe_url_for_log(url)}")
        print(f"   Method: {_safe_terminal_text(article['method'])}")
        print(f"   Title: {_safe_terminal_text(article['title'])}")
        authors = ", ".join(_safe_terminal_text(value) for value in article["authors"])
        keywords = ", ".join(
            _safe_terminal_text(value) for value in article["keywords"][:3]
        )
        print(f"   Authors: {authors or 'N/A'}")
        print(f"   Keywords: {keywords or 'N/A'}...")
        print(f"   Text: {article['text_length']} chars")
    else:
        print(f"❌ {_safe_url_for_log(url)}")
        print(f"   Failed to extract")
    print()

# Get statistics
stats = extractor.get_stats(results)

print("=" * 80)
print("STATISTICS")
print("=" * 80)
print(f"Total URLs: {stats['total']}")
print(f"Successful: {stats['successful']}")
print(f"Failed: {stats['failed']}")
print(f"Success rate: {stats['success_rate']:.1f}%")
print()
print(f"Methods used:")
for method, count in stats['methods'].items():
    print(f"  - {method}: {count}")
print("=" * 80)
