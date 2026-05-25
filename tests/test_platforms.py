"""Tests for OS platform separation."""

import pytest
from fastapi import HTTPException

from pvs_tracker.models import Project
from pvs_tracker.platforms import (
    compute_cross_platform_fp,
    normalize_platform_filter,
    normalize_target_platform,
)


def test_normalize_target_platform_valid() -> None:
    assert normalize_target_platform("Windows") == "windows"
    assert normalize_target_platform("LINUX") == "linux"
    assert normalize_target_platform("macos") == "macos"


def test_normalize_target_platform_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        normalize_target_platform("freebsd")
    assert exc.value.status_code == 400


def test_normalize_platform_filter_defaults() -> None:
    assert normalize_platform_filter(None) == "windows"
    assert normalize_platform_filter("common") == "common"
    assert normalize_platform_filter("invalid") == "windows"


def test_compute_cross_platform_fp_strips_root() -> None:
    project = Project(
        name="test-fp",
        source_root_win=r"C:\proj",
        source_root_linux="/home/proj",
        source_root_macos="/Users/proj",
    )
    fp_win = compute_cross_platform_fp(
        r"C:\proj\src\main.cpp",
        "V1001",
        "Some message",
        project=project,
        platform="windows",
    )
    fp_linux = compute_cross_platform_fp(
        "/home/proj/src/main.cpp",
        "V1001",
        "Some message",
        project=project,
        platform="linux",
    )
    assert fp_win == fp_linux


def test_compute_cross_platform_fp_differs_by_rule() -> None:
    project = Project(name="test", source_root_win=r"C:\proj")
    a = compute_cross_platform_fp(r"C:\proj\a.cpp", "V1001", "msg", project=project, platform="windows")
    b = compute_cross_platform_fp(r"C:\proj\a.cpp", "V1002", "msg", project=project, platform="windows")
    assert a != b
