"""Tests for PVS rule documentation fetch and classifier resolution."""

from pvs_tracker.models import ErrorClassifier, Issue
from pvs_tracker.rule_documentation import (
    build_classifier_maps,
    extract_rule_documentation_html,
    normalize_rule_code,
    resolve_issue_classifier,
    rule_documentation_url,
)

SAMPLE_DOC_HTML = """
<div class="b-docs__content">
  <div class="content">
    <h1>V501. Identical sub-expressions to the left and to the right of 'foo' operator.</h1>
    <p>The analyzer found a code fragment that most probably has a logic error.</p>
    <pre class="err"><code class="cpp">if (a.x != 0 && a.x != 0)</code></pre>
    <p>Correct code:</p>
    <pre class="norm"><code class="cpp">if (a.x != 0 && a.y != 0)</code></pre>
    Was this page helpful?
  </div>
</div>
"""


def test_normalize_rule_code() -> None:
    assert normalize_rule_code("v501") == "V501"
    assert normalize_rule_code("501") == "V501"


def test_rule_documentation_url() -> None:
    assert rule_documentation_url("V501") == "https://pvs-studio.com/en/docs/warnings/v501/"


def test_extract_rule_documentation_html() -> None:
    fragment = extract_rule_documentation_html(SAMPLE_DOC_HTML)
    assert fragment is not None
    assert "logic error" in fragment
    assert "a.x != 0" in fragment
    assert "Was this page helpful" not in fragment


def test_resolve_issue_classifier_by_rule_code() -> None:
    clf = ErrorClassifier(id=1, rule_code="V501", type="BUG", priority="MAJOR", name="Test")
    by_id, by_code = build_classifier_maps([clf])
    issue = Issue(
        id=10,
        run_id=1,
        fingerprint="fp",
        file_path="a.cpp",
        line=1,
        rule_code="V501",
        severity="High",
        message="msg",
        classifier_id=None,
    )
    resolved = resolve_issue_classifier(issue, by_id, by_code)
    assert resolved is not None
    assert resolved.rule_code == "V501"
