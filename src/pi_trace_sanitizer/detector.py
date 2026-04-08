"""PII/sensitive data detector using Nemotron 3 via mlx-lm.

Loads the model once, then processes text chunks to extract entity mentions.
Supports thinking mode (higher quality, slower) and direct mode (faster).
Also supports connecting to a running mlx_lm.server via OpenAI-compatible API.
"""

from __future__ import annotations

import hashlib
import re
import sys
from typing import Any

from .config import (
    ALLOWLISTED_TERMS,
    ENTITY_TYPES,
    MAX_TOKENS_PER_GENERATION,
    MIN_ENTITY_TEXT_LENGTH,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)

_THINK_CLOSE_RE = re.compile(r"</think>\s*", re.DOTALL)
_ENTITY_LINE_RE = re.compile(
    r"^(" + "|".join(ENTITY_TYPES) + r"):\s*(.+)$", re.MULTILINE
)


def _parse_entities(
    raw_output: str,
    source_text: str,
    *,
    strip_thinking: bool = True,
) -> list[tuple[str, str]]:
    """Parse model output into (type, text) pairs.

    If thinking mode was used, strips the reasoning block first.
    Only returns entities whose text actually appears in the source,
    passes minimum length, and is not allowlisted.
    """
    answer = raw_output
    if strip_thinking:
        m = _THINK_CLOSE_RE.search(answer)
        if m:
            answer = answer[m.end():]

    if answer.strip().upper() == "NONE":
        return []

    entities: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _ENTITY_LINE_RE.finditer(answer):
        entity_type = match.group(1)
        entity_text = match.group(2).strip()
        if not entity_text:
            continue
        key = (entity_type, entity_text)
        if key in seen:
            continue
        if len(entity_text) < MIN_ENTITY_TEXT_LENGTH:
            continue
        if entity_text.lower() in ALLOWLISTED_TERMS:
            continue
        if entity_text in source_text:
            seen.add(key)
            entities.append(key)

    return entities


class DetectionCache:
    """Hash-based cache to skip re-detection of identical text chunks."""

    def __init__(self) -> None:
        self._cache: dict[str, list[tuple[str, str]]] = {}

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def get(self, text: str) -> list[tuple[str, str]] | None:
        return self._cache.get(self._key(text))

    def put(self, text: str, entities: list[tuple[str, str]]) -> None:
        self._cache[self._key(text)] = entities

    def __len__(self) -> int:
        return len(self._cache)


class Detector:
    """Wraps mlx-lm model loading and entity extraction."""

    def __init__(
        self,
        model_path: str,
        *,
        thinking: bool = True,
        max_tokens: int = MAX_TOKENS_PER_GENERATION,
    ) -> None:
        self.model_path = model_path
        self.thinking = thinking
        self.max_tokens = max_tokens
        self._model: Any = None
        self._tokenizer: Any = None
        self.cache = DetectionCache()

    def load(self) -> None:
        """Load the model and tokenizer. Call once before detect()."""
        from mlx_lm import load as mlx_load

        print(f"Loading model from {self.model_path}...", file=sys.stderr)
        self._model, self._tokenizer = mlx_load(self.model_path)
        print("Model loaded.", file=sys.stderr)

    def detect(self, text: str) -> list[tuple[str, str]]:
        """Detect PII/sensitive entities in text.

        Returns a list of (entity_type, entity_text) tuples where entity_text
        is the exact string found in the input.
        """
        if not text.strip():
            return []

        cached = self.cache.get(text)
        if cached is not None:
            return cached

        from mlx_lm.generate import stream_generate

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
        ]

        prompt = self._tokenizer.apply_chat_template(
            messages,
            add_generation_prompt=True,
            enable_thinking=self.thinking,
        )

        full_output = ""
        for resp in stream_generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=self.max_tokens,
            temp=1.0,
            top_p=1.0,
        ):
            full_output += resp.text

        entities = _parse_entities(
            full_output, text, strip_thinking=self.thinking
        )
        self.cache.put(text, entities)
        return entities


class ServerDetector:
    """Detector that connects to a running mlx_lm.server via OpenAI-compatible API.

    Use this when processing many sessions — load the model once as a server,
    then point multiple sanitizer runs at it.
    """

    def __init__(
        self,
        server_url: str,
        *,
        thinking: bool = True,
        max_tokens: int = MAX_TOKENS_PER_GENERATION,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.thinking = thinking
        self.max_tokens = max_tokens
        self.cache = DetectionCache()

    def load(self) -> None:
        """Verify the server is reachable."""
        import urllib.request
        import urllib.error

        url = f"{self.server_url}/v1/models"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print(f"Connected to server at {self.server_url}", file=sys.stderr)
                    return
        except (urllib.error.URLError, OSError) as exc:
            raise ConnectionError(
                f"Cannot reach mlx_lm server at {self.server_url}: {exc}"
            ) from exc

    def detect(self, text: str) -> list[tuple[str, str]]:
        """Detect PII via the server's chat completions endpoint."""
        if not text.strip():
            return []

        cached = self.cache.get(text)
        if cached is not None:
            return cached

        import json
        import urllib.request

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
        ]

        payload = json.dumps({
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 1.0,
            "top_p": 1.0,
        }).encode()

        req = urllib.request.Request(
            f"{self.server_url}/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read())

        msg = data["choices"][0]["message"]
        raw_output = msg.get("content") or ""
        entities = _parse_entities(
            raw_output, text, strip_thinking=False
        )
        self.cache.put(text, entities)
        return entities
