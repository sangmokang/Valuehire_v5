"""Process-local HUMAN_AUTH episode dedupe state."""

from __future__ import annotations

from threading import Lock
from typing import Any


class HumanAuthEpisodeStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._claims: set[tuple[str, str]] = set()
        self._locators: dict[str, Any] = {}

    def claim(self, episode_id: str, event: str) -> bool:
        key = (episode_id, event)
        with self._lock:
            if key in self._claims:
                return False
            self._claims.add(key)
            return True

    def count(self, episode_id: str, event: str) -> int:
        with self._lock:
            return int((episode_id, event) in self._claims)

    def save_locator(self, episode_id: str, locator: Any) -> None:
        with self._lock:
            self._locators[episode_id] = locator

    def load_locator(self, episode_id: str) -> Any | None:
        with self._lock:
            return self._locators.get(episode_id)


DEFAULT_HUMAN_AUTH_EPISODES = HumanAuthEpisodeStore()
