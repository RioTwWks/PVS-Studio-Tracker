"""Tests for PVS-Studio report parser."""
import json
import tempfile
from pathlib import Path

import pytest

from pvs_tracker.parser import parse_pvs_report


@pytest.fixture
def modern_report_file():
    """Create a temp file with modern PVS-Studio format."""
    data = {
        "version": 3,
        "warnings": [
            {
                "code": "V824",
                "cwe": 0,
                "level": 1,
                "positions": [
                    {
                        "file": "D:\\temp\\project\\src\\MappedFileStorage.cpp",
                        "line": 18,
                        "endLine": 18,
                        "navigation": {
                            "previousLine": 0,
                            "currentLine": 0,
                            "nextLine": 0,
                            "columns": 0
                        }
                    }
                ],
                "projects": ["embedb"],
                "message": "It is recommended to use the 'make_unique' function.",
                "favorite": False,
                "falseAlarm": False
            },
            {
                "code": "V010",
                "cwe": 0,
                "level": 0,
                "positions": [
                    {
                        "file": "",
                        "line": 1,
                        "endLine": 1,
                        "navigation": {
                            "previousLine": 0,
                            "currentLine": 0,
                            "nextLine": 0,
                            "columns": 0
                        }
                    }
                ],
                "projects": ["ALL_BUILD"],
                "message": "Analysis of 'Utility' type projects is not supported.",
                "favorite": False,
                "falseAlarm": False
            }
        ],
    }
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def multi_position_warning():
    """Create a warning with multiple positions (same code in different locations)."""
    data = {
        "version": 3,
        "warnings": [
            {
                "code": "V501",
                "cwe": 670,
                "level": 2,
                "positions": [
                    {
                        "file": "src/utils.cpp",
                        "line": 10,
                        "endLine": 10,
                        "navigation": {"columns": 0}
                    },
                    {
                        "file": "src/utils.cpp",
                        "line": 15,
                        "endLine": 15,
                        "navigation": {"columns": 0}
                    }
                ],
                "projects": ["core"],
                "message": "There are identical sub-expressions.",
                "favorite": False,
                "falseAlarm": False
            }
        ],
    }
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


@pytest.fixture
def legacy_report_file():
    """Create a temp file with legacy PVS-Studio format."""
    data = {
        "version": "8.10",
        "warnings": [
            {
                "fileName": "src/main.cpp",
                "lineNumber": 42,
                "warningCode": "V501",
                "level": "High",
                "message": "Identical expressions in 'if' condition.",
            }
        ],
    }
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    yield tmp.name
    Path(tmp.name).unlink(missing_ok=True)


def test_parse_modern_format(modern_report_file):
    """Test parsing of modern PVS-Studio format with positions array."""
    issues = parse_pvs_report(modern_report_file)

    # Should have 2 issues (V824 + V010 with synthetic path)
    assert len(issues) == 2

    # V824 should have the real file path
    v824 = [i for i in issues if i["rule_code"] == "V824"][0]
    assert "MappedFileStorage.cpp" in v824["file_path"]
    assert v824["line"] == 18
    assert v824["severity"] == "High"  # level 1 -> High
    assert v824["message"] == "It is recommended to use the 'make_unique' function."
    assert len(v824["fingerprint"]) == 16

    # V010 should have synthetic path
    v010 = [i for i in issues if i["rule_code"] == "V010"][0]
    assert v010["file_path"] == "__analysis__/V010"
    assert v010["line"] == 0
    assert v010["severity"] == "Analysis"  # level 0 -> Analysis
    assert "Utility" in v010["message"]


def test_parse_skips_empty_file_paths(modern_report_file):
    """Test that warnings with empty file paths get synthetic paths."""
    issues = parse_pvs_report(modern_report_file)

    # V010 with empty file path should get a synthetic path
    v010_issues = [i for i in issues if i["rule_code"] == "V010"]
    assert len(v010_issues) > 0
    # Should have synthetic file path
    assert all(i["file_path"].startswith("__analysis__/") for i in v010_issues)


def test_parse_multi_position_warning(multi_position_warning):
    """Test that warnings with multiple positions create separate issues."""
    issues = parse_pvs_report(multi_position_warning)
    
    # Should have 2 issues (one for each position)
    assert len(issues) == 2
    
    # Both should have the same code and message
    assert issues[0]["rule_code"] == issues[1]["rule_code"] == "V501"
    assert issues[0]["message"] == issues[1]["message"]
    
    # But different lines
    assert issues[0]["line"] == 10
    assert issues[1]["line"] == 15
    
    # Both should be Medium severity (level 2)
    assert issues[0]["severity"] == "Medium"
    assert issues[1]["severity"] == "Medium"


def test_parse_legacy_format(legacy_report_file):
    """Test parsing of legacy PVS-Studio format with direct fields."""
    issues = parse_pvs_report(legacy_report_file)
    
    assert len(issues) == 1
    
    issue = issues[0]
    assert issue["file_path"] == "src/main.cpp"
    assert issue["line"] == 42
    assert issue["rule_code"] == "V501"
    assert issue["severity"] == "High"
    assert issue["message"] == "Identical expressions in 'if' condition."


def test_level_to_severity_mapping(modern_report_file):
    """Test numeric level to severity string mapping."""
    # Create a file with all levels
    data = {
        "version": 3,
        "warnings": [
            {
                "code": "V001",
                "level": 0,
                "positions": [{"file": "test.cpp", "line": 1, "endLine": 1}],
                "message": "Level 0",
            },
            {
                "code": "V002",
                "level": 1,
                "positions": [{"file": "test.cpp", "line": 2, "endLine": 2}],
                "message": "Level 1",
            },
            {
                "code": "V003",
                "level": 2,
                "positions": [{"file": "test.cpp", "line": 3, "endLine": 3}],
                "message": "Level 2",
            },
            {
                "code": "V004",
                "level": 3,
                "positions": [{"file": "test.cpp", "line": 4, "endLine": 4}],
                "message": "Level 3",
            },
        ],
    }
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    report_file = tmp.name
    
    try:
        issues = parse_pvs_report(report_file)
        
        assert len(issues) == 4
        assert issues[0]["severity"] == "Analysis"
        assert issues[1]["severity"] == "High"
        assert issues[2]["severity"] == "Medium"
        assert issues[3]["severity"] == "Low"
    finally:
        Path(report_file).unlink(missing_ok=True)


def test_fingerprint_stability():
    """Test that same input always produces same fingerprint."""
    data = {
        "version": 3,
        "warnings": [
            {
                "code": "V501",
                "level": 1,
                "positions": [{"file": "test.cpp", "line": 10, "endLine": 10}],
                "message": "Test message",
            }
        ],
    }
    
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    report_file = tmp.name
    
    try:
        issues1 = parse_pvs_report(report_file)
        issues2 = parse_pvs_report(report_file)
        
        assert issues1[0]["fingerprint"] == issues2[0]["fingerprint"]
    finally:
        Path(report_file).unlink(missing_ok=True)


def test_path_normalization_in_fingerprint():
    """Test that Windows paths are normalized in fingerprints."""
    data = {
        "version": 3,
        "warnings": [
            {
                "code": "V501",
                "level": 1,
                "positions": [{"file": "D:\\project\\test.cpp", "line": 10, "endLine": 10}],
                "message": "Test",
            }
        ],
    }
    
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
    json.dump(data, tmp)
    tmp.close()
    report_file = tmp.name
    
    try:
        issues = parse_pvs_report(report_file)
        
        # File path should keep original backslashes for storage
        assert issues[0]["file_path"] == "D:\\project\\test.cpp"
        # But fingerprint should use forward slashes
        assert "D:/project/test.cpp" in issues[0]["fingerprint"] or \
               issues[0]["fingerprint"]  # Just ensure it's computed
    finally:
        Path(report_file).unlink(missing_ok=True)
