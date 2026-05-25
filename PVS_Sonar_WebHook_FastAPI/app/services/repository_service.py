"""
Repository service for Git and TFVC operations.

Handles:
- Git repository operations (clone, diff, changes detection)
- TFVC repository operations (changeset queries, merge detection)
- C/C++/C# file change detection
- CMake file change detection
"""

import os
import shutil
import stat
import time
import uuid
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from git import Repo
import requests
from requests_ntlm import HttpNtlmAuth

from app.logging_config import get_logger
from app.config import settings

logger = get_logger(__name__)


# C/C++/C# file extensions
C_EXTENSIONS = {'.c', '.cpp', '.cc', '.cxx', '.h', '.hpp', '.hh', '.hxx', '.cs'}

# CMake file patterns
CMAKE_PATTERNS = {'CMakeLists.txt', 'CMakePresets.json', 'CUserMakePresets.json'}
CMAKE_EXTENSIONS = {'.cmake'}


def remove_readonly(func, path, _):
    """Callback to remove read-only attribute for shutil.rmtree."""
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def safe_rmtree(path: str, max_retries: int = 3):
    """
    Safely remove a directory with retries on Windows.
    
    On Windows, git may hold file locks briefly after operations.
    This function retries deletion with small delays.
    
    Args:
        path: Directory path to remove
        max_retries: Maximum number of retry attempts
    """
    for attempt in range(max_retries):
        try:
            if os.path.exists(path):
                # First attempt with onerror callback
                shutil.rmtree(path, onerror=remove_readonly)
                logger.info(f"Temporary repository removed: {path}")
                return
        except Exception:
            if attempt < max_retries - 1:
                # Wait before retry (git may still hold locks)
                time.sleep(0.5)
            else:
                # Last attempt - log warning but don't fail
                logger.warning(f"Could not remove temporary directory: {path}")
                return


def is_c_file(path: str) -> bool:
    """
    Check if file path has C/C++/C# extension.
    
    Args:
        path: File path to check
        
    Returns:
        True if file is C/C++/C#, False otherwise
    """
    if not path:
        return False
    ext = os.path.splitext(path)[1].lower()
    return ext in C_EXTENSIONS


def is_cmake_file(path: str) -> bool:
    """
    Check if file path is a CMake file.
    
    Args:
        path: File path to check
        
    Returns:
        True if file is CMake-related, False otherwise
    """
    if not path:
        return False
    
    basename = os.path.basename(path)
    ext = os.path.splitext(path)[1].lower()
    
    return basename in CMAKE_PATTERNS or ext in CMAKE_EXTENSIONS


def check_git_changes(
    project,
    last_processed_commit: str,
    last_server_commit: str
) -> Tuple[List[str], str, bool, bool]:
    """
    Check for C/C++/C# changes in Git repository.
    
    Args:
        project: Project object with tfs_path and another_branch
        last_processed_commit: Last processed commit hash
        last_server_commit: Current server commit hash
        
    Returns:
        Tuple of (changed_files, first_scan_flag, composition_changed, cmake_changed)
    """
    logger.info(f"Checking Git changes from {last_processed_commit} to {last_server_commit}")

    # First scan - no previous commit
    if not last_processed_commit:
        logger.info("First scan - no previous commit")
        return ['1'], "YES", True, True

    # Use unique temp directory to avoid conflicts on concurrent calls
    temp_dir = f"temp_repo_{uuid.uuid4().hex[:8]}"
    repo = None

    try:
        # Clone repository without checkout
        repo = Repo.clone_from(
            project.tfs_path,
            temp_dir,
            no_checkout=True,
            branch=project.another_branch
        )
        
        # Get commit objects
        last_processed = repo.commit(last_processed_commit)
        last_server = repo.commit(last_server_commit)
        
        # Get diff between commits
        diff = last_processed.diff(last_server)
        
        # Analyze changes
        changed_files = []
        composition_changed = False
        cmake_changed = False
        
        for diff_item in diff:
            # Check for C/C++/C# files
            is_c = False
            for path in [diff_item.a_path, diff_item.b_path]:
                if path and is_c_file(path):  # Added None check
                    is_c = True
                    changed_files.append(path)

            # Check for composition changes (add/delete/rename)
            if is_c and (diff_item.new_file or diff_item.deleted_file or diff_item.renamed):
                composition_changed = True

            # Check for CMake changes
            for path in [diff_item.a_path, diff_item.b_path]:
                if path and is_cmake_file(path):  # Added None check
                    cmake_changed = True
        
        logger.info(f"C/C++/C# files changed: {changed_files}")
        logger.info(f"Composition changed: {composition_changed}, CMake changed: {cmake_changed}")

        return changed_files, "NO", composition_changed, cmake_changed

    except Exception as e:
        logger.error(f"Error checking Git changes: {e}", exc_info=True)
        return [], "NO", False, False
    finally:
        # Cleanup - always executed even on error
        try:
            if repo is not None:
                repo.close()
                # Small delay to let git release file locks on Windows
                time.sleep(0.2)
            safe_rmtree(temp_dir)
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup {temp_dir}: {cleanup_error}")


def check_tfvc_merge(changeset_id: int) -> Optional[str]:
    """
    Check if changeset contains merge from another branch.
    
    Args:
        changeset_id: TFVC changeset ID
        
    Returns:
        Folder path if merge detected, None otherwise
    """
    logger.info(f"Checking for merge in changeset {changeset_id}")
    
    tfs_url = "http://qtfs:8080/tfs/QUIK"
    
    try:
        # Get changeset details
        changes_url = f"{tfs_url}/_apis/tfvc/changesets/{changeset_id}/changes"
        changes_params = {"api-version": "2.2"}
        
        response = requests.get(
            changes_url,
            auth=HttpNtlmAuth(settings.WEBHOOK_USERNAME, settings.WEBHOOK_PASSWORD),
            params=changes_params
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to get changes for changeset {changeset_id}")
            return None
        
        changes = response.json().get("value", [])
        
        for change in changes:
            if change.get("mergeSources") and len(change["mergeSources"]) > 0:
                folder_path = change["item"]["path"]
                logger.info(f"Found merge source in changeset {changeset_id}: {folder_path}")
                return folder_path
        
        logger.info(f"No merge sources found in changeset {changeset_id}")
        return None
        
    except Exception as e:
        logger.error(f"Error checking TFVC merge: {e}", exc_info=True)
        return None


def check_tfvc_changes(project, last_processed_changeset: str, last_server_changeset: str, branch: str = None) -> Tuple[List[str], str, bool, bool]:
    """
    Check for C/C++/C# changes in TFVC repository.
    
    Args:
        project: Project object with tfs_path
        last_processed_changeset: Last processed changeset ID
        last_server_changeset: Current server changeset ID
        
    Returns:
        Tuple of (changed_files, first_scan_flag, composition_changed, cmake_changed)
    """
    logger.info(f"Checking TFVC changes from {last_processed_changeset} to {last_server_changeset}")
    
    # First scan - no previous changeset
    if not last_processed_changeset:
        logger.info("First scan - no previous changeset")
        return ['1'], "YES", True, True
    
    tfs_url = "http://qtfs:8080/tfs/QUIK"
    
    try:
        # Get changesets in range
        params = {
            "searchCriteria.itemPath": f"{project.tfs_path}",
            "searchCriteria.fromId": int(last_processed_changeset),
            "searchCriteria.toId": int(last_server_changeset),
            "api-version": "2.2"
        }
        
        changeset_url = f"{tfs_url}/_apis/tfvc/changesets"
        response = requests.get(
            changeset_url,
            auth=HttpNtlmAuth(settings.WEBHOOK_USERNAME, settings.WEBHOOK_PASSWORD),
            params=params
        )
        
        if response.status_code != 200:
            logger.error(f"Failed to get changesets")
            return [], "NO", False, False
        
        changesets = response.json().get("value", [])
        logger.info(f"Found {len(changesets)} changesets")
        
        modified_files = []
        composition_changed = False
        cmake_changed = False
        
        # Analyze each changeset
        for changeset in changesets:
            changeset_id = changeset["changesetId"]
            logger.debug(f"Processing changeset {changeset_id}")
            
            # Get changeset details
            changes_url = f"{tfs_url}/_apis/tfvc/changesets/{changeset_id}/changes"
            changes_params = {"api-version": "2.2"}
            changes_response = requests.get(
                changes_url,
                auth=HttpNtlmAuth(settings.WEBHOOK_USERNAME, settings.WEBHOOK_PASSWORD),
                params=changes_params
            )
            
            if changes_response.status_code != 200:
                logger.error(f"Failed to get changes for changeset {changeset_id}")
                continue
            
            changes = changes_response.json().get("value", [])
            
            # Analyze changes
            for change in changes:
                change_type = change.get("changeType", "").lower()
                item = change.get("item", {})
                path = item.get("path", "")
                source_path = change.get("sourceServerItem", "")
                
                # Clean paths
                clean_path = path[2:] if path.startswith("$/") else path
                clean_source_path = source_path[2:] if source_path.startswith("$/") else source_path
                
                # Check for C/C++/C# files
                is_c = is_c_file(clean_path) or is_c_file(clean_source_path)

                if is_c:
                    # Use clean_path if available, otherwise use clean_source_path (for deletes)
                    file_to_track = clean_path if clean_path else clean_source_path
                    if file_to_track:
                        modified_files.append(file_to_track)

                # Check for composition changes
                if is_c and any(t in change_type for t in ("add", "delete", "rename")):
                    composition_changed = True
                
                # Check for CMake changes
                for p in [clean_path, clean_source_path]:
                    if is_cmake_file(p):
                        cmake_changed = True
        
        logger.info(f"Modified files: {modified_files}")
        logger.info(f"Composition changed: {composition_changed}, CMake changed: {cmake_changed}")
        
        return modified_files, "NO", composition_changed, cmake_changed
        
    except Exception as e:
        logger.error(f"Error checking TFVC changes: {e}", exc_info=True)
        return [], "NO", False, False


def get_commit_author_git(project) -> Tuple[Optional[str], Optional[str]]:
    """
    Get author name and email of a Git commit.
        
    Returns:
        Tuple of (author_name, author_email), or (None, None) on error
    """
    logger.info(f"Getting commit author from {project.last_processed_changeset}")

    # Early exit if no changeset
    if not getattr(project, 'last_processed_changeset', None):
        logger.warning("No last processed changeset to get author from")
        return None, None

    temp_dir = f"temp_repo_{uuid.uuid4().hex[:8]}"
    repo = None

    try:
        repo = Repo.clone_from(
            project.tfs_path,
            temp_dir,
            no_checkout=True,
            branch=project.another_branch
        )

        last_processed = repo.commit(project.last_processed_changeset)
        author_name = getattr(last_processed.author, 'name', None)
        author_email = getattr(last_processed.author, 'email', None)

        logger.info(f"Last processed commit author: {author_name} <{author_email}>")
        return author_name, author_email

    except Exception as e:
        logger.error(f"Error getting commit author: {e}", exc_info=True)
        return None, None
    finally:
        try:
            if repo is not None:
                repo.close()
                time.sleep(0.2)
            safe_rmtree(temp_dir)  # реализация safe_rmtree должна быть определена
        except Exception as cleanup_error:
            logger.warning(f"Failed to cleanup {temp_dir}: {cleanup_error}")


def get_tfvc_changeset_author(project: int) -> Tuple[Optional[str], Optional[str]]:
    """
    Get author name and email of a TFVC changeset.
        
    Returns:
        Tuple of (author_name, author_email), or (None, None) on error
    """
    logger.info(f"Getting author for changeset {project.last_processed_changeset}")
    tfs_url = "http://qtfs:8080/tfs/QUIK"
    
    try:
        # GET changeset details
        url = f"{tfs_url}/_apis/tfvc/changesets/{project.last_processed_changeset}"
        params = {"api-version": "2.2"}
        
        response = requests.get(
            url,
            auth=HttpNtlmAuth(settings.WEBHOOK_USERNAME, settings.WEBHOOK_PASSWORD),
            params=params
        )
        
        if response.status_code != 200:
            logger.error(
                f"Failed to get changeset {project.last_processed_changeset}: HTTP {response.status_code}"
            )
            return None, None
        
        changeset = response.json()
        author = changeset.get("author", {})
        author_name = author.get("displayName")
        author_email = author.get("uniqueName")  # usually email
        
        logger.info(
            f"Changeset {project.last_processed_changeset} author: {author_name} <{author_email}>"
        )
        return author_name, author_email
        
    except Exception as e:
        logger.error(
            f"Error getting TFVC changeset author: {e}", exc_info=True
        )
        return None, None


def get_head_commit_git(project) -> Optional[str]:
    """
    Получить хэш HEAD-коммита для Git-репозитория проекта.
    Использует shallow clone (depth=1) для скорости.
    """
    import uuid
    import time
    from git import Repo

    temp_dir = f"temp_repo_{uuid.uuid4().hex[:8]}"
    repo = None
    try:
        repo = Repo.clone_from(
            project.tfs_path,
            temp_dir,
            no_checkout=True,
            branch=project.another_branch,
            depth=1
        )
        head_commit = repo.head.commit.hexsha
        logger.info(f"HEAD commit для {project.sonar_project_name}: {head_commit}")
        return head_commit
    except Exception as e:
        logger.error(f"Ошибка получения HEAD коммита Git: {e}", exc_info=True)
        return None
    finally:
        if repo is not None:
            repo.close()
            time.sleep(0.2)
        safe_rmtree(temp_dir)


def get_latest_changeset_tfvc(project) -> Optional[str]:
    """
    Получить номер последнего changeset для TFVC-пути проекта.
    Использует TFS REST API.
    """
    import requests
    from requests_ntlm import HttpNtlmAuth
    from app.config import settings

    tfs_url = "http://qtfs:8080/tfs/QUIK"
    url = f"{tfs_url}/_apis/tfvc/changesets"
    params = {
        "searchCriteria.itemPath": project.tfs_path,
        "$top": 1,
        "api-version": "2.2"
    }
    try:
        response = requests.get(
            url,
            auth=HttpNtlmAuth(settings.WEBHOOK_USERNAME, settings.WEBHOOK_PASSWORD),
            params=params,
            timeout=30
        )
        if response.status_code == 200:
            data = response.json()
            changesets = data.get("value", [])
            if changesets:
                latest_id = changesets[0]["changesetId"]
                logger.info(f"Последний changeset для {project.tfs_path}: {latest_id}")
                return str(latest_id)
            else:
                logger.warning(f"Не найдено changeset'ов для {project.tfs_path}")
                return None
        else:
            logger.error(f"Ошибка получения последнего changeset: HTTP {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Ошибка при получении последнего changeset: {e}", exc_info=True)
        return None
