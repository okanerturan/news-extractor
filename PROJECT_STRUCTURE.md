# Project Structure

## Maintained Surface

### Source (`src/news_extractor/`)
- `article_extractor.py` – Newspaper4k primary + Trafilatura fallback implementation; its 5/6 result and 0.55s average are a dated November 2025 snapshot.
- `cli.py` – Powers the `news-extractor` executable and `python -m news_extractor.cli` flow.
- `__init__.py` – Exposes `ArticleExtractor` and `extract_article` for downstream imports.

### Packaging & Tooling
- `pyproject.toml` / `poetry.lock` – Poetry-managed metadata, lockfile, and CLI entry point.
- `requirements.txt` – Exported via `poetry export` for environments that cannot use Poetry directly (install with `pip install -r requirements.txt && pip install -e .`).

### Documentation
- `README.md` – Operational guide, workflows, API examples.
- `RESEARCH.md` – Deep dive on experimentation and rationale.

### Examples & Validation
- `examples/batch_extraction.py` – Ready-made batch usage script importing the packaged module.
- `tests/unit/` – Deterministic package, fallback, backlog, and output tests run in GitHub Actions.
- `tests/validation/test_ultimate_combo.py` – Opt-in live six-URL snapshot. Galleries remain out of scope by design.

## Operational Workflow
1. **Bootstrap** – `poetry install`.
2. **Integrate** – Import `ArticleExtractor` (Python jobs) or call the `news-extractor` CLI inside larger workflows/microservices.
3. **Verify** – Run `poetry run pytest tests/unit` for the deterministic gate and build the package.
4. **Validate live behavior** – Run `poetry run python tests/validation/test_ultimate_combo.py` when refreshing network-dependent evidence. Report publisher drift separately from code failures.
5. **Monitor** – Track success rate and fallback ratio as documented in `README.md`; the recorded 83.3% is a dated six-URL snapshot, not an SLA.

## Archive (Historical Research) 📦
All prior experimentation is frozen under `archive/legacy_research/`:

| Path | Contents / Notes |
|------|------------------|
| `analysis/` | Narrative reports (`analysis_*`, `newspaper4k_*`, etc.) |
| `docs/` | Earlier documentation set (pre-Nov 2025) |
| `experiments/` | Manual scrapers, Crawl4AI trials, LLM hybrids |
| `production/` | Obsolete Trafilatura-only implementation |
| `scripts/` | Diagnostic helpers (e.g., detailed link discovery) |
| `tests/research_archive/` | Full historical test harness (Crawl4AI, Trafilatura 2.0, etc.) |

These assets are **deprecated**—do not import or execute them inside production flows. They are maintained as evidence for decisions captured in `RESEARCH.md`.

## Repository Map

```
news-extractor/
├── README.md / RESEARCH.md
├── .github/workflows/test.yml
├── LICENSE
├── pyproject.toml
├── requirements.txt
├── src/
│   └── news_extractor/
│       ├── __init__.py
│       ├── article_extractor.py
│       └── cli.py
├── tests/
│   ├── unit/
│   └── validation/test_ultimate_combo.py
├── examples/batch_extraction.py
└── archive/
    └── legacy_research/
        ├── analysis/
        ├── docs/
        ├── experiments/
        ├── production/
        ├── scripts/
        └── tests/research_archive/
```

**Last Updated:** July 2026
**Status:** Maintained research-backed library; deterministic CI is required, while live-site evidence remains opt-in and dated.
