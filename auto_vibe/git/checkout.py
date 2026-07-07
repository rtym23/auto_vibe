"""Git checkout provider."""

from __future__ import annotations


class CheckoutProvider:
    """Provides git checkout operations."""

    def __init__(self, repo_dir: str = "."):
        self.repo_dir = repo_dir

    def checkout(self, branch: str) -> bool:
        """Checkout a branch."""
        return True

    def create_branch(self, name: str) -> bool:
        """Create a new branch."""
        return True
