"""Git integration service for fetching source code on demand.

This module provides SonarQube-style source code retrieval by:
1. Cloning/fetching from Git repository on demand
2. Extracting specific files at specific commits
3. Caching results to avoid repeated Git operations
"""

import asyncio
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

from fastapi import HTTPException

import gzip
import json
import time

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Directory for Git worktrees (temporary clones)
GIT_CACHE_DIR = os.getenv("GIT_CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", ".git_cache"))
SNAPSHOTS_DIR = os.getenv("SNAPSHOTS_DIR", os.path.join(os.path.dirname(__file__), "..", "data", "snapshots"))
Path(SNAPSHOTS_DIR).mkdir(parents=True, exist_ok=True)
# Cache TTL in minutes (avoid re-cloning too frequently)
CACHE_TTL_MINUTES = int(os.getenv("GIT_CACHE_TTL_MINUTES", "60"))
# Timeout for Git operations (seconds)
GIT_TIMEOUT_SECONDS = int(os.getenv("GIT_TIMEOUT_SECONDS", "30"))


@dataclass
class SourceFile:
    """Represents a source file with its content."""
    file_path: str
    content: str
    lines: list[str]
    commit: Optional[str] = None
    fetched_at: Optional[datetime] = None
    source: str = "git"  # git, archive, local


# ---------------------------------------------------------------------------
# Cache management
# ---------------------------------------------------------------------------

class GitCache:
    """Manages cached Git repositories and fetched files."""
    
    def __init__(self, cache_dir: str = GIT_CACHE_DIR, ttl_minutes: int = CACHE_TTL_MINUTES):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(minutes=ttl_minutes)
        self._repo_timestamps: dict[str, datetime] = {}
    
    def _get_repo_path(self, git_url: str, branch: str) -> Path:
        """Get cache path for a Git repository."""
        # Create unique directory name from URL + branch
        repo_name = git_url.split("/")[-1].replace(".git", "")
        safe_name = f"{repo_name}_{branch}".replace("/", "_").replace("\\", "_")
        # Hash if name is too long
        if len(safe_name) > 100:
            import hashlib
            safe_name = hashlib.md5(f"{git_url}_{branch}".encode()).hexdigest()[:16]
        return self.cache_dir / safe_name
    
    def is_cache_valid(self, git_url: str, branch: str) -> bool:
        """Check if cached repository is still valid (within TTL)."""
        repo_path = self._get_repo_path(git_url, branch)
        if not repo_path.exists():
            return False
        
        timestamp = self._repo_timestamps.get(str(repo_path))
        if not timestamp:
            # Check directory modification time
            mtime = datetime.fromtimestamp(repo_path.stat().st_mtime)
            self._repo_timestamps[str(repo_path)] = mtime
            timestamp = mtime
        
        return datetime.now() - timestamp < self.ttl
    
    def update_timestamp(self, git_url: str, branch: str):
        """Update cache timestamp after successful fetch."""
        repo_path = self._get_repo_path(git_url, branch)
        self._repo_timestamps[str(repo_path)] = datetime.now()
    
    def cleanup_expired(self):
        """Remove expired cache entries."""
        now = datetime.now()
        expired = [
            path for path, ts in self._repo_timestamps.items()
            if now - ts > self.ttl
        ]
        for path in expired:
            repo_path = Path(path)
            if repo_path.exists():
                try:
                    shutil.rmtree(repo_path)
                    logger.info("Cleaned up expired Git cache: %s", repo_path)
                except Exception as e:
                    logger.warning("Failed to clean up %s: %s", repo_path, e)
            del self._repo_timestamps[path]


# Global cache instance
git_cache = GitCache()


async def fetch_from_run_snapshot(run_id: int, file_path: str) -> Optional[SourceFile]:
    """Fetch file from the run-specific code snapshot."""
    snapshot_path = SNAPSHOTS_DIR / f"{run_id}.json.gz"
    if not snapshot_path.exists():
        return None
    
    normalized = file_path.replace("\\", "/")
    
    try:
        with gzip.open(snapshot_path, "rt", encoding="utf-8") as f:
            snapshot = json.load(f)
            
        content = snapshot.get(normalized)
        if content is None:
            return None
            
        lines = content.splitlines(keepends=True)
        return SourceFile(
            file_path=normalized,
            content=content,
            lines=lines,
            source="snapshot",
        )
    except Exception as e:
        logger.warning(f"Failed to load snapshot for run {run_id}: {e}")
        return None


# ---------------------------------------------------------------------------
# Git operations
# ---------------------------------------------------------------------------

async def clone_or_update_repo(git_url: str, branch: str) -> Path:
    """Clone repository if not cached, otherwise update existing clone."""
    repo_path = git_cache._get_repo_path(git_url, branch)
    
    if repo_path.exists() and git_cache.is_cache_valid(git_url, branch):
        # Cache hit - update if needed
        logger.debug("Using cached Git repository: %s", repo_path)
        try:
            await asyncio.wait_for(
                _run_git_command(repo_path, ["git", "fetch", "origin"]),
                timeout=GIT_TIMEOUT_SECONDS
            )
            await asyncio.wait_for(
                _run_git_command(repo_path, ["git", "checkout", branch]),
                timeout=GIT_TIMEOUT_SECONDS
            )
            await asyncio.wait_for(
                _run_git_command(repo_path, ["git", "pull", "--ff-only"]),
                timeout=GIT_TIMEOUT_SECONDS
            )
        except Exception as e:
            logger.warning("Git update failed, using cached version: %s", e)
        
        git_cache.update_timestamp(git_url, branch)
        return repo_path
    
    # Cache miss or expired - clone fresh
    if repo_path.exists():
        logger.info("Removing expired cache: %s", repo_path)
        shutil.rmtree(repo_path, ignore_errors=True)
    
    logger.info("Cloning Git repository: %s (branch: %s)", git_url, branch)
    repo_path.mkdir(parents=True, exist_ok=True)
    
    try:
        await asyncio.wait_for(
            _run_git_command(
                repo_path,
                ["git", "clone", "--depth", "1", "--branch", branch, git_url, "."],
            ),
            timeout=GIT_TIMEOUT_SECONDS
        )
        git_cache.update_timestamp(git_url, branch)
        return repo_path
    except Exception as e:
        # Clean up failed clone
        if repo_path.exists():
            shutil.rmtree(repo_path, ignore_errors=True)
        raise HTTPException(500, f"Failed to clone repository: {e}")


async def checkout_commit(repo_path: Path, commit: str):
    """Checkout a specific commit."""
    try:
        await asyncio.wait_for(
            _run_git_command(repo_path, ["git", "fetch", "--depth", "1", "origin", commit]),
            timeout=GIT_TIMEOUT_SECONDS
        )
        await asyncio.wait_for(
            _run_git_command(repo_path, ["git", "checkout", commit]),
            timeout=GIT_TIMEOUT_SECONDS
        )
    except Exception as e:
        logger.warning("Failed to checkout commit %s: %s", commit, e)


async def fetch_file_from_git(
    git_url: str,
    branch: str,
    file_path: str,
    commit: Optional[str] = None,
) -> SourceFile:
    """Fetch a specific file from Git repository."""
    # Clone or update repository
    repo_path = await clone_or_update_repo(git_url, branch)
    
    # Checkout specific commit if provided
    if commit:
        await checkout_commit(repo_path, commit)
    
    # Read file
    full_path = repo_path / file_path
    if not full_path.exists():
        # Try different path variations
        for variation in _generate_path_variations(file_path):
            alt_path = repo_path / variation
            if alt_path.exists():
                full_path = alt_path
                break
        else:
            raise HTTPException(404, f"File not found in Git repository: {file_path}")
    
    try:
        content = full_path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines(keepends=True)
        
        return SourceFile(
            file_path=file_path,
            content=content,
            lines=lines,
            commit=commit,
            fetched_at=datetime.now(),
            source="git",
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to read file from Git: {e}")


async def _run_git_command(repo_path: Path, command: list[str]) -> str:
    """Run a Git command in the specified repository directory."""
    import subprocess
    
    env = os.environ.copy()
    # Disable interactive prompts
    env["GIT_TERMINAL_PROMPT"] = "0"
    
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=repo_path,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    
    stdout, stderr = await process.communicate()
    
    if process.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace").strip()
        raise Exception(f"Git command failed: {' '.join(command)}\n{error_msg}")
    
    return stdout.decode("utf-8", errors="replace")


def _generate_path_variations(file_path: str) -> list[str]:
    """Generate path variations to try (for cross-platform compatibility)."""
    variations = []
    
    # Normalize separators
    normalized = file_path.replace("\\", "/")
    
    # Try as-is
    variations.append(normalized)
    
    # Try lowercase
    variations.append(normalized.lower())
    
    # Try with different base directories
    parts = normalized.split("/")
    if len(parts) > 1:
        # Try just the filename
        variations.append(parts[-1])
        # Try last two components
        variations.append("/".join(parts[-2:]))
    
    return variations


# ---------------------------------------------------------------------------
# Archive extraction
# ---------------------------------------------------------------------------

async def fetch_file_from_archive(
    archive_path: str,
    file_path: str,
) -> Optional[SourceFile]:
    """Extract a specific file from a source archive."""
    if not archive_path or not os.path.exists(archive_path):
        return None
    
    import zipfile
    import tarfile
    
    archive = Path(archive_path)
    normalized_path = file_path.replace("\\", "/")
    
    try:
        if archive.suffix == ".zip":
            return await _extract_from_zip(archive, normalized_path)
        elif archive.suffix in (".tar", ".gz", ".bz2", ".xz"):
            return await _extract_from_tar(archive, normalized_path)
        else:
            logger.warning("Unsupported archive format: %s", archive.suffix)
            return None
    except Exception as e:
        logger.warning("Failed to extract from archive: %s", e)
        return None


async def _extract_from_zip(archive_path: Path, file_path: str) -> Optional[SourceFile]:
    """Extract file from ZIP archive."""
    import zipfile
    
    with zipfile.ZipFile(archive_path, "r") as zf:
        # Try exact match first
        for name in zf.namelist():
            if name.replace("\\", "/") == file_path or name.endswith("/" + file_path):
                content = zf.read(name).decode("utf-8", errors="replace")
                lines = content.splitlines(keepends=True)
                return SourceFile(
                    file_path=file_path,
                    content=content,
                    lines=lines,
                    source="archive",
                )
    
    return None


async def _extract_from_tar(archive_path: Path, file_path: str) -> Optional[SourceFile]:
    """Extract file from tar archive."""
    import tarfile
    
    mode = "r:*" if archive_path.suffix != ".tar" else "r:"
    with tarfile.open(archive_path, mode) as tf:
        for member in tf.getmembers():
            if member.isfile():
                name = member.name.replace("\\", "/")
                if name == file_path or name.endswith("/" + file_path):
                    content = tf.extractfile(member)
                    if content:
                        text = content.read().decode("utf-8", errors="replace")
                        lines = text.splitlines(keepends=True)
                        return SourceFile(
                            file_path=file_path,
                            content=text,
                            lines=lines,
                            source="archive",
                        )
    
    return None


# ---------------------------------------------------------------------------
# High-level API
# ---------------------------------------------------------------------------

async def fetch_from_run_snapshot(run_id: int, file_path: str) -> Optional[SourceFile]:
    """Fetch file from the run-specific code snapshot."""
    snapshot_path = Path(SNAPSHOTS_DIR) / f"{run_id}.json.gz"
    if not snapshot_path.exists():
        return None
    
    normalized = file_path.replace("\\", "/")
    
    try:
        with gzip.open(snapshot_path, "rt", encoding="utf-8") as f:
            snapshot = json.load(f)
            
        content = snapshot.get(normalized)
        if content is None:
            return None
            
        lines = content.splitlines(keepends=True)
        return SourceFile(
            file_path=normalized,
            content=content,
            lines=lines,
            source="snapshot",
        )
    except Exception as e:
        logger.warning(f"Failed to load snapshot for run {run_id}: {e}")
        return None

async def fetch_source_file(
    project_id: int,
    file_path: str,
    run_id: Optional[int] = None,
    git_url: Optional[str] = None,
    git_branch: Optional[str] = None,
    commit: Optional[str] = None,
    source_archive_path: Optional[str] = None,
    source_root_win: Optional[str] = None,
    source_root_linux: Optional[str] = None,
) -> SourceFile:
    """
    Fetch source file using fallback strategy:
    0. CI Snapshot (uploaded with report)
    1. Git repository
    2. Source archive
    3. Local file system
    """
    # 🔑 Strategy 0: CI Snapshot (fastest & most accurate)
    if run_id:
        result = await fetch_from_run_snapshot(run_id, file_path)
        if result:
            return result

    from pvs_tracker.file_resolver import resolve_source_path
    
    # Strategy 1: Git repository
    if git_url:
        try:
            logger.info("Fetching from Git: %s / %s", git_url, file_path)
            return await fetch_file_from_git(git_url, git_branch or "main", file_path, commit)
        except Exception as e:
            logger.warning("Git fetch failed, trying next strategy: %s", e)
    
    # Strategy 2: Source archive
    if source_archive_path:
        try:
            logger.info("Fetching from archive: %s / %s", source_archive_path, file_path)
            result = await fetch_file_from_archive(source_archive_path, file_path)
            if result:
                return result
        except Exception as e:
            logger.warning("Archive extraction failed: %s", e)
    
    # Strategy 3: Local file system (backward compatibility)
    if source_root_win or source_root_linux:
        try:
            logger.info("Fetching from local filesystem: %s", file_path)
            abs_path = resolve_source_path(
                source_root_win,
                source_root_linux,
                file_path,
            )
            content = abs_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines(keepends=True)
            return SourceFile(
                file_path=file_path,
                content=content,
                lines=lines,
                source="local",
            )
        except Exception as e:
            logger.warning("Local file access failed: %s", e)
    
    # All strategies failed
    raise HTTPException(
        404,
        f"Source code not available for file: {file_path}\n\n"
        f"To enable source code viewing, configure one of:\n"
        f"1. Git repository URL in project settings\n"
        f"2. Upload source archive with report\n"
        f"3. Configure source_root paths (legacy)"
    )
