# Research and architecture decision record

This document separates the maintained July 2026 implementation from the frozen November 2025 extraction benchmark. The old score is evidence about an old corpus and dependency graph; it is not a service-level guarantee and is not a score for the current parser.

## Current decision — July 2026

### Problem

The original two-tier implementation depended on Newspaper4k, Trafilatura, Requests, NLTK, Pillow, lxml, urllib3, and their transitive packages. GitHub reported duplicated alerts across `requirements.txt` and `poetry.lock`, including critical/high issues for which compatible patched releases were not available in the active graph.

Updating only the lockfile could not produce a clean, supportable result. Suppressing alerts would have hidden risk without changing the shipped code. The maintained extractor therefore moved to a standard-library implementation and removed both duplicate dependency manifests.

### Maintained architecture

The current `ArticleExtractor` has two parsing tiers over one safely downloaded HTML document:

1. **Structured tier** — parse `application/ld+json`, recursively find schema.org `NewsArticle`/`Article` nodes, and select the candidate with the strongest body and metadata.
2. **Semantic tier** — when structured article text is absent or too short, collect paragraph/list/blockquote content from `<article>`, `<main>`, or `role="main"` while excluding common page chrome.

The maintained method values are `json-ld` and `semantic-html`.

### Network threat model

Accepting URLs makes SSRF a first-class design concern. The built-in client:

- accepts only HTTP(S) URLs without credentials or control characters;
- validates every DNS answer and rejects a hostname if any answer is non-public;
- connects directly to the vetted address to prevent a connection-time DNS rebind;
- retains the requested hostname for TLS certificate verification and the HTTP `Host` header;
- repeats the full policy on each redirect and rejects secure-to-insecure downgrades;
- limits redirect hops, response bytes, per-request time, content type, and content encoding.

Private-network access is available only through an explicit opt-in for trusted internal use. The parser itself never executes JavaScript or publisher markup.

### Why JSON-LD first

The 2025 experiments already showed that publisher structured data was valuable, but the former conclusion rejected direct schema.org parsing because Newspaper4k exposed overlapping metadata. Once the vulnerable runtime graph was removed, JSON-LD became the smallest high-signal primary source:

- it is usually explicit about headline, body, author, date, image, keywords, and section;
- the JSON decoder and HTML parser are in the Python standard library;
- synthetic fixtures can cover it deterministically;
- the semantic fallback remains available for incomplete or malformed structured data.

This design trades the broad heuristics of large third-party parser stacks for a smaller, auditable surface. JavaScript-only and unusually marked-up sites may produce lower recall; that tradeoff is recorded rather than hidden.

### Deterministic evidence

The unit suite is network-free and covers:

- Turkish Unicode through structured and semantic extraction;
- nested `@graph` selection and flexible metadata shapes;
- malformed/short structured data fallback;
- page-chrome exclusion and minimum-length rejection;
- public batch/statistics and backlog APIs;
- CLI success/failure/configuration behavior;
- invalid schemes, credentials, control characters, and missing hosts;
- private, loopback, link-local, and mixed DNS rejection;
- explicit private-network opt-in;
- redirect revalidation, downgrade rejection, and redirect bounds;
- HTML-only content types, declared charsets, response byte bounds, and vetted address retention.

CI installs with `--no-deps`, runs this suite on the minimum and modern Python versions, builds both distribution formats, installs the wheel into a clean virtual environment, and verifies that wheel metadata has no `Requires-Dist` entry.

## Legacy experiment — November 2025

### Frozen result

The retired Newspaper4k → Trafilatura prototype recorded:

| Metric | November 2025 snapshot |
|---|---:|
| Fixed corpus | 6 URLs |
| Overall successes | 5/6 (83.3%) |
| Newspaper4k successes | 3/6 (50%) |
| Trafilatura rescues | 2/6 (33%) |
| Both failed | 1/6 (gallery) |
| Mean observed time | 0.55 seconds |

Those values came from six publisher URLs at a point in time. URLs may now be removed, redirected, bot-blocked, paywalled, or structurally different. The result was never a publisher-wide benchmark or SLA.

### Approaches explored

The 2025 research compared or prototyped:

- Newspaper4k;
- Trafilatura 2.0;
- schema.org extraction via Extruct;
- Beautiful Soup heuristics;
- Readability-style extraction;
- Crawl4AI/browser automation;
- LLM post-processing;
- go-Trafilatura as an unimplemented alternative.

Archived reports include independent F1 figures and qualitative observations, but those external benchmark numbers were not reproduced by this repository. They should be read as cited historical context, not current project measurements.

### Why the legacy implementation was retired

The old combination was attractive for recall on its six-URL snapshot, but its runtime graph became unsuitable for a small portfolio library:

- multiple transitive advisories lacked an immediately adoptable patched release;
- the same graph was represented twice, multiplying alert noise;
- deterministic tests required third-party packages even when testing local fixtures;
- general HTTP clients did not by themselves define the URL/redirect/DNS policy needed for untrusted inputs;
- claims such as “production-ready,” “all edge cases,” and permanent sub-second behavior exceeded the evidence.

The current design removes those claims and preserves the old measurements only as a dated decision record.

## Live validation policy

`tests/validation/validate_live.py` can revisit the legacy URLs or additional URLs using the current implementation. Its output must be labeled with the execution date and interpreted manually:

- a removed URL is publisher drift, not automatically a parser defect;
- a gallery remains outside the article contract;
- a bot challenge may yield HTML but still require a manual content review;
- success means the minimum content contract was met, not that every sentence is perfect.

Live results do not run in CI and must not replace the deterministic security/parser suite.

## Archive map

Selected legacy material is frozen under `archive/legacy_research/`:

- `analysis/` — comparison narratives and recorded outputs;
- `docs/` — pre-maintenance notes and source inventories;
- `experiments/` — manual parser prototypes and result JSON;
- `production/` — obsolete discovery prototypes;
- `tests/research_archive/` — one-off benchmark and debugging scripts.

Archived Python files retain their original imports for historical readability. They are not package modules, maintained scripts, tests, or dependency declarations and should not be executed in the current environment.

## Next useful research

1. Build a redistribution-safe synthetic fixture set for additional Turkish publisher patterns.
2. Add explicit precision/recall annotations before claiming comparative quality.
3. Measure current live behavior on a versioned, legally reviewable URL-only corpus.
4. Add per-domain adapters only when repeated evidence justifies the maintenance cost.
5. Continue treating network security, extraction quality, and publisher availability as separate metrics.
