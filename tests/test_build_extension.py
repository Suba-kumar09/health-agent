import json
import zipfile

from scripts.build_extension import EXTENSION_DIR, MANIFEST_PATH, _read_pyproject_version, build


def test_build_syncs_manifest_version_and_produces_expected_zip(tmp_path):
    expected_version = _read_pyproject_version()
    out = tmp_path / "extension.zip"

    result = build(out)

    assert result == out
    assert out.exists()
    assert expected_version  # sanity: pyproject actually has a version string

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        zipped_manifest = json.loads(zf.read("manifest.json"))

    # The zip's manifest.json must carry pyproject.toml's version...
    assert zipped_manifest["version"] == expected_version
    # ...and so must the on-disk manifest.json build() synced it from/to.
    on_disk_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert on_disk_manifest["version"] == expected_version

    assert "manifest.json" in names
    assert "background.js" in names
    assert "options.html" in names
    assert "options.js" in names
    assert "icons/icon16.png" in names
    assert "icons/icon32.png" in names
    assert "icons/icon48.png" in names
    assert "icons/icon128.png" in names


def test_build_output_lives_under_extension_dir_not_leaked_paths(tmp_path):
    out = tmp_path / "extension.zip"

    build(out)

    with zipfile.ZipFile(out) as zf:
        for name in zf.namelist():
            assert not name.startswith(str(EXTENSION_DIR)), "arcnames must be relative to EXTENSION_DIR"
