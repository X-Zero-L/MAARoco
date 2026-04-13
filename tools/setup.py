#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Download MaaFramework runtime to deps/ for local development.

Usage:
    uv run tools/setup.py              # auto-detect platform
    uv run tools/setup.py --platform win-x86_64
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO = "MaaXYZ/MaaFramework"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

PLATFORM_MAP = {
    ("Windows", "AMD64"): "win-x86_64",
    ("Windows", "ARM64"): "win-aarch64",
    ("Darwin", "x86_64"): "macos-x86_64",
    ("Darwin", "arm64"): "macos-aarch64",
    ("Linux", "x86_64"): "linux-x86_64",
    ("Linux", "aarch64"): "linux-aarch64",
}


def detect_platform() -> str:
    key = (platform.system(), platform.machine())
    plat = PLATFORM_MAP.get(key)
    if not plat:
        print(f"Unsupported platform: {key}")
        print(f"Available: {', '.join(v for v in PLATFORM_MAP.values())}")
        sys.exit(1)
    return plat


def get_latest_release(plat: str) -> tuple[str, str]:
    """Return (tag, download_url) for the given platform."""
    print(f"Fetching latest release from {REPO}...")
    req = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    tag = data["tag_name"]
    asset_name = f"MAA-{plat}-{tag}.zip"
    for asset in data["assets"]:
        if asset["name"] == asset_name:
            return tag, asset["browser_download_url"]

    print(f"Asset '{asset_name}' not found in release {tag}")
    print(f"Available: {', '.join(a['name'] for a in data['assets'])}")
    sys.exit(1)


def download_and_extract(url: str, dest: Path) -> None:
    print(f"Downloading {url} ...")
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        buf = io.BytesIO()
        downloaded = 0
        while True:
            chunk = resp.read(1 << 20)  # 1MB
            if not chunk:
                break
            buf.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded * 100 // total
                print(f"\r  {downloaded >> 20}/{total >> 20} MB ({pct}%)", end="", flush=True)
            else:
                print(f"\r  {downloaded >> 20} MB", end="", flush=True)
        print()

    print(f"Extracting to {dest}/ ...")
    buf.seek(0)
    with zipfile.ZipFile(buf) as zf:
        zf.extractall(dest)


def link_assets(project_root: Path, deps_dir: Path) -> None:
    """Link assets/interface.json and assets/resource/ into deps/bin/ for MaaPiCli."""
    bin_dir = deps_dir / "bin"
    if not bin_dir.exists():
        return

    assets_dir = project_root / "assets"

    # assets/ — directory junction (Windows) or symlink (Unix)
    # MaaPiCli looks for interface.json and resource/ relative to its own directory.
    # By junctioning the whole assets/ dir we just need one junction,
    # but MaaPiCli expects them at bin/interface.json and bin/resource/.
    # So we junction resource/ and symlink interface.json individually.

    # resource/
    link_resource = bin_dir / "resource"
    src_resource = assets_dir / "resource"
    if not link_resource.exists() and src_resource.exists():
        if sys.platform == "win32":
            import subprocess
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_resource), str(src_resource)],
                capture_output=True,
            )
        else:
            link_resource.symlink_to(src_resource)
        print("Linked resource/")

    # interface.json — symlink (stays in sync when file is re-saved)
    link_interface = bin_dir / "interface.json"
    src_interface = assets_dir / "interface.json"
    if not link_interface.exists() and src_interface.exists():
        if sys.platform == "win32":
            import subprocess
            subprocess.run(
                ["cmd", "/c", "mklink", str(link_interface), str(src_interface)],
                capture_output=True,
            )
        else:
            link_interface.symlink_to(src_interface)
        if link_interface.exists():
            print("Linked interface.json (symlink)")
        else:
            # Symlink may need admin on older Windows — fallback to copy
            shutil.copy2(src_interface, link_interface)
            print("Copied interface.json (symlink failed, using copy)")


def main():
    parser = argparse.ArgumentParser(description="Download MaaFramework for local dev")
    parser.add_argument("--platform", default="", help="e.g. win-x86_64, linux-x86_64")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    deps_dir = project_root / "deps"

    plat = args.platform or detect_platform()
    tag, url = get_latest_release(plat)

    # Check if already installed
    marker = deps_dir / ".maafw-version"
    if marker.exists() and marker.read_text().strip() == f"{tag}-{plat}":
        print(f"MaaFramework {tag} ({plat}) already installed in deps/")
        return

    # Clean old runtime files (keep tools/ schemas)
    for d in ("bin", "include", "lib", "share"):
        p = deps_dir / d
        if p.exists():
            shutil.rmtree(p)

    download_and_extract(url, deps_dir)
    marker.write_text(f"{tag}-{plat}\n")

    # Link project assets into bin/ so MaaPiCli can find them
    link_assets(project_root, deps_dir)

    # Verify
    if plat.startswith("win"):
        cli = deps_dir / "bin" / "MaaPiCli.exe"
    else:
        cli = deps_dir / "bin" / "MaaPiCli"

    if cli.exists():
        print(f"\nDone! MaaFramework {tag} installed.")
        print(f"Run with:\n  {cli.relative_to(project_root)}")
    else:
        print(f"\nExtracted to deps/, but MaaPiCli not found at expected path.")
        print("Check deps/bin/ contents.")


if __name__ == "__main__":
    main()
