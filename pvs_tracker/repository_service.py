"""Git/TFVC change detection for CI webhooks."""

from __future__ import annotations

import logging
import os
import shutil
import stat
import time
import uuid
from typing import Optional

import requests
from requests_ntlm import HttpNtlmAuth

from pvs_tracker.ci_config import ci_settings
from pvs_tracker.models import Project
from pvs_tracker.project_ci import project_analysis_branch, project_repo_path

logger = logging.getLogger(__name__)

C_EXTENSIONS = {".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".hh", ".hxx", ".cs"}
CMAKE_PATTERNS = {"CMakeLists.txt", "CMakePresets.json", "CUserMakePresets.json"}
CMAKE_EXTENSIONS = {".cmake"}


def _tfs_url() -> str:
    return ci_settings.TFS_BASE_URL.rstrip("/")


def _ntlm_auth() -> HttpNtlmAuth:
    return HttpNtlmAuth(ci_settings.WEBHOOK_USERNAME, ci_settings.WEBHOOK_PASSWORD)


def remove_readonly(func, path, _):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def safe_rmtree(path: str, max_retries: int = 3) -> None:
    for attempt in range(max_retries):
        try:
            if os.path.exists(path):
                shutil.rmtree(path, onerror=remove_readonly)
                return
        except OSError:
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:
                logger.warning("Could not remove temporary directory: %s", path)


def is_c_file(path: str) -> bool:
    if not path:
        return False
    return os.path.splitext(path)[1].lower() in C_EXTENSIONS


def is_cmake_file(path: str) -> bool:
    if not path:
        return False
    basename = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    return basename in CMAKE_PATTERNS or ext in CMAKE_EXTENSIONS


def check_git_changes(
    project: Project,
    last_processed_commit: str,
    last_server_commit: str,
) -> tuple[list[str], str, bool, bool]:
    from git import Repo

    logger.info("Checking Git changes %s -> %s", last_processed_commit, last_server_commit)
    if not last_processed_commit:
        return ["1"], "YES", True, True

    repo_path = project_repo_path(project)
    branch = project_analysis_branch(project)
    temp_dir = os.path.join(ci_settings.CI_TEMP_DIR, f"temp_repo_{uuid.uuid4().hex[:8]}")
    os.makedirs(ci_settings.CI_TEMP_DIR, exist_ok=True)
    repo = None
    try:
        repo = Repo.clone_from(repo_path, temp_dir, no_checkout=True, branch=branch)
        last_processed = repo.commit(last_processed_commit)
        last_server = repo.commit(last_server_commit)
        diff = last_processed.diff(last_server)
        changed_files: list[str] = []
        composition_changed = False
        cmake_changed = False
        for diff_item in diff:
            is_c = False
            for path in (diff_item.a_path, diff_item.b_path):
                if path and is_c_file(path):
                    is_c = True
                    changed_files.append(path)
            if is_c and (diff_item.new_file or diff_item.deleted_file or diff_item.renamed):
                composition_changed = True
            for path in (diff_item.a_path, diff_item.b_path):
                if path and is_cmake_file(path):
                    cmake_changed = True
        return changed_files, "NO", composition_changed, cmake_changed
    except Exception as e:
        logger.error("Error checking Git changes: %s", e, exc_info=True)
        return [], "NO", False, False
    finally:
        try:
            if repo is not None:
                repo.close()
                time.sleep(0.2)
            safe_rmtree(temp_dir)
        except Exception as cleanup_error:
            logger.warning("Cleanup failed %s: %s", temp_dir, cleanup_error)


def check_tfvc_merge(changeset_id: int) -> Optional[str]:
    tfs_url = _tfs_url()
    try:
        changes_url = f"{tfs_url}/_apis/tfvc/changesets/{changeset_id}/changes"
        response = requests.get(
            changes_url,
            auth=_ntlm_auth(),
            params={"api-version": "2.2"},
            timeout=30,
        )
        if response.status_code != 200:
            return None
        for change in response.json().get("value", []):
            if change.get("mergeSources"):
                return change["item"]["path"]
        return None
    except Exception as e:
        logger.error("TFVC merge check failed: %s", e, exc_info=True)
        return None


def check_tfvc_changes(
    project: Project,
    last_processed_changeset: str,
    last_server_changeset: str,
) -> tuple[list[str], str, bool, bool]:
    if not last_processed_changeset:
        return ["1"], "YES", True, True

    tfs_url = _tfs_url()
    repo_path = project_repo_path(project)
    try:
        params = {
            "searchCriteria.itemPath": repo_path,
            "searchCriteria.fromId": int(last_processed_changeset),
            "searchCriteria.toId": int(last_server_changeset),
            "api-version": "2.2",
        }
        response = requests.get(
            f"{tfs_url}/_apis/tfvc/changesets",
            auth=_ntlm_auth(),
            params=params,
            timeout=60,
        )
        if response.status_code != 200:
            return [], "NO", False, False
        modified_files: list[str] = []
        composition_changed = False
        cmake_changed = False
        for changeset in response.json().get("value", []):
            cid = changeset["changesetId"]
            ch_resp = requests.get(
                f"{tfs_url}/_apis/tfvc/changesets/{cid}/changes",
                auth=_ntlm_auth(),
                params={"api-version": "2.2"},
                timeout=30,
            )
            if ch_resp.status_code != 200:
                continue
            for change in ch_resp.json().get("value", []):
                change_type = change.get("changeType", "").lower()
                item = change.get("item", {})
                path = item.get("path", "")
                source_path = change.get("sourceServerItem", "")
                clean_path = path[2:] if path.startswith("$/") else path
                clean_source = source_path[2:] if source_path.startswith("$/") else source_path
                is_c = is_c_file(clean_path) or is_c_file(clean_source)
                if is_c:
                    file_to_track = clean_path or clean_source
                    if file_to_track:
                        modified_files.append(file_to_track)
                if is_c and any(t in change_type for t in ("add", "delete", "rename")):
                    composition_changed = True
                for p in (clean_path, clean_source):
                    if is_cmake_file(p):
                        cmake_changed = True
        return modified_files, "NO", composition_changed, cmake_changed
    except Exception as e:
        logger.error("TFVC changes check failed: %s", e, exc_info=True)
        return [], "NO", False, False


def get_head_commit_git(project: Project) -> Optional[str]:
    from git import Repo

    repo_path = project_repo_path(project)
    branch = project_analysis_branch(project)
    temp_dir = os.path.join(ci_settings.CI_TEMP_DIR, f"temp_repo_{uuid.uuid4().hex[:8]}")
    os.makedirs(ci_settings.CI_TEMP_DIR, exist_ok=True)
    repo = None
    try:
        repo = Repo.clone_from(repo_path, temp_dir, no_checkout=True, branch=branch, depth=1)
        return repo.head.commit.hexsha
    except Exception as e:
        logger.error("Git HEAD failed: %s", e, exc_info=True)
        return None
    finally:
        if repo is not None:
            repo.close()
            time.sleep(0.2)
        safe_rmtree(temp_dir)


def get_latest_changeset_tfvc(project: Project) -> Optional[str]:
    tfs_url = _tfs_url()
    repo_path = project_repo_path(project)
    try:
        response = requests.get(
            f"{tfs_url}/_apis/tfvc/changesets",
            auth=_ntlm_auth(),
            params={
                "searchCriteria.itemPath": repo_path,
                "$top": 1,
                "api-version": "2.2",
            },
            timeout=30,
        )
        if response.status_code == 200:
            changesets = response.json().get("value", [])
            if changesets:
                return str(changesets[0]["changesetId"])
        return None
    except Exception as e:
        logger.error("Latest TFVC changeset failed: %s", e, exc_info=True)
        return None
