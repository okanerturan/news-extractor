#!/usr/bin/env python3
"""Fail if a built wheel unexpectedly declares a runtime dependency."""

from __future__ import annotations

import argparse
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

    print(f"verified {wheels[0].name}: no Requires-Dist metadata")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    verify(args.directory)


if __name__ == "__main__":
    main()
