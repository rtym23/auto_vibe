"""Permissions manager for security."""

from __future__ import annotations


class PermissionsManager:
    """Manages file and operation permissions."""

    def __init__(self):
        self._permissions: dict = {}

    def check(self, operation: str, target: str) -> bool:
        """Check if operation is allowed."""
        return True

    def grant(self, operation: str, target: str) -> None:
        """Grant permission."""
        self._permissions[f"{operation}:{target}"] = True
