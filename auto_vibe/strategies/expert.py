"""
Expert strategies — 3 fix modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Strategy(str, Enum):
    """AutoVibe operating mode."""
    QUICK = "quick"       # 1 attempt, minimal analysis
    DEEP = "deep"         # up to 5 iterations, full analysis
    MAX = "max"           # infinite loop with verification


@dataclass
class StrategyResult:
    """Strategy application result."""
    strategy: Strategy
    iterations: int
    success: bool
    fixed_code: str | None = None
    error_summary: str | None = None
    tokens_used: int = 0
    elapsed_seconds: float = 0.0


class ExpertMode:
    """Manages fix strategy."""

    def __init__(self, strategy: Strategy = Strategy.DEEP, max_iterations: int = 5):
        self.strategy = strategy
        self.max_iterations = max_iterations

    @property
    def max_attempts(self) -> int:
        """Max attempts for current strategy."""
        if self.strategy == Strategy.QUICK:
            return 1
        if self.strategy == Strategy.DEEP:
            return self.max_iterations
        return 999  # MAX — until fixed

    def should_continue(self, iteration: int, last_error: str | None) -> bool:
        """Decide whether to continue the loop."""
        if self.strategy == Strategy.QUICK:
            return iteration < 1
        if self.strategy == Strategy.DEEP:
            return iteration < self.max_iterations and last_error is not None
        # MAX: continue while there is an error
        return last_error is not None

    def analysis_depth(self) -> int:
        """Analysis depth: 1=min, 2=mid, 3=max."""
        return {Strategy.QUICK: 1, Strategy.DEEP: 2, Strategy.MAX: 3}[self.strategy]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "max_iterations": self.max_iterations,
            "max_attempts": self.max_attempts,
            "analysis_depth": self.analysis_depth(),
        }
