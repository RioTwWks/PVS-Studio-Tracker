"""Unit tests for commit metadata parsing."""

import pytest

from pvs_tracker.upload_metadata import merge_commit_upload_fields, parse_commit_metadata_bytes


def _strip(value: str | None) -> str | None:
    if value is None:
        return None
    s = value.strip()
    return s or None


def test_parse_commit_metadata_bytes() -> None:
    raw = b'{"commit": "abc", "commit_author_name": "Dev", "extra": "ignored"}'
    assert parse_commit_metadata_bytes(raw) == {
        "commit": "abc",
        "commit_author_name": "Dev",
    }


def test_parse_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parse_commit_metadata_bytes(b"[]")


def test_parse_release_version() -> None:
    raw = b'{"release_version": "8.10.3"}'
    assert parse_commit_metadata_bytes(raw) == {"release_version": "8.10.3"}


def test_merge_form_overrides_metadata() -> None:
    merged = merge_commit_upload_fields(
        commit="form-sha",
        commit_author_name=None,
        commit_author_email="form@example.com",
        metadata={
            "commit": "meta-sha",
            "commit_author_name": "Meta",
            "commit_author_email": "meta@example.com",
        },
        optional_form=_strip,
    )
    assert merged["commit"] == "form-sha"
    assert merged["commit_author_name"] == "Meta"
    assert merged["commit_author_email"] == "form@example.com"
