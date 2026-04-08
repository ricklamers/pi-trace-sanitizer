"""Session-scoped entity map for consistent placeholder assignment.

Each unique (entity_type, entity_text) pair gets a stable placeholder like
[PERSON_1] that persists across the entire session. The map can be saved and
loaded for cross-session consistency.

Special case: USER_PATH entities normalize the username portion of filesystem
paths (e.g. /Users/rlamers/ -> /Users/user/) rather than using opaque
placeholders, preserving path structure for trace analysis.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


class EntityMap:
    """Maps detected entities to consistent placeholders."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._map: dict[tuple[str, str], str] = {}

    def get_placeholder(self, entity_type: str, entity_text: str) -> str:
        """Return a consistent placeholder for the given entity.

        USER_PATH entities are handled specially: the username component of
        common path prefixes is normalized rather than replaced entirely.
        """
        key = (entity_type, entity_text)
        if key in self._map:
            return self._map[key]

        if entity_type == "USER_PATH":
            placeholder = _normalize_user_path(entity_text)
        else:
            self._counters[entity_type] += 1
            placeholder = f"[{entity_type}_{self._counters[entity_type]}]"

        self._map[key] = placeholder
        return placeholder

    def apply_all(self, text: str) -> str:
        """Replace all known entities in text with their placeholders.

        Replaces longer entities first to avoid partial matches.
        """
        replacements = sorted(
            self._map.items(), key=lambda kv: len(kv[0][1]), reverse=True
        )
        for (_, entity_text), placeholder in replacements:
            text = text.replace(entity_text, placeholder)
        return text

    @property
    def entities(self) -> dict[tuple[str, str], str]:
        return dict(self._map)

    def __len__(self) -> int:
        return len(self._map)

    def save(self, path: str | Path) -> None:
        """Persist the entity map to a JSON file."""
        serializable = {
            "counters": dict(self._counters),
            "map": {f"{et}\t{txt}": placeholder for (et, txt), placeholder in self._map.items()},
        }
        Path(path).write_text(json.dumps(serializable, indent=2, ensure_ascii=False))

    @classmethod
    def load(cls, path: str | Path) -> "EntityMap":
        """Load an entity map from a JSON file."""
        data = json.loads(Path(path).read_text())
        em = cls()
        em._counters = defaultdict(int, data.get("counters", {}))
        for key_str, placeholder in data.get("map", {}).items():
            et, txt = key_str.split("\t", 1)
            em._map[(et, txt)] = placeholder
        return em


_USER_PATH_RE = re.compile(
    r"(/(?:Users|home)/)[A-Za-z0-9._-]+(/)"
)


def _normalize_user_path(path_text: str) -> str:
    """Replace the username component in paths like /Users/rlamers/ with /Users/user/."""
    return _USER_PATH_RE.sub(r"\1user\2", path_text)
