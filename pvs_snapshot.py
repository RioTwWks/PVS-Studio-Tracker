"""
PVS-Studio Snapshot Builder — с улучшенной обработкой кодировок для Windows C++ проектов.

Определяет автора коммита через локальный Git (в т.ч. git-tf: каталог с .git в корне).
Метаданные пишутся в .meta.json для передачи в /api/v1/upload.
"""
from __future__ import annotations

import argparse
import json
import gzip
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Set, TypedDict


class CommitMetadata(TypedDict, total=False):
    commit: str
    commit_author_name: str
    commit_author_email: str


def read_file_with_fallback(file_path: Path) -> tuple[str, str]:
    """
    Читает файл с приоритетом кодировок для Windows C++ проектов.
    Возвращает (content, used_encoding).
    """
    ext = file_path.suffix.lower()

    if os.name == "nt" and ext in [".cpp", ".h", ".c", ".hpp", ".cxx", ".cc"]:
        encodings_priority = [
            ("cp1251", "strict"),
            ("cp866", "strict"),
            ("utf-8", "strict"),
            ("utf-8-sig", "strict"),
            ("cp1251", "replace"),
            ("cp866", "replace"),
            ("utf-8", "replace"),
            ("latin-1", "replace"),
        ]
    else:
        encodings_priority = [
            ("utf-8", "strict"),
            ("utf-8-sig", "strict"),
            ("cp1251", "strict"),
            ("cp866", "strict"),
            ("cp1251", "replace"),
            ("utf-8", "replace"),
            ("latin-1", "replace"),
        ]

    for enc, errors in encodings_priority:
        try:
            content = file_path.read_text(encoding=enc, errors=errors)
            if errors == "strict":
                return content, enc
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
        except OSError:
            continue

    print(f"❌ Could not read {file_path.name} with any encoding", file=sys.stderr)
    return "", "failed"


def _run_git(repo_dir: Path, *args: str, timeout: int = 30) -> Optional[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_dir), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return completed.stdout.strip() or None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def is_git_repo(repo_dir: Path) -> bool:
    return (repo_dir / ".git").exists() or _run_git(repo_dir, "rev-parse", "--git-dir") is not None


def resolve_git_commit(repo_dir: Path, commit: Optional[str]) -> Optional[str]:
    ref = (commit or "").strip() or "HEAD"
    verified = _run_git(repo_dir, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if verified:
        return verified
    return _run_git(repo_dir, "rev-parse", "HEAD")


def get_commit_author_git(
    repo_dir: Path, commit: Optional[str]
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Автор коммита из локального Git checkout (git-tf тоже создаёт .git в корне).

    Returns:
        (resolved_commit, author_name, author_email)
    """
    resolved = resolve_git_commit(repo_dir, commit)
    if not resolved:
        print("⚠️ Could not resolve Git commit", file=sys.stderr)
        return None, None, None

    log_line = _run_git(repo_dir, "log", "-1", "--format=%an|%ae", resolved)
    if not log_line or "|" not in log_line:
        print(f"⚠️ Could not read author for commit {resolved}", file=sys.stderr)
        return resolved, None, None

    name, _, email = log_line.partition("|")
    author_name = name.strip() or None
    author_email = email.strip() or None
    print(
        f"👤 Commit {resolved[:12]} author: {author_name} <{author_email}>",
        file=sys.stderr,
    )
    return resolved, author_name, author_email


def resolve_commit_metadata(repo_dir: Path, commit: Optional[str] = None) -> CommitMetadata:
    """Commit hash и автор для upload API (только Git)."""
    if not is_git_repo(repo_dir):
        print("⚠️ No .git in base_dir, skipping author resolution", file=sys.stderr)
        meta: CommitMetadata = {}
        if commit and commit.strip():
            meta["commit"] = commit.strip()
        return meta

    resolved, author_name, author_email = get_commit_author_git(repo_dir, commit)
    meta = {}
    if resolved:
        meta["commit"] = resolved
    if author_name:
        meta["commit_author_name"] = author_name
    if author_email:
        meta["commit_author_email"] = author_email
    return meta


def write_metadata(path: str, metadata: CommitMetadata) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"📋 Metadata written: {path}", file=sys.stderr)


def default_metadata_path(snapshot_path: str) -> str:
    if snapshot_path.endswith(".json.gz"):
        return snapshot_path[: -len(".json.gz")] + ".meta.json"
    return f"{snapshot_path}.meta.json"


def build_snapshot(
    report_path: str,
    output_path: str,
    base_dir: str = ".",
    *,
    commit: Optional[str] = None,
    metadata_out: Optional[str] = None,
    skip_author: bool = False,
) -> CommitMetadata:
    """Создаёт снапшот исходного кода для файлов из отчёта."""
    base = Path(base_dir).resolve()
    metadata: CommitMetadata = {}
    if not skip_author:
        metadata = resolve_commit_metadata(base, commit=commit)

    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    warnings = report.get("warnings", report if isinstance(report, list) else [])
    file_paths: Set[str] = set()

    for w in warnings:
        for pos in w.get("positions", []):
            fp = pos.get("file", "")
            if fp and not fp.startswith("__analysis__"):
                file_paths.add(fp)
        fp = w.get("fileName", "")
        if fp:
            file_paths.add(fp)

    snapshot: dict[str, str] = {}
    print(f"📦 Building snapshot for {len(file_paths)} files...", file=sys.stderr)

    for rel_path in file_paths:
        full_path = base / rel_path
        if full_path.exists() and full_path.is_file():
            try:
                content, used_enc = read_file_with_fallback(full_path)

                if used_enc == "failed" or not content:
                    print(f"⚠️ Skipped unreadable file: {rel_path}", file=sys.stderr)
                    continue

                has_cyrillic = any("\u0400" <= c <= "\u04FF" for c in content[:500])
                print(
                    f"✅ Read: {rel_path} (encoding: {used_enc}, cyrillic: {has_cyrillic})",
                    file=sys.stderr,
                )

                if "\ufffd" in content[:200] and not has_cyrillic:
                    print(
                        f"⚠️ Warning: replacement chars in {rel_path} (read as {used_enc})",
                        file=sys.stderr,
                    )

                key = rel_path.replace("\\", "/")
                snapshot[key] = content

            except OSError as e:
                print(f"❌ Failed to process {rel_path}: {e}", file=sys.stderr)
        else:
            print(f"⚠️ File not found: {full_path}", file=sys.stderr)

    print(f"💾 Writing snapshot to {output_path}...", file=sys.stderr)
    with gzip.open(output_path, "wt", encoding="utf-8", errors="replace") as f:
        json.dump(
            snapshot,
            f,
            ensure_ascii=False,
            indent=2,
            default=str,
            sort_keys=True,
        )
    size_kb = os.path.getsize(output_path) / 1024
    print(
        f"✅ Snapshot created: {output_path} ({len(snapshot)} files, {size_kb:.1f} KB)",
        file=sys.stderr,
    )

    if metadata and metadata_out:
        write_metadata(metadata_out, metadata)

    return metadata


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build PVS code snapshot (.json.gz) and Git commit author metadata.",
    )
    parser.add_argument("report", help="Path to PVS-Studio report.json")
    parser.add_argument("output", help="Output snapshot path (.json.gz)")
    parser.add_argument(
        "base_dir",
        nargs="?",
        default=".",
        help="Source root with .git (git or git-tf checkout)",
    )
    parser.add_argument(
        "--commit",
        help="Git commit ref (default: HEAD)",
    )
    parser.add_argument(
        "--metadata-out",
        metavar="PATH",
        help="Write commit/author JSON (default: <output>.meta.json)",
    )
    parser.add_argument(
        "--no-metadata",
        action="store_true",
        help="Do not write metadata JSON file",
    )
    parser.add_argument(
        "--skip-author",
        action="store_true",
        help="Only build snapshot, skip author resolution",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print metadata JSON to stdout (for CI parsing)",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    metadata_out: Optional[str] = None
    if not args.no_metadata and not args.skip_author:
        metadata_out = args.metadata_out or default_metadata_path(args.output)

    metadata = build_snapshot(
        args.report,
        args.output,
        args.base_dir,
        commit=args.commit,
        metadata_out=metadata_out,
        skip_author=args.skip_author,
    )

    if args.print_json and metadata:
        print(json.dumps(metadata, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
