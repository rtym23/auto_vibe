"""Code indexer for retrieval."""

from __future__ import annotations


class CodeIndexer:
    """Indexes code files for fast search."""

    def __init__(self, root_dir: str = "."):
        self.root_dir = root_dir
        self._index: dict = {}

    def index_file(self, file_path: str) -> None:
        """Index a single file."""
        self._index[file_path] = True

    def search(self, query: str) -> list[str]:
        """Search indexed files."""
        return list(self._index.keys())
