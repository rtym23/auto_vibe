"""Grep client for code search."""

from __future__ import annotations


class GrepClient:
    """Grep-like search across files."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir

    def grep(self, pattern: str, file_pattern: str = "*.py") -> list[dict]:
        """Search for pattern in files."""
        return []
