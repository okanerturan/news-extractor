# Deterministic extraction-quality benchmark

- **Package:** `news-extractor` 0.2.0
- **Corpus:** v1.0.0 (2026-07-17)
- **Corpus SHA-256:** `d38499d92a840e4ea9ea5ed21a7d5ae4c0f72c51e8050ccf2e0dcdee38410627`
- **Scope:** Redistribution-safe deterministic Turkish article-extraction conformance corpus
- **Result:** 8/8 cases and 55/55 assertions passed

| Case | Result | Assertions |
|---|---:|---:|
| `jsonld-rich-turkish` | Pass | 9 |
| `semantic-chrome-exclusion` | Pass | 11 |
| `jsonld-graph-selection` | Pass | 8 |
| `semantic-role-main` | Pass | 9 |
| `incomplete-jsonld-fallback` | Pass | 6 |
| `malformed-jsonld-fallback` | Pass | 6 |
| `relative-image-resolution` | Pass | 5 |
| `navigation-only-rejection` | Pass | 1 |

This is a deterministic conformance result over synthetic, redistribution-safe fixtures. It measures the declared extraction decisions and field/content expectations in this corpus; it is not a live-publisher success rate, comparative accuracy claim, or service-level guarantee.
