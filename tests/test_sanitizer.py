"""Tests for the sanitizer orchestrator (uses mock detector, no model needed)."""

from __future__ import annotations

from pathlib import Path

from pi_trace_sanitizer.entity_map import EntityMap
from pi_trace_sanitizer.sanitizer import _should_scan, sanitize_session

FIXTURE = Path(__file__).parent / "fixtures" / "sample_session.jsonl"


class FakeDetector:
    """Returns canned entity detections for testing the sanitizer flow."""

    def __init__(self, detections: dict[str, list[tuple[str, str]]] | None = None):
        self._detections = detections or {}
        self.calls: list[str] = []

    def detect(self, text: str) -> list[tuple[str, str]]:
        self.calls.append(text)
        for substring, entities in self._detections.items():
            if substring in text:
                return entities
        return []


class TestShouldScan:
    def test_skips_short_text(self):
        assert not _should_scan("field", "hi")

    def test_skips_type_field(self):
        assert not _should_scan("type", "some_type_value")

    def test_skips_id_field(self):
        assert not _should_scan("id", "some-uuid-value")

    def test_skips_timestamp(self):
        assert not _should_scan("timestamp", "2026-04-08T10:00:00Z")

    def test_skips_nested_type(self):
        assert not _should_scan("message.content[0].type", "text_type_val")

    def test_skips_model(self):
        assert not _should_scan("message.model", "claude-sonnet-4-20250514")

    def test_skips_provider(self):
        assert not _should_scan("message.provider", "anthropic_value")

    def test_skips_stop_reason(self):
        assert not _should_scan("message.stopReason", "some_stop_reason")

    def test_skips_usage_prefix(self):
        assert not _should_scan("usage.input", "12345678")

    def test_allows_content_text(self):
        assert _should_scan("message.content[0].text", "Check the auth config for user")

    def test_allows_cwd(self):
        assert _should_scan("cwd", "/Users/john/workspace/project")

    def test_allows_tool_result(self):
        assert _should_scan("message.content", "db_url: postgresql://admin:pass@host/db")


class TestSanitizeSession:
    def test_dry_run_no_output(self, tmp_path):
        detector = FakeDetector()
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        summary = sanitize_session(
            FIXTURE, out, detector, entity_map, dry_run=True
        )
        assert not out.exists()
        assert summary["events"] == 8
        assert summary["output"] is None

    def test_writes_output(self, tmp_path):
        detector = FakeDetector()
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        summary = sanitize_session(FIXTURE, out, detector, entity_map)
        assert out.exists()
        lines = out.read_text().strip().split("\n")
        assert len(lines) == 8

    def test_detector_called_for_scannable_fields(self, tmp_path):
        detector = FakeDetector()
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        sanitize_session(FIXTURE, out, detector, entity_map)
        assert len(detector.calls) > 0

    def test_detector_not_called_for_skip_fields(self, tmp_path):
        """Fields like type, id, timestamp should not be sent to the detector."""
        detector = FakeDetector()
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        sanitize_session(FIXTURE, out, detector, entity_map)
        for call_text in detector.calls:
            assert call_text != "session"
            assert call_text != "message"
            assert call_text != "model_change"

    def test_detections_applied_in_output(self, tmp_path):
        detector = FakeDetector({
            "sarah.chen@nvidia.com": [
                ("EMAIL", "sarah.chen@nvidia.com"),
                ("PERSON", "Sarah Chen"),
            ],
        })
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        summary = sanitize_session(FIXTURE, out, detector, entity_map)
        content = out.read_text()
        assert "sarah.chen@nvidia.com" not in content
        assert "[EMAIL_1]" in content
        assert summary["entities_found"] > 0

    def test_user_path_normalization_in_output(self, tmp_path):
        detector = FakeDetector({
            "/Users/john.smith/": [
                ("USER_PATH", "/Users/john.smith/"),
            ],
        })
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        sanitize_session(FIXTURE, out, detector, entity_map)
        content = out.read_text()
        assert "/Users/john.smith/" not in content
        assert "/Users/user/" in content

    def test_entity_map_save_load_across_sessions(self, tmp_path):
        """Entity map saved after one session produces consistent placeholders."""
        detector = FakeDetector({
            "sarah.chen@nvidia.com": [("EMAIL", "sarah.chen@nvidia.com")],
        })
        entity_map = EntityMap()
        map_path = tmp_path / "map.json"
        out1 = tmp_path / "out1.jsonl"
        sanitize_session(FIXTURE, out1, detector, entity_map)
        entity_map.save(map_path)

        loaded_map = EntityMap.load(map_path)
        out2 = tmp_path / "out2.jsonl"
        sanitize_session(FIXTURE, out2, FakeDetector({
            "sarah.chen@nvidia.com": [("EMAIL", "sarah.chen@nvidia.com")],
        }), loaded_map)

        assert out1.read_text() == out2.read_text()

    def test_progress_callback(self, tmp_path):
        events_received: list = []
        detector = FakeDetector({
            "sarah.chen@nvidia.com": [("EMAIL", "sarah.chen@nvidia.com")],
        })
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        sanitize_session(
            FIXTURE, out, detector, entity_map,
            on_progress=events_received.append,
        )
        type_names = {type(e).__name__ for e in events_received}
        assert "SessionStart" in type_names
        assert "SessionDone" in type_names
        assert "Detection" in type_names

    def test_summary_counts(self, tmp_path):
        detector = FakeDetector({
            "sarah.chen@nvidia.com": [("EMAIL", "sarah.chen@nvidia.com")],
        })
        entity_map = EntityMap()
        out = tmp_path / "out.jsonl"
        summary = sanitize_session(FIXTURE, out, detector, entity_map)
        assert summary["events"] == 8
        assert summary["fields_scanned"] > 0
        assert summary["unique_entities"] >= 1
        assert len(summary["detections"]) >= 1
