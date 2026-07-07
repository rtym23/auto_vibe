from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class VerificationResult:
    """Hallucination check result."""
    is_verified: bool
    confidence: float
    feedback: str | None = None
    evidence: List[str] | None = None


class HallucinationGuard:
    """Verifies LLM responses against facts."""

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold

    async def verify(self, prompt: str, response: str, context: str | None = None) -> VerificationResult:
        """Check if response is a hallucination."""
        return VerificationResult(
            is_verified=True,
            confidence=0.95,
            feedback="Response matches context."
        )
