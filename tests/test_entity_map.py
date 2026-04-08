"""Tests for the entity map."""

from pi_trace_sanitizer.entity_map import EntityMap


def test_consistent_placeholder():
    em = EntityMap()
    p1 = em.get_placeholder("PERSON", "John Smith")
    p2 = em.get_placeholder("PERSON", "John Smith")
    assert p1 == p2 == "[PERSON_1]"


def test_distinct_entities_get_distinct_placeholders():
    em = EntityMap()
    p1 = em.get_placeholder("PERSON", "John Smith")
    p2 = em.get_placeholder("PERSON", "Jane Doe")
    assert p1 == "[PERSON_1]"
    assert p2 == "[PERSON_2]"


def test_different_types_independent_counters():
    em = EntityMap()
    em.get_placeholder("PERSON", "John")
    em.get_placeholder("EMAIL", "john@example.com")
    assert em.get_placeholder("PERSON", "John") == "[PERSON_1]"
    assert em.get_placeholder("EMAIL", "john@example.com") == "[EMAIL_1]"


def test_user_path_normalization():
    em = EntityMap()
    p = em.get_placeholder("USER_PATH", "/Users/rlamers/workspace/project")
    assert p == "/Users/user/workspace/project"
    assert "rlamers" not in p


def test_user_path_home_normalization():
    em = EntityMap()
    p = em.get_placeholder("USER_PATH", "/home/john.smith/.config/app")
    assert p == "/home/user/.config/app"


def test_apply_all_replaces_longest_first():
    em = EntityMap()
    em.get_placeholder("EMAIL", "sarah@nvidia.com")
    em.get_placeholder("PERSON", "Sarah")
    text = "Contact Sarah at sarah@nvidia.com"
    result = em.apply_all(text)
    assert "[EMAIL_1]" in result
    assert "[PERSON_1]" in result
    assert "sarah@nvidia.com" not in result


def test_save_load_roundtrip(tmp_path):
    em = EntityMap()
    em.get_placeholder("PERSON", "Alice")
    em.get_placeholder("EMAIL", "alice@example.com")
    em.get_placeholder("USER_PATH", "/Users/alice/code")

    path = tmp_path / "map.json"
    em.save(path)

    loaded = EntityMap.load(path)
    assert loaded.get_placeholder("PERSON", "Alice") == em.get_placeholder("PERSON", "Alice")
    assert loaded.get_placeholder("EMAIL", "alice@example.com") == em.get_placeholder("EMAIL", "alice@example.com")
    assert len(loaded) == len(em)


def test_len():
    em = EntityMap()
    assert len(em) == 0
    em.get_placeholder("PERSON", "A")
    em.get_placeholder("PERSON", "B")
    assert len(em) == 2
