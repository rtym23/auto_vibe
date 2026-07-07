"""Canvas runtime for interactive agent collaboration."""

from typing import Any
from datetime import datetime


class CanvasRuntime:
    """Canvas for agent collaboration and state sharing."""
    
    def __init__(self):
        self.state: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in the canvas."""
        self.state[key] = value
        self.history.append({
            "action": "set",
            "key": key,
            "value": value,
            "timestamp": datetime.now().isoformat()
        })
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a value from the canvas."""
        return self.state.get(key, default)
    
    def clear(self) -> None:
        """Clear all state."""
        self.state.clear()
        self.history.append({
            "action": "clear",
            "timestamp": datetime.now().isoformat()
        })
    
    def get_history(self) -> list[dict[str, Any]]:
        """Get the history of operations."""
        return self.history
