#!/usr/bin/env python3
"""Fail if a built wheel unexpectedly declares a runtime dependency."""

from __future__ import annotations

import argparse
import tarfile
import zipfile
from pathlib import Path


def verify(directory: Path) -> None:
    wheels = sorted(directory.glob("*.whl"))
    source_distributions = sorted(directory.glob("*.tar.gz"))
    if len(wheels) != 1 or len(source_distributions) != 1:
        raise SystemExit("expected exactly one wheel and one source distribution")

    with zipfile.ZipFile(wheels[0]) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise SystemExit("wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")

    requirements = [line for line in metadata.splitlines() if line.startswith("Requires-Dist:")]
    if requirements:
        raise SystemExit(f"unexpected runtime requirements: {requirements}")

    required_source_evidence = {
        "benchmarks/corpus-v1.json",
        "benchmarks/results/corpus-v1-v0.2.0.md",
        "docs/TRUST_BOUNDARY.md",
        "scripts/run_quality_benchmark.py",
        "tests/fixtures/jsonld_news_article.html",
        "tests/fixtures/semantic_article.html",
    }
    with tarfile.open(source_distributions[0], "r:gz") as archive:
        names = archive.getnames()
    missing = sorted(
        expected
        for expected in required_source_evidence
        if not any(name.endswith(f"/{expected}") for name in names)
    )
    if missing:
        raise SystemExit(f"source distribution is missing reproducibility evidence: {missing}")

    print(f"verified {wheels[0].name}: no Requires-Dist metadata")
    print(f"verified {source_distributions[0].name}: benchmark and trust-boundary evidence included")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    verify(args.directory)


if __name__ == "__main__":
    main()
