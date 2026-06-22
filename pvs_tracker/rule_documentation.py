"""Fetch and sanitize PVS-Studio rule documentation for the Issues UI."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from html import unescape

import httpx

from pvs_tracker.models import ErrorClassifier, Issue

logger = logging.getLogger(__name__)

RULE_DOC_BASE_URL = "https://pvs-studio.com/en/docs/warnings"
_FETCH_TIMEOUT = 30.0

_END_MARKERS = (
    "Was this page helpful",
    '<div class="content-feedback',
    'class="b-docs__pagination',
    "<footer",
)


def normalize_rule_code(rule_code: str) -> str:
    code = (rule_code or "").strip().upper()
    if code and not code.startswith("V"):
        code = f"V{code}"
    return code


def rule_documentation_url(rule_code: str) -> str:
    code = normalize_rule_code(rule_code)
    if not code:
        return f"{RULE_DOC_BASE_URL}/"
    return f"{RULE_DOC_BASE_URL}/{code.lower()}/"


def resolve_issue_classifier(
    issue: Issue,
    classifiers_by_id: dict[int, ErrorClassifier],
    classifiers_by_code: dict[str, ErrorClassifier],
) -> ErrorClassifier | None:
    """Resolve classifier by FK, falling back to rule_code lookup."""
    if issue.classifier_id:
        clf = classifiers_by_id.get(issue.classifier_id)
        if clf:
            return clf
    code = normalize_rule_code(issue.rule_code)
    if code:
        return classifiers_by_code.get(code)
    return None


def build_classifier_maps(
    classifiers: list[ErrorClassifier],
) -> tuple[dict[int, ErrorClassifier], dict[str, ErrorClassifier]]:
    by_id = {c.id: c for c in classifiers if c.id is not None}
    by_code: dict[str, ErrorClassifier] = {}
    for clf in classifiers:
        code = normalize_rule_code(clf.rule_code)
        if code:
            by_code.setdefault(code, clf)
    return by_id, by_code


def _strip_unsafe_html(fragment: str) -> str:
    fragment = re.sub(r"<script\b[^>]*>.*?</script>", "", fragment, flags=re.DOTALL | re.IGNORECASE)
    fragment = re.sub(r"<style\b[^>]*>.*?</style>", "", fragment, flags=re.DOTALL | re.IGNORECASE)
    fragment = re.sub(r"<(iframe|object|embed|form)\b[^>]*>.*?</\1>", "", fragment, flags=re.DOTALL | re.IGNORECASE)
    fragment = re.sub(r"\s+on\w+\s*=\s*['\"][^'\"]*['\"]", "", fragment, flags=re.IGNORECASE)
    return fragment.strip()


def extract_rule_documentation_html(page_html: str) -> str | None:
    """Extract main documentation body from a PVS rule page."""
    h1_match = re.search(r"<h1\b[^>]*>.*?</h1>", page_html, flags=re.DOTALL | re.IGNORECASE)
    if not h1_match:
        return None

    start = h1_match.start()
    end = len(page_html)
    for marker in _END_MARKERS:
        pos = page_html.find(marker, start)
        if pos != -1:
            end = min(end, pos)

    fragment = page_html[start:end]
    fragment = _strip_unsafe_html(fragment)
    if not re.search(r"<p\b", fragment, flags=re.IGNORECASE):
        return None
    return fragment


@lru_cache(maxsize=512)
def _fetch_rule_documentation_cached(rule_code: str) -> tuple[str | None, str | None]:
    """Returns (html_fragment, error_message)."""
    code = normalize_rule_code(rule_code)
    if not code:
        return None, "Rule code is empty"

    url = rule_documentation_url(code)
    try:
        with httpx.Client(follow_redirects=True, timeout=_FETCH_TIMEOUT) as client:
            response = client.get(url)
            response.raise_for_status()
            html_text = response.text
    except Exception as exc:
        logger.warning("Failed to fetch rule documentation for %s: %s", code, exc)
        return None, f"Documentation unavailable ({exc})"

    fragment = extract_rule_documentation_html(html_text)
    if not fragment:
        meta = re.search(
            r'<meta\s+name="description"\s+content="([^"]+)"',
            html_text,
            flags=re.IGNORECASE,
        )
        if meta:
            return f"<p>{unescape(meta.group(1))}</p>", None
        return None, "Documentation section not found on PVS site"

    return fragment, None


async def fetch_rule_documentation(rule_code: str) -> tuple[str | None, str | None]:
    """Async wrapper around cached sync fetch (runs in thread pool if needed)."""
    import asyncio

    return await asyncio.to_thread(_fetch_rule_documentation_cached, normalize_rule_code(rule_code))
