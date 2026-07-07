"""Mesh node for distributed LLM."""

from __future__ import annotations


class MeshNode:
    """A single node in the LLM mesh."""

    def __init__(self, name: str, endpoint: str = ""):
        self.name = name
        self.endpoint = endpoint

    def process(self, task: str) -> str:
        """Process a task."""
        return task
