"""Tests for the detector module (parsing logic and cache, no model needed)."""

from pi_trace_sanitizer.detector import DetectionCache, _parse_entities


class TestParseEntities:
    def test_parses_standard_output(self):
        raw = "PERSON: John Smith\nEMAIL: john@corp.com"
        source = "Contact John Smith at john@corp.com"
        result = _parse_entities(raw, source, strip_thinking=False)
        assert ("PERSON", "John Smith") in result
        assert ("EMAIL", "john@corp.com") in result

    def test_strips_thinking_block(self):
        raw = "<think>\nLet me analyze...\n</think>\nPERSON: Alice"
        source = "From Alice"
        result = _parse_entities(raw, source, strip_thinking=True)
        assert ("PERSON", "Alice") in result

    def test_returns_empty_for_none(self):
        assert _parse_entities("NONE", "some text", strip_thinking=False) == []

    def test_returns_empty_for_none_with_thinking(self):
        raw = "<think>analysis</think>\nNONE"
        assert _parse_entities(raw, "some text", strip_thinking=True) == []

    def test_skips_entity_not_in_source(self):
        raw = "PERSON: Bob"
        source = "Hello Alice"
        result = _parse_entities(raw, source, strip_thinking=False)
        assert len(result) == 0

    def test_skips_short_entities(self):
        raw = "PERSON: Jo"
        source = "Hi Jo"
        result = _parse_entities(raw, source, strip_thinking=False)
        assert len(result) == 0

    def test_skips_allowlisted_terms(self):
        raw = "SENSITIVE_DATA: email\nSENSITIVE_DATA: credentials"
        source = "Enter your email and credentials"
        result = _parse_entities(raw, source, strip_thinking=False)
        assert len(result) == 0

    def test_deduplicates(self):
        raw = "PERSON: Alice\nPERSON: Alice"
        source = "Alice says hi"
        result = _parse_entities(raw, source, strip_thinking=False)
        assert len(result) == 1


class TestDetectionCache:
    def test_miss_returns_none(self):
        cache = DetectionCache()
        assert cache.get("hello") is None

    def test_put_and_get(self):
        cache = DetectionCache()
        entities = [("PERSON", "Alice")]
        cache.put("some text", entities)
        assert cache.get("some text") == entities

    def test_different_text_different_key(self):
        cache = DetectionCache()
        cache.put("text A", [("PERSON", "A")])
        assert cache.get("text B") is None

    def test_len(self):
        cache = DetectionCache()
        assert len(cache) == 0
        cache.put("a", [])
        cache.put("b", [])
        assert len(cache) == 2
