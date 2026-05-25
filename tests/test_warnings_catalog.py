"""Tests for PVS warnings catalog import parser."""

from pathlib import Path

from pvs_tracker.warnings_catalog import (
    WarningEntry,
    _dedupe_entries,
    _language_from_category,
    parse_warnings_html,
    parse_warnings_markdown,
)


FIXTURE = Path(__file__).parent / "fixtures" / "warnings_sample.md"


def test_language_from_category() -> None:
    assert _language_from_category("General Analysis (C++)") == "cpp"
    assert _language_from_category("General Analysis (C#)") == "csharp"
    assert _language_from_category("OWASP errors (Java)") == "java"


def test_parse_warnings_markdown() -> None:
    text = FIXTURE.read_text(encoding="utf-8")
    entries = parse_warnings_markdown(text)
    codes = {e.rule_code for e in entries}
    assert "V501" in codes
    assert "V3041" in codes
    assert "V001" in codes
    v501 = next(e for e in entries if e.rule_code == "V501")
    assert "Identical" in v501.name
    assert v501.language == "cpp"
    assert v501.category == "General Analysis (C++)"


def test_parse_warnings_html_list_items() -> None:
    html = """
    <h2>General Analysis (C++)</h2>
    <li>V777. Sample HTML warning.</li>
    <li>V778. Another warning.</li>
    """
    entries = parse_warnings_html(html)
    assert len(entries) == 2
    assert entries[0].rule_code == "V777"


def test_dedupe_entries() -> None:
    entries = [
        WarningEntry("V501", "A"),
        WarningEntry("V501", "B"),
    ]
    deduped = _dedupe_entries(entries)
    assert len(deduped) == 1
    assert deduped[0].name == "A"
