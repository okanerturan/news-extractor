from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run_quality_benchmark.py"
SPEC = importlib.util.spec_from_file_location("run_quality_benchmark", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BENCHMARK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class QualityBenchmarkTests(unittest.TestCase):
    def test_versioned_corpus_passes_every_declared_expectation(self) -> None:
        report = BENCHMARK.run_benchmark(ROOT / "benchmarks" / "corpus-v1.json")

        self.assertEqual(report["corpus_version"], "1.0.0")
        self.assertEqual(report["cases"], {"passed": 8, "total": 8})
        self.assertEqual(report["assertions"]["passed"], report["assertions"]["total"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(len(report["corpus_sha256"]), 64)

    def test_checked_in_report_is_reproducible(self) -> None:
        report = BENCHMARK.run_benchmark(ROOT / "benchmarks" / "corpus-v1.json")
        expected = (ROOT / "benchmarks" / "results" / "corpus-v1-v0.2.0.md").read_text(
            encoding="utf-8"
        )

        self.assertEqual(BENCHMARK.render_markdown(report), expected)


if __name__ == "__main__":
    unittest.main()
