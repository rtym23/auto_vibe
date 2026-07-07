"""Mesh manager for distributed LLM agents."""

from __future__ import annotations


class MeshManager:
    """Manages a mesh of LLM agents."""

    def __init__(self):
        self._nodes: list = []

    def add_node(self, node) -> None:
        """Add a node to the mesh."""
        self._nodes.append(node)

    def route(self, task: str) -> str:
        """Route task to appropriate node."""
        return task
