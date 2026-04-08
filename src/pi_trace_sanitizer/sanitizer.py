"""Orchestrator: reads session JSONL, detects entities, replaces, writes output."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .entity_map import EntityMap
from .parser import extract_text_fields, mutate_strings, read_session, write_session


class DetectorLike(Protocol):
    """Minimal interface shared by Detector and ServerDetector."""
    def detect(self, text: str) -> list[tuple[str, str]]: ...


# ── Progress events ───────────────────────────────────────────────────────────

@dataclass
class SessionStart:
    file: str
    total_events: int

@dataclass
class EventStart:
    index: int
    total: int
    event_id: str
    event_type: str
    scannable_fields: int

@dataclass
class FieldStart:
    json_path: str
    text_length: int
    chunks: int

@dataclass
class Detection:
    json_path: str
    entity_type: str
    entity_text: str
    placeholder: str

@dataclass
class FieldDone:
    json_path: str
    elapsed: float
    detections: int

@dataclass
class EventDone:
    index: int
    detections: int

@dataclass
class ReplaceStart:
    unique_entities: int
    total_events: int

@dataclass
class SessionDone:
    events: int
    fields_scanned: int
    entities_found: int
    unique_entities: int
    elapsed: float


ProgressEvent = (
    SessionStart | EventStart | FieldStart | Detection
    | FieldDone | EventDone | ReplaceStart | SessionDone
)
ProgressCallback = Callable[[ProgressEvent], None]


# ── Field filtering ───────────────────────────────────────────────────────────

MIN_TEXT_LENGTH = 8
MAX_CHUNK_CHARS = 4000

_SKIP_SUFFIXES = frozenset({
    ".thinkingSignature", ".stopReason", ".api", ".object",
    ".type", ".version", ".id", ".parentId", ".timestamp",
    ".provider", ".model", ".modelId", ".thinkingLevel",
})

_SKIP_PREFIXES = ("usage.", "message.usage.")

_SKIP_EXACT = frozenset({
    "type", "version", "id", "parentId", "timestamp",
    "api", "provider", "model", "modelId", "thinkingLevel",
})


def _should_scan(json_path: str, text: str) -> bool:
    """Skip fields that are unlikely to contain PII worth scanning."""
    if len(text) < MIN_TEXT_LENGTH:
        return False
    if json_path in _SKIP_EXACT:
        return False
    for suffix in _SKIP_SUFFIXES:
        if json_path.endswith(suffix):
            return False
    for prefix in _SKIP_PREFIXES:
        if json_path.startswith(prefix):
            return False
    return True


def _chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split long text into chunks on line boundaries."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    lines = text.split("\n")
    current: list[str] = []
    current_len = 0
    for line in lines:
        if current_len + len(line) + 1 > max_chars and current:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1
    if current:
        chunks.append("\n".join(current))
    return chunks


# ── Main entry point ──────────────────────────────────────────────────────────

def sanitize_session(
    input_path: str | Path,
    output_path: str | Path,
    detector: DetectorLike,
    entity_map: EntityMap,
    *,
    dry_run: bool = False,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Sanitize a single session file.

    Returns a summary dict with counts of events, fields scanned, entities found.
    """
    emit = on_progress or (lambda _: None)
    t_start = time.monotonic()

    events = read_session(input_path)
    total_fields = 0
    total_entities = 0
    all_detections: list[tuple[str, str, str]] = []

    emit(SessionStart(file=Path(input_path).name, total_events=len(events)))

    # Pass 1: detect all entities across all events
    for i, event in enumerate(events):
        event_id = event.get("id", "?")
        event_type = event.get("type", "?")

        fields = extract_text_fields(event)
        scannable = [(p, t) for p, t in fields if _should_scan(p, t)]
        total_fields += len(scannable)

        emit(EventStart(
            index=i, total=len(events),
            event_id=event_id, event_type=event_type,
            scannable_fields=len(scannable),
        ))

        event_detections = 0
        for json_path, text in scannable:
            chunks = _chunk_text(text)
            emit(FieldStart(
                json_path=json_path,
                text_length=len(text),
                chunks=len(chunks),
            ))

            t0 = time.monotonic()
            field_detections = 0
            for chunk in chunks:
                detected = detector.detect(chunk)
                for entity_type, entity_text in detected:
                    placeholder = entity_map.get_placeholder(entity_type, entity_text)
                    all_detections.append((json_path, entity_type, entity_text))
                    field_detections += 1
                    emit(Detection(
                        json_path=json_path,
                        entity_type=entity_type,
                        entity_text=entity_text,
                        placeholder=placeholder,
                    ))

            emit(FieldDone(
                json_path=json_path,
                elapsed=time.monotonic() - t0,
                detections=field_detections,
            ))
            event_detections += field_detections

        total_entities += event_detections
        emit(EventDone(index=i, detections=event_detections))

    # Pass 2: replace all detected entities across all events
    emit(ReplaceStart(unique_entities=len(entity_map), total_events=len(events)))
    for event in events:
        mutate_strings(event, lambda _path, text: entity_map.apply_all(text))

    if not dry_run:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        write_session(events, output_path)

    elapsed = time.monotonic() - t_start
    emit(SessionDone(
        events=len(events),
        fields_scanned=total_fields,
        entities_found=total_entities,
        unique_entities=len(entity_map),
        elapsed=elapsed,
    ))

    return {
        "input": str(input_path),
        "output": str(output_path) if not dry_run else None,
        "events": len(events),
        "fields_scanned": total_fields,
        "entities_found": total_entities,
        "unique_entities": len(entity_map),
        "detections": all_detections,
    }
