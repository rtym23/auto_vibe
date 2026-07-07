"""Environment manager for dev environments."""

from __future__ import annotations


class EnvironmentManager:
    """Manages development environment setup."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir

    def setup(self) -> bool:
        """Set up the environment."""
        return True

    def get_info(self) -> dict:
        """Get environment information."""
        return {"status": "ready"}
