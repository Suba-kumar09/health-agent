"""Zip browser-extension/ into a store-uploadable archive.

pyproject.toml's [project].version is the single source of truth for the extension's
version too -- before zipping, this script rewrites browser-extension/manifest.json's
`version` field to match it (a no-op write if they already agree), so the packaged
extension can never ship with a version that has drifted from the Python project's.

Usage:
    python scripts/build_extension.py
    python scripts/build_extension.py --out dist/health-agent-extension.zip
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
EXTENSION_DIR = REPO_ROOT / "browser-extension"
MANIFEST_PATH = EXTENSION_DIR / "manifest.json"

# Files that shouldn't ship in the store package if they ever show up here.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}


def _read_pyproject_version() -> str:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


def _sync_manifest_version(version: str) -> None:
    """Rewrites manifest.json's version field to match pyproject.toml, in place."""
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        manifest["version"] = version
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Synced browser-extension/manifest.json version -> {version}")


def build(out: Path) -> Path:
    version = _read_pyproject_version()
    _sync_manifest_version(version)
    out.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(EXTENSION_DIR.rglob("*")):
            if path.is_dir() or path.name in EXCLUDE_NAMES:
                continue
            zf.write(path, arcname=path.relative_to(EXTENSION_DIR))

    print(f"Built {out} (version {version})")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out",
        default=None,
        help="Output zip path; defaults to dist/health-agent-extension-<version>.zip",
    )
    args = parser.parse_args()

    out = Path(args.out) if args.out else REPO_ROOT / "dist" / f"health-agent-extension-{_read_pyproject_version()}.zip"
    build(out)


if __name__ == "__main__":
    main()
