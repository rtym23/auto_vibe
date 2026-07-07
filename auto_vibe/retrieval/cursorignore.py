"""CursorIgnore — .cursorignore support."""

from __future__ import annotations


class CursorIgnore:
    """Manages .cursorignore patterns."""

    def __init__(self, ignore_file: str = ".cursorignore"):
        self.ignore_file = ignore_file
        self._patterns: list[str] = []

    def load(self) -> None:
        """Load patterns from file."""
        pass

    def should_ignore(self, path: str) -> bool:
        """Check if path should be ignored."""
        return False
