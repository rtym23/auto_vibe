"""Shadow workspace for safe experimentation."""

from __future__ import annotations


class ShadowWorkspace:
    """Isolated workspace for code experiments."""

    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir

    def create(self) -> str:
        """Create shadow workspace and return path."""
        return self.base_dir

    def cleanup(self) -> None:
        """Clean up shadow workspace."""
        pass
