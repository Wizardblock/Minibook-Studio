"""Put a finished build, the sample file, the licence and first-run notes into one folder, ready to zip.

    python packaging/stage.py --os windows|macos|linux --dist dist --out release --version 0.1.0
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPIMAGE = "MiniBook-Studio-x86_64.AppImage"
TITLES = {"windows": "MiniBook-Studio-windows", "macos": "MiniBook-Studio-macos", "linux": "MiniBook-Studio-linux"}


def stage(os_name: str, dist: Path, out: Path, version: str) -> Path:
    """Returns the staged folder (its name is the name to give the zip)."""
    if os_name not in TITLES:
        raise ValueError(f"unknown system: {os_name}")
    folder = out / f"{TITLES[os_name]}-{version}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    if os_name == "windows":
        built = dist / "MiniBookStudio"
        shutil.copytree(built, folder / "MiniBook Studio")
    elif os_name == "macos":
        built = dist / "MiniBook Studio.app"
        shutil.copytree(built, folder / built.name, symlinks=True)
    else:
        built = dist / APPIMAGE
        shutil.copy2(built, folder / APPIMAGE)
    shutil.copytree(ROOT / "samples", folder / "samples")
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    notes = (ROOT / "packaging" / f"first-run-{os_name}.txt").read_text(encoding="utf-8")
    (folder / "READ ME FIRST.txt").write_text(notes.replace("{version}", version), encoding="utf-8")
    return folder


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--os", required=True, choices=sorted(TITLES))
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--out", default="release")
    ap.add_argument("--version", required=True)
    a = ap.parse_args()
    print(stage(a.os, Path(a.dist), Path(a.out), a.version))


if __name__ == "__main__":
    main()
