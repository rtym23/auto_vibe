import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from auto_vibe.config.settings import MemoryConfig


class MemoryVault:
    """
    Memory with automatic decay and checkpointing support.
    """

    def __init__(self, config: MemoryConfig):
        self.config = config
        self.vault_path = Path(config.vault_path).expanduser()
        self.memory: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self.vault_path.exists():
            try:
                with open(self.vault_path, "r") as f:
                    self.memory = json.load(f)
            except Exception:
                self.memory = []

    def _save(self) -> None:
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.vault_path, "w") as f:
            json.dump(self.memory, f, indent=2)

    def add_entry(self, content: str, metadata: Dict[str, Any] = None) -> None:
        """
        Adds a new entry to memory.
        """
        self._apply_decay()

        entry = {
            "timestamp": time.time(),
            "content": content,
            "metadata": metadata or {},
        }
        self.memory.append(entry)
        self._save()

    def _apply_decay(self) -> None:
        """
        Applies decay coefficient to old entries.
        """
        if not self.config.enabled:
            return

        now = time.time()
        new_memory = []
        for entry in self.memory:
            age_days = (now - entry["timestamp"]) / (24 * 3600)
            if age_days < 30:  # Keep only last 30 days for simplicity
                new_memory.append(entry)

        self.memory = new_memory

    def get_recent_entries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns recent entries.
        """
        return self.memory[-limit:]

    # === Checkpoint methods ===

    def save_checkpoint(self, state: Dict[str, Any]) -> None:
        """
        Saves state checkpoint.

        Args:
            state: state dictionary (iteration, task, file_content, etc.)
        """
        checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "timestamp": time.time(),
            "state": state,
            "memory_count": len(self.memory)
        }

        with open(checkpoint_path, "w") as f:
            json.dump(checkpoint, f, indent=2)

        print(f"Checkpoint saved: {checkpoint_path}")

    def load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """
        Loads state checkpoint.

        Returns:
            State dictionary or None if no checkpoint exists.
        """
        checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()

        if not checkpoint_path.exists():
            return None

        try:
            with open(checkpoint_path, "r") as f:
                checkpoint = json.load(f)

            print(f"Checkpoint loaded from iteration {checkpoint.get('state', {}).get('iteration', 0)}")
            return checkpoint.get("state")

        except Exception as e:
            print(f"Failed to load checkpoint: {e}")
            return None

    def clear_checkpoint(self) -> None:
        """Deletes checkpoint."""
        checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
        if checkpoint_path.exists():
            checkpoint_path.unlink()
            print("Checkpoint cleared")

    def search_memory(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Search memory.

        Args:
            query: search query
            limit: maximum number of results

        Returns:
            List of entries containing the query.
        """
        results = []
        query_lower = query.lower()

        for entry in reversed(self.memory):  # Recent first
            content = entry.get("content", "").lower()
            if query_lower in content:
                results.append(entry)
                if len(results) >= limit:
                    break

        return results
