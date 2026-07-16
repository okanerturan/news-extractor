# Project structure

## Maintained surface

```text
news-extractor/
├── .github/
│   ├── dependabot.yml
│   └── workflows/test.yml
├── examples/
│   ├── batch_extraction.py
│   ├── scrape_news_gatherer_backlog.py
│   ├── view_jsonl.py
│   └── backlog_viewer.html
├── scripts/
│   └── verify_distribution.py
├── src/news_extractor/
│   ├── __init__.py
│   ├── article_extractor.py
│   ├── backlog.py
│   └── cli.py
├── tests/
│   ├── fixtures/
│   │   ├── jsonld_news_article.html
│   │   └── semantic_article.html
│   ├── unit/
│   │   ├── test_article_extractor.py
│   │   ├── test_backlog.py
│   │   ├── test_backlog_viewer.py
│   │   ├── test_cli.py
│   │   ├── test_http_client.py
│   │   └── test_validation_output.py
│   └── validation/
│       └── validate_live.py
├── archive/legacy_research/
├── AGENTS.md
├── LICENSE
├── README.md
├── RESEARCH.md
├── SECURITY.md
└── pyproject.toml
```

## Responsibilities

- `article_extractor.py` owns the safe HTTP boundary, JSON-LD selection, semantic HTML fallback, batch API, and statistics API.
- `cli.py` exposes the package as `news-extractor` and makes network bounds configurable.
- `backlog.py` owns the SQLite/JSONL integration used by the collector bridge.
- `tests/unit/` is deterministic, uses only the standard library, and is the required CI gate.
- The backlog-viewer verifier guards DOM text rendering and the HTTP(S)-only link policy without adding a browser-test dependency.
- `tests/fixtures/` contains synthetic Turkish documents; it does not contain copied publisher articles.
- `tests/validation/validate_live.py` is an opt-in publisher-drift report, never a deterministic CI assertion.
- `scripts/verify_distribution.py` verifies the wheel declares no runtime requirements.

## Packaging authority

`pyproject.toml` is the single package manifest. The project intentionally has no `requirements.txt`, Poetry lockfile, runtime dependency list, or test dependency list. CI installs the package with `--no-deps`, runs `pip check`, and inspects built wheel metadata.

## Historical boundary

`archive/legacy_research/` freezes the November 2025 Newspaper4k, Trafilatura, Crawl4AI, Beautiful Soup, and Extruct experiments. Archived `.py` files are readable research artifacts, not supported scripts:

- they are outside the `src` package;
- they are outside unit-test discovery and compilation checks;
- their former third-party dependencies are intentionally not declared;
- they must not be imported by maintained code.

The tracked root `backlog.jsonl` is also a dated November 2025 output sample. Its method values describe the retired implementation.

## Standard workflow

1. Install: `python -m pip install --no-deps --editable .`
2. Test: `python -m unittest discover -s tests/unit -v`
3. Compile: `python -m compileall -q src tests/unit tests/validation examples`
4. Build: `python -m build`
5. Inspect: `python scripts/verify_distribution.py dist`
6. Optionally validate publishers: `python tests/validation/validate_live.py`

**Status:** maintained dependency-free library; last structure refresh July 2026.
