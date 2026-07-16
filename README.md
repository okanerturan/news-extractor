# News Extractor (Turkish Article Extractor)

[![Test](https://github.com/okturan/news-extractor/actions/workflows/test.yml/badge.svg)](https://github.com/okturan/news-extractor/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

Python library and CLI for extracting structured Turkish news articles with a Newspaper4k primary path and a Trafilatura fallback. It also includes SQLite backlog reprocessing and JSONL inspection tools for evaluating extraction quality in a larger collection workflow.

## Project status and evidence

| Surface | Current evidence |
|---|---|
| Deterministic behavior | Offline unit tests cover primary extraction, fallback, failure handling, statistics, SQLite pagination, re-extraction, and JSONL output on Python 3.10 and 3.12 |
| Packaging | Poetry-managed source package and CLI; CI builds wheel and source distribution artifacts |
| Live validation | An opt-in six-URL snapshot recorded 5/6 successes (83.3%) in November 2025 |
| Scope | Research-backed extraction library; not a hosted service or guaranteed publisher-wide SLA |

News pages and upstream parsers change. The recorded success rate and timing below describe that fixed research snapshot, not a permanent production guarantee.

## Quick Start

```python
from news_extractor import extract_article

# Extract a single article
article = extract_article('https://bianet.org/haber/...')

print(article['title'])
print(article['text'])
print(article['keywords'])
```

## Setup

```bash
poetry install
```

Run tools through Poetry so the managed environment stays consistent, e.g. `poetry run news-extractor https://...` or `poetry run python tests/validation/test_ultimate_combo.py`.

## Features

- Two-tier Newspaper4k → Trafilatura extraction.
- Structured title, text, author, date, keyword, image, and method metadata.
- Configurable minimum text length and request timeout.
- Batch statistics plus SQLite backlog reprocessing and JSONL output.
- Offline unit tests in CI and a separate opt-in live-site validation script.

## Installation

- **Recommended:** `poetry install` (handles dependencies, scripts, lockfile).
- **Fallback:** `pip install -r requirements.txt && pip install -e .` if Poetry is unavailable (requires PEP 517 support).

## Usage

### Single Article

```python
from news_extractor import ArticleExtractor

extractor = ArticleExtractor()
article = extractor.extract('https://bianet.org/...')

if article:
    print(f"Title: {article['title']}")
    print(f"Text: {article['text']}")
    print(f"Authors: {article['authors']}")
    print(f"Date: {article['date']}")
    print(f"Keywords: {article['keywords']}")
    print(f"Method: {article['method']}")  # 'newspaper4k' or 'trafilatura'
```

### Batch Extraction

```python
urls = [
    'https://bianet.org/haber/...',
    'https://t24.com.tr/haber/...',
    'https://www.odatv.com/...'
]

results = extractor.extract_batch(urls)
stats = extractor.get_stats(results)

print(f"Success rate: {stats['success_rate']:.1f}%")
print(f"Methods used: {stats['methods']}")
```

### Command Line

```bash
# from the Poetry environment
poetry run news-extractor 'https://bianet.org/haber/...'
# or
python -m news_extractor.cli 'https://bianet.org/haber/...'
```

## How It Works

### Two-Tier Strategy

The extractor uses a fallback approach for maximum reliability:

1. **Primary: Newspaper4k** (fast, clean extraction)
   - Handles 50% of URLs
   - 0.5s average
   - Clean article-only text

2. **Fallback: Trafilatura** (robust, handles edge cases)
   - Rescues 33% of failed extractions
   - Handles user-agent blocking
   - Extracts when Newspaper4k returns empty text

### Supported Sites

Tested and verified on:
- ✅ Bianet
- ✅ T24
- ✅ Hürriyet
- ✅ OdaTV
- ✅ Sözcü
- ✅ Cumhuriyet
- ✅ And more...

### Recorded validation snapshot

The repository's November 2025 research run used six fixed article URLs:

Based on comprehensive testing:

| Metric | Value |
|--------|-------|
| Success rate | 83.3% (5/6 URLs) |
| Average time | 0.55s |
| Primary success | 50% |
| Fallback success | 33% |
| Both failed | 17% |

## Response Format

```python
{
    'url': 'https://...',
    'title': 'Article title',
    'text': 'Full article text (clean, no ads)',
    'authors': ['Author Name'],
    'date': '2025-11-06T16:31:00+03:00',  # ISO format
    'keywords': ['keyword1', 'keyword2'],
    'description': 'Meta description',
    'image': 'https://...image.jpg',
    'categories': 'HABER',  # Trafilatura only
    'method': 'newspaper4k',  # or 'trafilatura'
    'text_length': 1027,
    'extracted_at': '2025-11-07T...'
}
```

## Edge Cases

### What Works

✅ **Paywalled content** - Extracts available preview text
✅ **Embedded social media** - Filters out Twitter/Instagram embeds
✅ **Video articles** - Extracts text around videos
✅ **User-agent blocking** - Trafilatura bypasses with custom UA
✅ **Empty extractions** - Automatic fallback to Trafilatura

### What Doesn't Work

❌ **Photo galleries** (e.g., `/galeri/...`)
❌ **News listing pages** (e.g., `/haberleri/...`)
❌ **Live blogs** - Extracts snapshot only

These are expected - the tool is designed for article URLs.

## Java/Spring Boot Integration

For Java applications, deploy as a microservice:

```python
# microservice.py (FastAPI)
from fastapi import FastAPI
from news_extractor import extract_article

app = FastAPI()

@app.get("/extract")
def extract(url: str):
    return extract_article(url)
```

```java
// Java client
RestTemplate rest = new RestTemplate();
String url = "http://localhost:8000/extract?url=" + articleUrl;
Article article = rest.getForObject(url, Article.class);
```

## Why This Solution?

### Alternatives Tested

We evaluated state-of-the-art alternatives:

| Tool | Success Rate | Speed | Issues |
|------|-------------|-------|---------|
| **Newspaper4k + Trafilatura** | **83%** | **0.55s** | ✅ Best overall |
| Newspaper4k alone | 50% | 0.53s | ⚠️ Empty extractions |
| Trafilatura 2.0 | 73% | 0.6s | ⚠️ User-agent blocking |
| Crawl4AI | 50% | 4-60s | ❌ Timeouts, too slow |
| go-Trafilatura | Not tested | N/A | Requires Go runtime |

### Benchmark Results

From independent evaluation (Zyte/Scrapinghub):

- **go-Trafilatura**: F1 0.960 (highest quality)
- **Trafilatura 2.0**: F1 0.958
- **Newspaper4k**: F1 0.949 (our choice)

Newspaper4k remains the primary path because it produced clean output quickly on the supported URLs in the recorded snapshot and stays Python-native. Trafilatura handles short or failed primary extractions.

## Research Summary

### What We Tested

1. ✅ **Newspaper4k** - Fast, clean primary extraction on supported snapshot URLs
2. ✅ **Trafilatura 2.0** - User-agent blocking on Bianet
3. ✅ **Crawl4AI** - LLM-powered, but 60s timeouts
4. ✅ **LLM Hybrid** - Pre-clean + Claude, but Trafilatura JSON already structured
5. ✅ **Extruct** - Schema.org metadata, but Newspaper4k has keywords
6. ❌ **Dolphin** - Document OCR, not for web scraping

### Key Insights

1. **Newspaper4k `meta_keywords`** - Already extracts tags (no extruct needed!)
2. **Trafilatura JSON** - Already structured (no LLM needed!)
3. **User-agent bypass** - Fixes Bianet blocking
4. **Fallback improved the recorded snapshot** - 5/6 URLs succeeded with two tiers versus 3/6 with the primary alone

## Maintenance

### Dependency status

Runtime and development versions are pinned in `poetry.lock`. Refresh the lockfile deliberately and rerun both offline CI and the live validation snapshot before adopting upstream parser changes.

### Monitoring Recommendations

Track these metrics in production:

```python
# Monitor extraction success
stats = extractor.get_stats(results)
if stats['success_rate'] < 80:
    alert("Success rate dropped below 80%")

# Monitor method usage
if stats['methods']['trafilatura'] > 50:
    alert("High fallback usage - investigate")
```

### When to Update

Update if:
- Success rate drops below 80%
- Major news site redesigns
- Library security updates

## Project Structure

```
news-extractor/
├── .github/workflows/test.yml # Python 3.10/3.12 unit + package build CI
├── LICENSE                     # MIT license for original project code/docs
├── pyproject.toml              # Packaging + CLI entry point
├── requirements.txt            # `-e .` for local dev install
├── README.md / RESEARCH.md     # Product + research docs
├── src/news_extractor/
│   ├── __init__.py             # Exposes ArticleExtractor + helpers
│   ├── article_extractor.py    # Production module ⭐
│   └── cli.py                  # `news-extractor` / `python -m news_extractor.cli`
├── tests/
│   ├── unit/                   # Deterministic, network-free CI coverage
│   └── validation/
│       └── test_ultimate_combo.py  # Opt-in six-URL live snapshot
├── examples/
│   └── batch_extraction.py     # Batch usage sample
└── archive/
    └── legacy_research/        # Deprecated research assets
        ├── analysis/           # Historic findings
        ├── docs/               # Previous documentation set
        ├── experiments/        # Manual scrapers, prototypes
        ├── production/         # Old Trafilatura-only impl
        └── tests/              # Research-only test harnesses
```

## Operational Flow

1. **Bootstrap** – run `poetry install` (Poetry spawns the virtualenv automatically).
2. **Integrate** – import `ArticleExtractor` or call `poetry run news-extractor …` inside your workflow/job.
3. **Verify deterministic behavior** – run `poetry run pytest tests/unit`; CI executes this on Python 3.10 and 3.12 and builds distribution artifacts.
4. **Refresh live evidence deliberately** – run `poetry run python tests/validation/test_ultimate_combo.py` when network-dependent behavior must be re-evaluated. Treat URL removals, publisher redesigns, and galleries separately from code regressions.
5. **Research reference** – anything under `archive/legacy_research` is frozen context only. Do not import from there in production pipelines.

## Backlog Inspection Tools

Coordinate with the Java collector via these helpers:

1. **re-extract backlog rows**
   ```bash
   poetry run python examples/scrape_news_gatherer_backlog.py \
     --db ../news-gatherer/output/news-gatherer.db \
     --limit 50 --format json > backlog.jsonl
   ```
   - Reads from the `articles` table, runs `news_extractor.ArticleExtractor` for each URL, and emits JSON/pretty payloads with error notes.

2. **inspect JSONL output**
   ```bash
   poetry run python examples/view_jsonl.py backlog.jsonl --limit 10
   ```
   - Provides quick previews (domain, title, method, truncated text). Handy for CLI-based QA.

3. **visualize in browser**
   - Open `examples/backlog_viewer.html` and load the `backlog.jsonl` file to browse articles interactively (search/filter, expand text, see extraction metadata).

For automation, import `news_extractor.backlog` and call `load_records()` / `reextract()` directly instead of invoking the CLI script.

Keep `backlog.jsonl` under version control only when sharing curated samples; otherwise treat it as local output.

## Contributing

This is a research-backed library. Key extraction decisions are documented in `RESEARCH.md`; behavior changes should include deterministic tests and, when relevant, a separately reported live validation run.

## License

Original source code and documentation are available under the [MIT License](./LICENSE). Third-party dependencies retain their own licenses. Captured publisher content, URLs, and research fixtures under `archive/legacy_research/` remain subject to their original owners' rights and are not relicensed by this repository.

## Support

For issues with specific sites, provide:
- URL
- Expected vs actual output
- Error messages (if any)

## Credits

Built after extensive testing of:
- Newspaper4k by Andrei Paraschiv
- Trafilatura by Adrien Barbaresi
- Research validated by external experts
