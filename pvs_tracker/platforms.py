"""Target platform constants and cross-platform fingerprint helpers."""

from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import HTTPException

from pvs_tracker.file_resolver import get_effective_source_root, normalize_file_path_for_display
from pvs_tracker.models import GlobalSettings, Project

TargetPlatform = Literal["windows", "linux", "macos"]
PlatformFilter = Literal["windows", "linux", "macos", "all", "common"]
ReportType = Literal["incremental", "full"]

PLATFORMS: tuple[TargetPlatform, ...] = ("windows", "linux", "macos")
DEFAULT_PLATFORM: TargetPlatform = "windows"
DEFAULT_PLATFORM_FILTER: PlatformFilter = "windows"
DEFAULT_REPORT_TYPE: ReportType = "incremental"


def normalize_report_type(value: str | None) -> ReportType:
    """Validate upload report scope: incremental (partial PVS) or full snapshot."""
    if not value:
        return DEFAULT_REPORT_TYPE
    normalized = value.strip().lower()
    if normalized not in ("incremental", "full"):
        raise HTTPException(
            400,
            f"Invalid report_type: {value}. Must be one of: incremental, full",
        )
    return normalized  # type: ignore[return-value]


def normalize_target_platform(value: str | None) -> TargetPlatform:
    """Validate and normalize upload / run platform value."""
    if not value:
        return DEFAULT_PLATFORM
    normalized = value.strip().lower()
    if normalized not in PLATFORMS:
        raise HTTPException(
            400,
            f"Invalid target_platform: {value}. Must be one of: {', '.join(PLATFORMS)}",
        )
    return normalized  # type: ignore[return-value]


def normalize_platform_filter(value: str | None) -> PlatformFilter:
    """Validate dashboard / issues filter value."""
    if not value:
        return DEFAULT_PLATFORM_FILTER
    normalized = value.strip().lower()
    allowed: tuple[PlatformFilter, ...] = (
        "windows",
        "linux",
        "macos",
        "all",
        "common",
    )
    if normalized not in allowed:
        return DEFAULT_PLATFORM_FILTER
    return normalized  # type: ignore[return-value]


def compute_cross_platform_fp(
    file_path: str,
    rule_code: str,
    message: str,
    *,
    project: Project | None = None,
    global_settings: GlobalSettings | None = None,
    platform: TargetPlatform = DEFAULT_PLATFORM,
) -> str:
    """Stable key for matching the same defect across OS reports."""
    norm_msg = " ".join(message.split())
    root = None
    if project is not None:
        root = get_effective_source_root(
            project.source_root_win,
            project.source_root_linux,
            project.source_root_macos,
            global_settings,
            platform=platform,
        )
    rel = normalize_file_path_for_display(file_path, root)
    rel_norm = rel.replace("\\", "/")
    raw = f"{rule_code}:{rel_norm}:{norm_msg}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def platform_label(platform: str) -> str:
    """Human-readable platform name for UI badges."""
    labels = {
        "windows": "Windows",
        "linux": "Linux",
        "macos": "macOS",
    }
    return labels.get(platform, platform)
