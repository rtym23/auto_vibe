"""Terminal manager."""

from __future__ import annotations


class TerminalManager:
    """Manages terminal sessions."""

    def __init__(self):
        self._sessions: dict = {}

    def execute(self, command: str, cwd: str = ".") -> tuple[str, str, int]:
        """Execute command and return (stdout, stderr, returncode)."""
        return "", "", 0
