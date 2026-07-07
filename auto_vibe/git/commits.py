"""Git commit tracker."""

from __future__ import annotations


class CommitTracker:
    """Tracks git commits."""

    def __init__(self, repo_dir: str = "."):
        self.repo_dir = repo_dir
        self._commits: list[dict] = []

    def get_recent(self, limit: int = 10) -> list[dict]:
        """Get recent commits."""
        return self._commits[-limit:]

    def track(self, message: str, files: list[str] | None = None) -> None:
        """Track a commit."""
        self._commits.append({"message": message, "files": files or []})
