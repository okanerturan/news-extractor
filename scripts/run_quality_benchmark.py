#!/usr/bin/env python3
"""Run the versioned, deterministic extraction-quality corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from news_extractor import ArticleExtractor, __version__


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "benchmarks" / "corpus-v1.json"


def load_corpus(path: Path) -> dict[str, Any]:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(corpus.get("cases"), list) or not corpus["cases"]:
        raise ValueError("corpus must contain at least one case")
    return corpus


def corpus_digest(path: Path, corpus: dict[str, Any]) -> str:
    digest = hashlib.sha256(path.read_bytes())
    for case in corpus["cases"]:
        fixture = (path.parent / case["fixture"]).resolve()
        digest.update(case["id"].encode("utf-8"))
        digest.update(fixture.read_bytes())
    return digest.hexdigest()


def record_check(checks: list[dict[str, Any]], case_id: str, name: str, expected: Any, actual: Any) -> None:
    checks.append(
        {
            "case": case_id,
            "check": name,
            "expected": expected,
            "actual": actual,
            "passed": actual == expected,
        }
    )


def run_case(corpus_path: Path, case: dict[str, Any]) -> list[dict[str, Any]]:
    fixture = (corpus_path.parent / case["fixture"]).resolve()
    html = fixture.read_text(encoding="utf-8")
    result = ArticleExtractor(min_text_length=case["min_text_length"]).extract_html(
        html,
        url=case["url"],
        final_url=case.get("final_url"),
    )
    expected = case["expected"]
    checks: list[dict[str, Any]] = []
    record_check(checks, case["id"], "extracted", expected["extracted"], result is not None)
    if result is None or not expected["extracted"]:
        return checks

    for field in ("method", "title", "authors", "date", "keywords", "categories", "image"):
        if field in expected:
            record_check(checks, case["id"], field, expected[field], result.get(field))
    for text in expected.get("text_contains", []):
        record_check(checks, case["id"], f"text contains {text!r}", True, text in result["text"])
    for text in expected.get("text_excludes", []):
        record_check(checks, case["id"], f"text excludes {text!r}", True, text not in result["text"])
    return checks


def run_benchmark(corpus_path: Path) -> dict[str, Any]:
    corpus = load_corpus(corpus_path)
    checks = [check for case in corpus["cases"] for check in run_case(corpus_path, case)]
    case_ids = [case["id"] for case in corpus["cases"]]
    passed_cases = sum(
        all(check["passed"] for check in checks if check["case"] == case_id)
        for case_id in case_ids
    )
    return {
        "benchmark": "news-extractor deterministic quality conformance",
        "package_version": __version__,
        "corpus_version": corpus["corpus_version"],
        "corpus_as_of": corpus["as_of"],
        "corpus_sha256": corpus_digest(corpus_path, corpus),
        "scope": corpus["scope"],
        "cases": {"passed": passed_cases, "total": len(case_ids)},
        "assertions": {
            "passed": sum(check["passed"] for check in checks),
            "total": len(checks),
        },
        "results": [
            {
                "id": case_id,
                "passed": all(check["passed"] for check in checks if check["case"] == case_id),
                "assertions": sum(check["case"] == case_id for check in checks),
            }
            for case_id in case_ids
        ],
        "failures": [check for check in checks if not check["passed"]],
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| `{result['id']}` | {'Pass' if result['passed'] else 'Fail'} | {result['assertions']} |"
        for result in report["results"]
    )
    return f"""# Deterministic extraction-quality benchmark

- **Package:** `news-extractor` {report['package_version']}
- **Corpus:** v{report['corpus_version']} ({report['corpus_as_of']})
- **Corpus SHA-256:** `{report['corpus_sha256']}`
- **Scope:** {report['scope']}
- **Result:** {report['cases']['passed']}/{report['cases']['total']} cases and {report['assertions']['passed']}/{report['assertions']['total']} assertions passed

| Case | Result | Assertions |
|---|---:|---:|
{rows}

This is a deterministic conformance result over synthetic, redistribution-safe fixtures. It measures the declared extraction decisions and field/content expectations in this corpus; it is not a live-publisher success rate, comparative accuracy claim, or service-level guarantee.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    parser.add_argument("--check", type=Path, help="Fail unless output exactly matches this file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = run_benchmark(args.corpus.resolve())
    output = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.check:
        expected = args.check.read_text(encoding="utf-8")
        if output != expected:
            print(f"benchmark output differs from {args.check}", file=sys.stderr)
            return 1
    sys.stdout.write(output)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
