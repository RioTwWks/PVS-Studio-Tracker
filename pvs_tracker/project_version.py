"""Detect product release version from sources (CMake / Version.rc / VersionInfo.h)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal, Optional

logger = logging.getLogger(__name__)

BuildSystem = Literal["msbuild", "cmake", "auto"]

FILEVERSION_RE = re.compile(r".*FILEVERSION\s+(\d+),(\d+),(\d+),\d+", re.IGNORECASE)
CMAKE_VER_LINE_RE = re.compile(r".*VER.* \d+")
CMAKE_NUM_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class VersionParts:
    major: int
    minor: int
    patch: int

    def as_string(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class VersionDetectOptions:
    """Options aligned with Jenkins get_version / get-version-linux scripts."""

    group: str = ""
    build_system: BuildSystem = "auto"
    sln_name: str = ""
    project_key: str = ""
    project_name: str = ""
    select_vcxproj: str = ""
    exclude_paths: tuple[str, ...] = ()


def _path_excluded(path: Path, exclude_dirs: tuple[str, ...]) -> bool:
    path_str = str(path)
    return any(part and part in path_str for part in exclude_dirs)


def _read_text_lines(path: Path) -> Iterator[str]:
    encodings = ("utf-8", "utf-8-sig", "cp866", "cp1251", "latin-1")
    for enc in encodings:
        try:
            text = path.read_text(encoding=enc)
            yield from text.splitlines()
            return
        except (UnicodeDecodeError, OSError):
            continue
    logger.debug("Could not read %s for version detection", path)
    return iter(())


def _parse_cmake_version_lines(lines: Iterator[str]) -> Optional[VersionParts]:
    major: int | None = None
    minor: int | None = None
    patch: int | None = None
    for line in lines:
        if not CMAKE_VER_LINE_RE.match(line):
            continue
        if re.search(r"MAJ", line, re.IGNORECASE):
            match = CMAKE_NUM_RE.search(line)
            if match:
                major = int(match.group(1))
        elif re.search(r"MIN", line, re.IGNORECASE):
            match = CMAKE_NUM_RE.search(line)
            if match:
                minor = int(match.group(1))
        elif re.search(r"PATCH", line, re.IGNORECASE):
            match = CMAKE_NUM_RE.search(line)
            if match:
                patch = int(match.group(1))
                break
    if major is None or minor is None or patch is None:
        return None
    return VersionParts(major, minor, patch)


def _find_fileversion(root: Path, pattern: str, exclude_dirs: tuple[str, ...]) -> Optional[VersionParts]:
    for path in sorted(root.rglob(pattern)):
        if not path.is_file() or _path_excluded(path, exclude_dirs):
            continue
        for line in _read_text_lines(path):
            match = FILEVERSION_RE.match(line)
            if match:
                return VersionParts(
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )
    return None


def _find_cmake_version(
    root: Path,
    glob_pattern: str,
    exclude_dirs: tuple[str, ...],
) -> Optional[VersionParts]:
    for path in sorted(root.rglob(glob_pattern)):
        if not path.is_file() or _path_excluded(path, exclude_dirs):
            continue
        version = _parse_cmake_version_lines(_read_text_lines(path))
        if version:
            return version
    return None


def _upper_two_levels_windows(vcxproj_path: str) -> str:
    parts = vcxproj_path.replace("/", "\\").split("\\")
    if parts and parts[0] in (".", ""):
        parts.pop(0)
    remaining = parts[:-2] if len(parts) >= 2 else []
    if not remaining:
        return ""
    return "\\" + "\\".join(remaining) + "\\"


def _find_qadmin_version(root: Path, options: VersionDetectOptions) -> Optional[VersionParts]:
    name = options.project_name
    if "QAdministrator_Client" in name or "QAdministrator_Server" in name:
        candidates = [root / "Exchange" / "Common" / "VersionInfo.h"]
    elif options.select_vcxproj.strip():
        prefix = _upper_two_levels_windows(options.select_vcxproj)
        rel = prefix.lstrip("\\").replace("\\", "/")
        candidates = list((root / rel).rglob("VersionInfo.h")) if rel else []
        if not candidates:
            candidates = list(root.rglob("CMakeLists.txt"))
    else:
        candidates = list(root.rglob("VersionInfo.h"))

    for path in candidates:
        if not path.is_file():
            continue
        version = _parse_cmake_version_lines(_read_text_lines(path))
        if version:
            return version
    return None


def _detect_msbuild(root: Path, options: VersionDetectOptions) -> Optional[VersionParts]:
    sln_stem = (options.sln_name or "").split(".")[0]
    exclude = options.exclude_paths

    if sln_stem:
        version = _find_fileversion(root, f"*{sln_stem}*.rc", exclude)
        if version:
            return version

    for pattern in ("*Version*.rc", "*version*.rc", "*.rc"):
        version = _find_fileversion(root, pattern, exclude)
        if version:
            return version
    return None


def _detect_cmake(root: Path, options: VersionDetectOptions) -> Optional[VersionParts]:
    version = _find_cmake_version(root, "*Version*.cmake", options.exclude_paths)
    if version:
        return version

    key = options.project_key
    if key:
        for segment in (key.split(".")[-1], key.split(".")[-2] if "." in key else ""):
            if not segment:
                continue
            version = _find_cmake_version(root, f"*{segment}*.cmake", options.exclude_paths)
            if version:
                return version

    return _find_cmake_version(root, "CMakeLists.txt", options.exclude_paths)


def detect_project_version(
    base_dir: str | Path,
    options: VersionDetectOptions | None = None,
) -> Optional[VersionParts]:
    """
    Detect major.minor.patch from the project tree.

    Mirrors Jenkins scripts get_version_fastapi.py / get-version-linux.py.
    """
    opts = options or VersionDetectOptions()
    root = Path(base_dir).resolve()
    if not root.is_dir():
        return None

    if opts.group.upper() == "QA":
        return _find_qadmin_version(root, opts)

    build = opts.build_system
    if build == "auto":
        build = "msbuild" if any(root.rglob("*.sln")) else "cmake"

    if build == "msbuild":
        version = _detect_msbuild(root, opts)
        if version:
            return version
        return _detect_cmake(root, opts)

    return _detect_cmake(root, opts)
