"""Tests for file path matching in code viewer."""

from pvs_tracker.file_resolver import paths_refer_to_same_file


def test_paths_exact_match() -> None:
    assert paths_refer_to_same_file(
        "src/foo.cpp",
        "src/foo.cpp",
    )


def test_paths_suffix_match_with_different_prefix() -> None:
    assert paths_refer_to_same_file(
        "D:/repo/dl_lib/src/TLogWriter.cpp",
        "dl_lib/src/TLogWriter.cpp",
        source_root="D:/repo",
    )


def test_paths_suffix_match_across_separators() -> None:
    assert paths_refer_to_same_file(
        r"dl_lib\src\TLogWriter.cpp",
        "dl_lib/src/TLogWriter.cpp",
    )


def test_paths_do_not_match_unrelated_files() -> None:
    assert not paths_refer_to_same_file(
        "other/foo.cpp",
        "src/foo.cpp",
    )


def test_paths_do_not_match_bare_filename_only() -> None:
    assert not paths_refer_to_same_file(
        "a/foo.cpp",
        "b/foo.cpp",
    )
