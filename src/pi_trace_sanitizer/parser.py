"""JSONL session parser with recursive string walking.

Reads pi coding agent session JSONL files, walks all string values in each
event, and supports round-trip modification (read -> mutate strings -> write).
Skips base64 image data blobs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from .config import IMAGE_DATA_MIN_LENGTH


def read_session(path: str | Path) -> list[dict[str, Any]]:
    """Read a pi session JSONL file, returning a list of event dicts."""
    events: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    return events


def write_session(events: list[dict[str, Any]], path: str | Path) -> None:
    """Write events back to a JSONL file, one JSON object per line."""
    with open(path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def _is_image_data(key: str, value: str, parent: dict | None) -> bool:
    """Detect base64 image blobs: key is 'data', sibling has 'mimeType', value is long."""
    if key != "data" or len(value) < IMAGE_DATA_MIN_LENGTH:
        return False
    if parent and isinstance(parent, dict) and "mimeType" in parent:
        return True
    return False


def walk_strings(
    obj: Any,
    *,
    path: str = "",
    parent: dict | None = None,
    parent_key: str = "",
) -> list[tuple[str, str, Any, str | int]]:
    """Recursively walk an object tree, yielding all string values with their paths.

    Returns a list of (json_path, string_value, parent_container, key_in_parent)
    tuples. This gives the caller enough info to mutate strings in-place.
    Skips base64 image data blobs.
    """
    results: list[tuple[str, str, Any, str | int]] = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else k
            if isinstance(v, str):
                if not _is_image_data(k, v, obj):
                    results.append((child_path, v, obj, k))
            elif isinstance(v, (dict, list)):
                results.extend(walk_strings(v, path=child_path, parent=obj, parent_key=k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            child_path = f"{path}[{i}]"
            if isinstance(v, str):
                results.append((child_path, v, obj, i))
            elif isinstance(v, (dict, list)):
                results.extend(walk_strings(v, path=child_path, parent=obj, parent_key=str(i)))

    return results


def mutate_strings(
    event: dict[str, Any],
    transform: Callable[[str, str], str],
) -> dict[str, Any]:
    """Apply a transform function to every string value in an event.

    The transform receives (json_path, original_string) and returns the
    replacement string. Skips image data blobs. Mutates the event in-place
    and returns it.
    """
    for json_path, value, container, key in walk_strings(event):
        new_value = transform(json_path, value)
        if new_value != value:
            container[key] = new_value
    return event


def extract_text_fields(event: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract all (json_path, text) pairs from an event, skipping images."""
    return [(path, value) for path, value, _, _ in walk_strings(event)]
