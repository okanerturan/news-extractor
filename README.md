# News Extractor

[![Test](https://github.com/okturan/news-extractor/actions/workflows/test.yml/badge.svg)](https://github.com/okturan/news-extractor/actions/workflows/test.yml)
[![Python 3.10–3.14](https://img.shields.io/badge/Python-3.10%E2%80%933.14-3776AB?logo=python&logoColor=white)](./pyproject.toml)
[![Runtime dependencies: 0](https://img.shields.io/badge/runtime%20dependencies-0-2ea44f)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](./LICENSE)

A dependency-free Python library and CLI for extracting structured Turkish news articles. It prefers schema.org `NewsArticle`/`Article` JSON-LD, falls back to semantic HTML, and treats outbound URL fetching as a security boundary.

This is a library and research project, not a hosted scraping service. The useful proof is its installable package, deterministic fixtures, security-focused transport tests, and opt-in live validation—not a screenshot or demo page.

## What it demonstrates

| Surface | Current evidence |
|---|---|
| Extraction | JSON-LD-first and semantic `<article>`/`<main>` fallback paths |
| Security | Version-stable public-address policy, recursive transition-address checks, address-pinned sockets, TLS hostname verification, and one absolute fetch deadline |
| Dependency health | No runtime or test dependencies; built wheel is checked for unexpected `Requires-Dist` metadata |
| Compatibility | `ArticleExtractor`, `extract_article`, batch/stats, CLI, and backlog helpers remain available |
| Unicode | Deterministic Turkish fixtures cover `İ`, `ı`, `ş`, `ğ`, `ü`, `ö`, and `ç` end to end |
| Automation | Pinned, least-privilege CI across Python 3.10, 3.12, and 3.14 plus package installation smoke tests |

## Install

The project requires Python 3.10 or newer and has no runtime dependencies.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable .
```

## Quick start

```python
from news_extractor import ArticleExtractor

extractor = ArticleExtractor()
article = extractor.extract("https://example.com/news/article")

if article:
    print(article["title"])
    print(article["method"])       # "json-ld" or "semantic-html"
    print(article["text"][:300])
```

The convenience function is still available:

```python
from news_extractor import extract_article

article = extract_article("https://example.com/news/article")
```

For deterministic processing of HTML you already possess, bypass the network entirely:

```python
from news_extractor import ArticleExtractor

html = """
<article>
  <h1>Türkçe başlık</h1>
  <p>Yeterince uzun haber metni burada yer alır...</p>
</article>
"""

article = ArticleExtractor(min_text_length=30).extract_html(
    html,
    url="https://publisher.example/article",
)
```

## CLI

```bash
news-extractor 'https://example.com/news/article'
news-extractor --format json --timeout 8 --max-bytes 1000000 'https://example.com/news/article'
python -m news_extractor.cli --help
```

The CLI exits `0` only when every requested URL succeeds, `1` when any extraction fails, and `2` for invalid configuration.

`--timeout` is one absolute wall-clock budget for the complete fetch. DNS resolution, every redirect and address attempt, TCP/TLS connection, request transmission, response headers, and response body all consume the same budget; a slow byte drip does not reset it.

## Extraction pipeline

1. Validate an `http`/`https` URL and reject embedded credentials, port zero, and invalid ports.
2. Resolve the hostname under the fetch deadline and a process-wide eight-worker capacity bound; apply an explicit public-address policy to every answer and recursively validate IPv4 destinations embedded in transition formats.
3. Connect the socket to the vetted address while preserving the original hostname for TLS verification and the `Host` header.
4. Repeat validation for every redirect, share the original deadline across the full chain, and reject HTTPS-to-HTTP downgrades.
5. Require HTML/XHTML, identity encoding, a bounded response body, a bounded redirect count, and an absolute deadline that cannot be extended by slow headers or body bytes.
6. Parse schema.org JSON-LD and select the strongest `NewsArticle` or `Article` candidate.
7. If structured article text is absent or too short, collect paragraph and blockquote content from semantic `<article>`/`<main>` regions while excluding navigation, forms, scripts, styles, sidebars, and footers.

The parser returns `None` when the fetch or extraction fails, matching the original public API. Operational diagnostics are emitted through Python logging.

## Response shape

```python
{
    "url": "https://publisher.example/start",
    "final_url": "https://publisher.example/article",
    "title": "Article title",
    "text": "Article body...",
    "authors": ["Author Name"],
    "date": "2026-07-16T09:30:00+03:00",
    "keywords": ["keyword"],
    "description": "Article summary",
    "image": "https://publisher.example/image.jpg",
    "categories": ["Technology"],
    "language": "tr",
    "method": "json-ld",  # or "semantic-html"
    "text_length": 1234,
    "extracted_at": "2026-07-16T07:00:00+00:00",
}
```

Sites expose inconsistent metadata, so `title`, `date`, `description`, `image`, and `categories` may be `None`; authors and keywords are lists. Text and metadata are untrusted publisher content and must be escaped for their destination.

## Network security defaults

The default client uses explicit IPv4 and IPv6 network tables rather than Python's release-dependent `ipaddress.is_global` classification. It blocks private, loopback, link-local, shared, documentation, benchmark, reserved, site-local, multicast, unspecified, and deprecated transition ranges—including mixed DNS answers where only one answer is denied. IPv4-mapped, 6to4, Teredo, well-known NAT64, and both ISATAP interface-ID forms are recursively checked so they cannot conceal a denied IPv4 destination. The globally reachable `192.0.0.9` and `192.0.0.10` anycast exceptions remain allowed.

Synchronous resolver calls run behind one process-wide capacity gate shared by all clients. At most eight DNS worker threads can be outstanding; waiting for capacity consumes the same absolute fetch deadline, and saturation fails closed without creating another worker.

For a trusted internal deployment only, opt in explicitly:

```python
extractor = ArticleExtractor(allow_private_networks=True)
```

```bash
news-extractor --allow-private-network 'http://intranet.example/article'
```

Do not enable that option for user-supplied URLs. See [SECURITY.md](./SECURITY.md) for the threat model and reporting route.

Human-readable diagnostics redact URL credentials, queries, and fragments and strip terminal control sequences from publisher text. The local backlog viewer renders untrusted JSONL scalars through DOM text nodes and links only validated HTTP(S) URLs.

## Batch and statistics API

```python
extractor = ArticleExtractor()
results = extractor.extract_batch(
    [
        "https://publisher.example/article-1",
        "https://publisher.example/article-2",
    ]
)
stats = extractor.get_stats(results)

print(stats)
# {
#   "total": 2,
#   "successful": 1,
#   "failed": 1,
#   "success_rate": 50.0,
#   "methods": {"json-ld": 1},
# }
```

## SQLite backlog workflow

The `news_extractor.backlog` module keeps the original collector bridge:

- `load_records()` reads paginated rows from a News Gatherer SQLite database.
- `reextract()` applies an `ArticleExtractor` while isolating row-level failures.
- `summarize()` calculates success totals.
- `write_jsonl()` emits UTF-8 JSONL.

```bash
python examples/scrape_news_gatherer_backlog.py \
  --db ../news-gatherer/output/news-gatherer.db \
  --limit 50 \
  --format json > /tmp/news-extractor-backlog.jsonl

python examples/view_jsonl.py --file /tmp/news-extractor-backlog.jsonl --limit 10
```

Open `examples/backlog_viewer.html` locally for a searchable visual inspection of the tracked root `backlog.jsonl`, which the page loads directly. That file is a November 2025 legacy output sample; its old `newspaper4k`/`trafilatura` method labels are historical data, not current runtime values.

## Verification

The required suite is deterministic and network-free:

```bash
python -m pip install --no-deps --editable .
python -m pip check
python -m unittest discover -s tests/unit -v
python -m compileall -q src tests/unit tests/validation examples
```

Build and inspect distributions:

```bash
python -m pip install build==1.3.0
python -m build
python scripts/verify_distribution.py dist
```

Refresh live publisher evidence separately:

```bash
python tests/validation/validate_live.py
python tests/validation/validate_live.py --json
python tests/validation/validate_live.py --skip-legacy --url 'https://publisher.example/article'
```

The live script is deliberately not a CI gate. Publisher removals, bot controls, paywalls, redesigns, and out-of-scope galleries are external drift that require manual classification.

## Scope and limitations

- The heuristic fallback is intentionally smaller than a full browser/readability engine.
- JavaScript-rendered-only bodies are not executed.
- Paywalls yield only content present in the downloaded HTML.
- Galleries, listing pages, live blogs, and multi-article feeds are outside the core article contract.
- Metadata quality depends on publisher markup.
- Address validation reduces SSRF risk but does not make arbitrary crawling legally or operationally appropriate; respect publisher terms, robots guidance, copyright, rate limits, and privacy obligations.

## Historical research

The November 2025 experiment measured a Newspaper4k → Trafilatura combination at 5/6 URLs in a fixed corpus. That implementation was retired in July 2026 because its transitive dependency graph included multiple critical/high advisories without available compatible patches. The number remains useful as dated research evidence, not as a claim about the current stdlib implementation.

See [RESEARCH.md](./RESEARCH.md) for the decision record and `archive/legacy_research/` for frozen reports and prototypes. Archived Python files are source artifacts only; they are not part of the package, test discovery, or supported execution surface.

## License

Original project source and documentation are licensed under [MIT](./LICENSE). Publisher URLs, captured content, and legacy research samples remain subject to their original owners' rights and are not relicensed by this repository.
