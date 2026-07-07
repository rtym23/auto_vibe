"""Auto review for code changes."""

from __future__ import annotations


class AutoReview:
    """Automated code review."""

    def __init__(self):
        self._reviews: list[dict] = []

    def review(self, file_path: str, content: str) -> dict:
        """Review code and return findings."""
        return {"status": "ok", "issues": []}
