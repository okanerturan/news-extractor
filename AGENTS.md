# Repository guidelines

## Maintained boundaries

- `src/news_extractor/` is the only production package.
- `tests/unit/` is deterministic and standard-library-only; it is the required CI gate.
- `tests/fixtures/` contains synthetic, redistribution-safe Turkish HTML.
- `tests/validation/validate_live.py` is opt-in and network-dependent. Never convert publisher availability into a required CI assertion.
- `archive/legacy_research/` is frozen historical evidence. Do not import, execute, compile, modernize, or depend on its scripts.
- `backlog.jsonl` is a dated November 2025 output sample; its old method labels are not current API values.

## Commands

```bash
python -m pip install --no-deps --editable .
python -m pip check
python -m unittest discover -s tests/unit -v
python -m compileall -q src tests/unit tests/validation examples
python -m build
python scripts/verify_distribution.py dist
news-extractor --help
```

Run `python tests/validation/validate_live.py` only when explicitly refreshing live evidence. Record publisher drift separately from code failures.

## Code and security expectations

- Support Python 3.10+ and use type hints plus `from __future__ import annotations`.
- Keep runtime and deterministic tests dependency-free unless a documented architecture decision proves a new package is necessary.
- Preserve `ArticleExtractor`, `extract_article`, `extract_batch`, `get_stats`, CLI, and backlog contracts.
- Treat every remote URL as untrusted. Any network change needs tests for schemes, credentials, address classes, mixed DNS, redirect targets, TLS downgrades, response types, sizes, and timeouts.
- DNS validation must remain connected to the actual socket address; do not replace it with a check followed by a second uncontrolled resolver call.
- Private-network access must remain an explicit, documented opt-in.
- Escape or otherwise safely handle extracted publisher content at its eventual destination.

## Pull requests

Use a focused commit and keep the PR in draft until independent review. Include exact test/build/package commands and distinguish deterministic evidence from any live URL sample. Do not claim a success rate without a dated, versioned corpus and a stated denominator.
