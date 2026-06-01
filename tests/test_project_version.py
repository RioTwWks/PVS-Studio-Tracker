"""Tests for release version detection."""

from pathlib import Path

from pvs_tracker.project_version import VersionDetectOptions, detect_project_version


def test_detect_from_version_rc(tmp_path: Path) -> None:
    rc = tmp_path / "app" / "MyApp.rc"
    rc.parent.mkdir(parents=True)
    rc.write_text(
        'FILEVERSION 8,10,3,0\nPRODUCTVERSION 8,10,3,0\n',
        encoding="utf-8",
    )
    parts = detect_project_version(
        tmp_path,
        VersionDetectOptions(build_system="msbuild", sln_name="MyApp.sln"),
    )
    assert parts is not None
    assert parts.as_string() == "8.10.3"


def test_detect_from_version_cmake(tmp_path: Path) -> None:
    cmake = tmp_path / "Version.cmake"
    cmake.write_text(
        "set(MAJOR_VERSION 1)\nset(MINOR_VERSION 2)\nset(PATCH_VERSION 3)\n",
        encoding="utf-8",
    )
    parts = detect_project_version(
        tmp_path,
        VersionDetectOptions(build_system="cmake"),
    )
    assert parts is not None
    assert parts.as_string() == "1.2.3"
