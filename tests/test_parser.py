"""Tests for the JSONL parser and string walker."""

import json
import tempfile
from pathlib import Path

from pi_trace_sanitizer.parser import (
    extract_text_fields,
    mutate_strings,
    read_session,
    walk_strings,
    write_session,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


def test_read_session_returns_all_events():
    events = read_session(FIXTURE)
    assert len(events) == 8
    assert events[0]["type"] == "session"
    assert events[3]["type"] == "message"


def test_write_read_roundtrip(tmp_path):
    events = read_session(FIXTURE)
    out = tmp_path / "out.jsonl"
    write_session(events, out)
    reloaded = read_session(out)
    assert len(reloaded) == len(events)
    for orig, new in zip(events, reloaded):
        assert orig == new


def test_walk_strings_finds_nested_text():
    event = {
        "type": "message",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": "hello world"}],
        },
    }
    results = walk_strings(event)
    paths = [r[0] for r in results]
    values = [r[1] for r in results]
    assert "message.content[0].text" in paths
    assert "hello world" in values


def test_walk_strings_skips_image_data():
    event = {
        "type": "message",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "mimeType": "image/png",
                    "data": "x" * 500,
                },
                {"type": "text", "text": "caption"},
            ],
        },
    }
    results = walk_strings(event)
    values = [r[1] for r in results]
    assert "x" * 500 not in values
    assert "caption" in values
    assert "image/png" in values


def test_walk_strings_includes_short_data_field():
    """data fields shorter than threshold should NOT be skipped."""
    event = {"data": "short", "mimeType": "image/png"}
    results = walk_strings(event)
    values = [r[1] for r in results]
    assert "short" in values


def test_mutate_strings_replaces_in_place():
    event = {
        "type": "session",
        "cwd": "/Users/john.smith/project",
        "id": "abc123",
    }
    mutate_strings(event, lambda path, text: text.replace("john.smith", "user"))
    assert event["cwd"] == "/Users/user/project"
    assert event["id"] == "abc123"


def test_extract_text_fields_on_fixture():
    events = read_session(FIXTURE)
    session_event = events[0]
    fields = extract_text_fields(session_event)
    paths = [p for p, _ in fields]
    assert "cwd" in paths
    assert "id" in paths


def test_image_data_skipped_in_fixture():
    """The fixture's image event should have its data blob skipped."""
    events = read_session(FIXTURE)
    image_event = events[-1]
    fields = extract_text_fields(image_event)
    values = [v for _, v in fields]
    assert not any(len(v) > 300 and "AAAA" in v for v in values)
    assert "Here's a screenshot of the dashboard" in values
