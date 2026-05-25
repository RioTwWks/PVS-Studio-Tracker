"""Import PVS-Studio warning catalog from official documentation."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlmodel import Session, select

from pvs_tracker.models import ErrorClassifier

logger = logging.getLogger(__name__)

WARNINGS_PAGE_URL = "https://pvs-studio.com/en/docs/warnings/"
WARNINGS_PRINT_URL = "https://pvs-studio.com/en/docs/warnings/print/"
DOC_BASE_URL = "https://pvs-studio.com/en/docs/warnings/"

RULE_LINE_RE = re.compile(r"^- (V\d+)\.\s+(.+)$", re.MULTILINE)
HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
XML_HREF_RE = re.compile(r'href=["\']([^"\']+\.xml)["\']', re.IGNORECASE)


@dataclass
class WarningEntry:
    rule_code: str
    name: str
    category: Optional[str] = None
    language: Optional[str] = None


def _language_from_category(category: str) -> str:
    lower = category.lower()
    if "c#" in lower or "csharp" in lower:
        return "csharp"
    if "java" in lower and "javascript" not in lower:
        return "java"
    if "javascript" in lower or "typescript" in lower:
        return "js"
    if "go" in lower:
        return "go"
    if "c++" in lower or "(c++)" in lower or "viva64" in lower:
        return "cpp"
    return "other"


def parse_warnings_markdown(text: str) -> list[WarningEntry]:
    """Parse markdown-style warning list from docs page text."""
    entries: list[WarningEntry] = []
    current_category: Optional[str] = None
    current_language: Optional[str] = None

    for line in text.splitlines():
        heading = HEADING_RE.match(line.strip())
        if heading:
            current_category = heading.group(1).strip()
            if current_category.lower().startswith("general analysis"):
                current_language = _language_from_category(current_category)
            elif "owasp" in current_category.lower() or "misra" in current_category.lower():
                current_language = _language_from_category(current_category)
            else:
                current_language = _language_from_category(current_category)
            continue

        rule_match = RULE_LINE_RE.match(line.strip())
        if rule_match:
            code, name = rule_match.group(1), rule_match.group(2).strip()
            entries.append(
                WarningEntry(
                    rule_code=code,
                    name=name,
                    category=current_category,
                    language=current_language,
                )
            )

    return entries


def parse_warnings_html(html: str) -> list[WarningEntry]:
    """Parse warnings from HTML: list items and section headings."""
    entries: list[WarningEntry] = []
    current_category: Optional[str] = None
    current_language: Optional[str] = None

    h2_re = re.compile(r"<h2[^>]*>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
    li_re = re.compile(r"<li[^>]*>\s*(V\d+)\.\s*(.*?)\s*</li>", re.IGNORECASE | re.DOTALL)

    pos = 0
    for h2_match in h2_re.finditer(html):
        before = html[pos : h2_match.start()]
        for li_match in li_re.finditer(before):
            code, name = li_match.group(1), re.sub(r"<[^>]+>", "", li_match.group(2)).strip()
            entries.append(
                WarningEntry(
                    rule_code=code,
                    name=name,
                    category=current_category,
                    language=current_language,
                )
            )
        raw_title = re.sub(r"<[^>]+>", "", h2_match.group(1)).strip()
        current_category = raw_title
        current_language = _language_from_category(raw_title)
        pos = h2_match.end()

    for li_match in li_re.finditer(html[pos:]):
        code, name = li_match.group(1), re.sub(r"<[^>]+>", "", li_match.group(2)).strip()
        entries.append(
            WarningEntry(
                rule_code=code,
                name=name,
                category=current_category,
                language=current_language,
            )
        )

    if not entries:
        entries = parse_warnings_markdown(html)

    return _dedupe_entries(entries)


def _dedupe_entries(entries: list[WarningEntry]) -> list[WarningEntry]:
    seen: dict[str, WarningEntry] = {}
    for entry in entries:
        if entry.rule_code not in seen:
            seen[entry.rule_code] = entry
    return list(seen.values())


def find_xml_catalog_url(html: str, base_url: str = WARNINGS_PAGE_URL) -> Optional[str]:
    match = XML_HREF_RE.search(html)
    if not match:
        return None
    href = match.group(1)
    if href.startswith("http"):
        return href
    from urllib.parse import urljoin

    return urljoin(base_url, href)


def parse_warnings_xml(xml_text: str) -> list[WarningEntry]:
    """Parse PVS warnings XML map when available."""
    entries: list[WarningEntry] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        logger.warning("Failed to parse warnings XML")
        return entries

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag.lower() in ("warning", "rule", "diagnostic", "error"):
            code = (
                elem.get("code")
                or elem.get("id")
                or elem.get("key")
                or (elem.findtext("code") if elem.find("code") is not None else None)
            )
            name = (
                elem.get("name")
                or elem.get("title")
                or elem.findtext("name")
                or elem.findtext("title")
                or elem.text
            )
            if code and name:
                code = code.strip().upper()
                if code.startswith("V"):
                    entries.append(WarningEntry(rule_code=code, name=name.strip()))
        elif elem.text and elem.text.strip().startswith("V"):
            parts = elem.text.strip().split(".", 1)
            if len(parts) == 2 and parts[0].startswith("V"):
                entries.append(WarningEntry(rule_code=parts[0].strip(), name=parts[1].strip()))

    return _dedupe_entries(entries)


async def fetch_warnings_page(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    return response.text


async def fetch_warning_entries() -> list[WarningEntry]:
    """Download and parse the full PVS warnings catalog."""
    async with httpx.AsyncClient() as client:
        html = await fetch_warnings_page(client, WARNINGS_PRINT_URL)
        xml_url = find_xml_catalog_url(html)
        if xml_url:
            try:
                xml_text = await fetch_warnings_page(client, xml_url)
                xml_entries = parse_warnings_xml(xml_text)
                if xml_entries:
                    logger.info("Loaded %d warnings from XML %s", len(xml_entries), xml_url)
                    return xml_entries
            except Exception as exc:
                logger.warning("XML catalog fetch failed: %s", exc)

        entries = parse_warnings_html(html)
        if len(entries) < 100:
            main_html = await fetch_warnings_page(client, WARNINGS_PAGE_URL)
            entries = parse_warnings_html(main_html)
        logger.info("Loaded %d warnings from HTML", len(entries))
        return entries


def fetch_warning_entries_sync() -> list[WarningEntry]:
    """Synchronous wrapper for startup import."""
    import asyncio

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, fetch_warning_entries()).result()
        return loop.run_until_complete(fetch_warning_entries())
    except RuntimeError:
        return asyncio.run(fetch_warning_entries())


def sync_warnings_catalog(session: Session) -> dict[str, Any]:
    """Fetch from pvs-studio.com and upsert classifiers."""
    from sqlalchemy import func

    entries = fetch_warning_entries_sync()
    if not entries:
        raise ValueError("No warnings parsed from PVS documentation")

    when = datetime.utcnow()
    imported = 0
    updated = 0

    for entry in entries:
        doc_url = f"{DOC_BASE_URL}#{entry.rule_code.lower()}"
        existing = session.exec(
            select(ErrorClassifier).where(ErrorClassifier.rule_code == entry.rule_code)
        ).first()

        if existing:
            changed = False
            if entry.name and existing.name != entry.name:
                existing.name = entry.name
                changed = True
            if entry.category and existing.category != entry.category:
                existing.category = entry.category
                changed = True
            if entry.language and existing.language != entry.language:
                existing.language = entry.language
                changed = True
            existing.doc_url = doc_url
            existing.synced_at = when
            if changed:
                updated += 1
            session.add(existing)
        else:
            session.add(
                ErrorClassifier(
                    rule_code=entry.rule_code,
                    type="BUG",
                    priority="MAJOR",
                    name=entry.name,
                    description="",
                    category=entry.category,
                    language=entry.language,
                    doc_url=doc_url,
                    synced_at=when,
                )
            )
            imported += 1

    session.commit()
    from sqlalchemy import func as sa_func

    total = session.exec(select(sa_func.count()).select_from(ErrorClassifier)).one()
    return {"imported": imported, "updated": updated, "total": total}
