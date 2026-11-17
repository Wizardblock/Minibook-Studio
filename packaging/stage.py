"""Packaging helpers.

    python packaging/stage.py --os macos --dist dist --out release --version 0.1.0
        Puts the Mac app, the sample file, the licence and notes into the folder that becomes the disk image.

    python packaging/stage.py bundle --downloads downloads --out bundles --version 0.1.0
        Makes one download per system, each holding the installer(s), the README, the sample CSV and the
        licence: MiniBook-Studio-<version>-windows.zip, -macos.zip and -linux.tar.gz.
"""
from __future__ import annotations

import argparse
import shutil
import stat
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# what each system's download holds: the installer files (glob patterns inside the downloads folder), the archive kind
BUNDLES = {
    "windows": (["MiniBook-Studio-Setup-{v}.exe"], "zip"),
    "macos": (["MiniBook-Studio-{v}-macos-arm64.dmg"], "zip"),
    "linux": (["MiniBook-Studio-{v}-x86_64.AppImage", "minibook-studio_{v}_all.deb"], "tar.gz"),
}


def stage(os_name: str, dist: Path, out: Path, version: str) -> Path:
    """The folder that becomes the Mac disk image: the app, an Applications link, samples, licence and notes."""
    if os_name != "macos":
        raise ValueError(f"only the Mac disk image is staged; unknown system: {os_name}")
    folder = out / f"MiniBook-Studio-macos-{version}"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    built = dist / "MiniBook Studio.app"
    shutil.copytree(built, folder / built.name, symlinks=True)
    (folder / "Applications").symlink_to("/Applications")          # the drag-to-install target in the disk image
    shutil.copytree(ROOT / "samples", folder / "samples")
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    _write_notes(os_name, folder, version)
    return folder


def _write_notes(os_name: str, folder: Path, version: str) -> None:
    notes = (ROOT / "packaging" / f"first-run-{os_name}.txt").read_text(encoding="utf-8")
    (folder / "READ ME FIRST.txt").write_text(notes.replace("{version}", version), encoding="utf-8")


def bundle(os_name: str, downloads: Path, out: Path, version: str) -> Path:
    """Returns the archive for one system: installer(s) + README + sample CSV + licence + first-run notes."""
    if os_name not in BUNDLES:
        raise ValueError(f"unknown system: {os_name}")
    patterns, kind = BUNDLES[os_name]
    name = f"MiniBook-Studio-{version}-{os_name}"
    folder = out / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for pattern in patterns:
        wanted = pattern.format(v=version)
        found = sorted(downloads.rglob(wanted))
        if not found:
            raise FileNotFoundError(f"{wanted} is missing from {downloads}")
        target = folder / wanted
        shutil.copy2(found[0], target)
        if wanted.endswith(".AppImage"):
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)   # artifacts lose this
    shutil.copy2(ROOT / "README.md", folder / "README.md")
    shutil.copytree(ROOT / "samples", folder / "samples")
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    _write_notes(os_name, folder, version)
    archive = out / f"{name}.{kind}"
    if kind == "zip":
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(out))
    else:                                              # tar keeps the executable bit, so the AppImage just runs
        with tarfile.open(archive, "w:gz") as t:
            t.add(folder, arcname=name)
    return archive


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("bundle")
    b.add_argument("--downloads", default="downloads")
    b.add_argument("--out", default="bundles")
    b.add_argument("--version", required=True)
    ap.add_argument("--os", choices=["macos"])
    ap.add_argument("--dist", default="dist")
    ap.add_argument("--out", default="release")
    ap.add_argument("--version")
    a = ap.parse_args()
    if a.cmd == "bundle":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for os_name in BUNDLES:
            print(bundle(os_name, Path(a.downloads), out, a.version))
    else:
        print(stage(a.os, Path(a.dist), Path(a.out), a.version))


if __name__ == "__main__":
    main()
