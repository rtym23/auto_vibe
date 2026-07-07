"""Council — cross-model reviewer for checking results."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum

from auto_vibe.integrations.llm import LLMClient


logger = logging.getLogger(__name__)


class ReviewType(Enum):
    """Review type."""
    NOTES = "notes"  # Simple notes (reviewer)
    VERDICT = "verdict"  # Score with verdict (judge)


@dataclass
class ReviewResult:
    """Review result."""
    review_type: ReviewType
    score: float  # 0-1
    verdict: str  # "pass", "revise", "fail"
    notes: str
    suggestions: List[str] = field(default_factory=list)

    def is_pass(self) -> bool:
        return self.verdict == "pass"

    def is_revsion_needed(self) -> bool:
        return self.verdict == "revise"


@dataclass
class CouncilConfig:
    """Council configuration (reviewers/judges)."""
    reviewer_model: str | None = None  # Model for reviewer
    judge_model: str | None = None     # Model for judge
    use_different_family: bool = True  # Use a different model family

    # Evaluation rubric
    criteria: List[str] = field(default_factory=lambda: [
        "Code runs without errors",
        "Code meets requirements",
        "Code is readable and maintainable",
        "No security vulnerabilities",
    ])

    # Thresholds
    pass_threshold: float = 0.8
    revise_threshold: float = 0.5


class Council:
    """
    Council — cross-model reviewer.
    Uses a different model to check work results.
    """

    def __init__(
        self,
        host_client: LLMClient,
        config: CouncilConfig | None = None,
    ):
        self.host_client = host_client
        self.config = config or CouncilConfig()
        self._reviewer_client: Optional[LLMClient] = None
        self._judge_client: Optional[LLMClient] = None

    async def _get_reviewer_client(self) -> LLMClient:
        """Gets the client for the reviewer."""
        if self._reviewer_client:
            return self._reviewer_client

        # If a model is specified, use it
        if self.config.reviewer_model:
            from auto_vibe.integrations.llm import create_llm_client
            from auto_vibe.config.settings import Settings
            settings = Settings.load()
            settings.llm.model = self.config.reviewer_model
            self._reviewer_client = await create_llm_client(settings.llm)
            return self._reviewer_client

        # Otherwise use the same model (fallback)
        return self.host_client

    async def _get_judge_client(self) -> LLMClient:
        """Gets the client for the judge."""
        if self._judge_client:
            return self._judge_client

        if self.config.judge_model:
            from auto_vibe.integrations.llm import create_llm_client
            from auto_vibe.config.settings import Settings
            settings = Settings.load()
            settings.llm.model = self.config.judge_model
            self._judge_client = await create_llm_client(settings.llm)
            return self._judge_client

        return self.host_client

    async def review(
        self,
        content: str,
        context: str = "",
        review_type: ReviewType = ReviewType.VERDICT,
    ) -> ReviewResult:
        """
        Reviews content through the council.

        Args:
            content: Content to review (code, result, etc.)
            context: Additional context
            review_type: Type of review

        Returns:
            Review result
        """
        if review_type == ReviewType.NOTES:
            return await self._review_as_notes(content, context)
        else:
            return await self._review_as_judge(content, context)

    async def _review_as_notes(self, content: str, context: str) -> ReviewResult:
        """Review as notes (reviewer)."""
        client = await self._get_reviewer_client()

        prompt = f"""You are a code reviewer. Review the following code and provide feedback.

Context: {context}

Code to review:
```
{content}
```

Provide your review as notes. Focus on:
- Potential issues
- Improvements
- Suggestions

Return ONLY a JSON object with fields: notes (string), suggestions (array of strings)
"""

        try:
            response = await client.generate(prompt)
            raw = response.content.strip()

            # Parse JSON
            import json
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            data = json.loads(raw.strip())

            return ReviewResult(
                review_type=ReviewType.NOTES,
                score=0.7,  # Default score for notes
                verdict="pass",
                notes=data.get("notes", ""),
                suggestions=data.get("suggestions", []),
            )
        except Exception as e:
            logger.error(f"Review failed: {e}")
            return ReviewResult(
                review_type=ReviewType.NOTES,
                score=0.5,
                verdict="revise",
                notes=f"Review failed: {e}",
                suggestions=[],
            )

    async def _review_as_judge(self, content: str, context: str) -> ReviewResult:
        """Review with verdict (judge)."""
        client = await self._get_judge_client()

        criteria_text = "\n".join(f"- {c}" for c in self.config.criteria)

        prompt = f"""You are a judge evaluating code quality. Score the following code against criteria.

Context: {context}

Code to evaluate:
```
{content}
```

Evaluation criteria:
{criteria_text}

Score each criterion from 0 to 1, then provide an overall verdict.
- "pass": score >= {self.config.pass_threshold}
- "revise": {self.config.revise_threshold} <= score < {self.config.pass_threshold}
- "fail": score < {self.config.revise_threshold}

Return ONLY a JSON object with fields:
- score (float 0-1)
- verdict (string: pass, revise, or fail)
- notes (string with explanation)
- suggestions (array of strings with improvement suggestions)
"""

        try:
            response = await client.generate(prompt)
            raw = response.content.strip()

            import json
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            data = json.loads(raw.strip())

            return ReviewResult(
                review_type=ReviewType.VERDICT,
                score=data.get("score", 0.5),
                verdict=data.get("verdict", "revise"),
                notes=data.get("notes", ""),
                suggestions=data.get("suggestions", []),
            )
        except Exception as e:
            logger.error(f"Judge evaluation failed: {e}")
            return ReviewResult(
                review_type=ReviewType.VERDICT,
                score=0.5,
                verdict="revise",
                notes=f"Evaluation failed: {e}",
                suggestions=[],
            )

    async def critique_goal(self, goal: str) -> str:
        """
        Critiques the goal before work begins.

        Args:
            goal: Goal description

        Returns:
            Critique and recommendations for improving the goal
        """
        prompt = f"""You are a goal design coach. Critique the following goal for an AI agent loop.

Goal: {goal}

Evaluate:
1. Is the goal specific and measurable?
2. Is it falsifiable (can we verify completion?)
3. Is it achievable?
4. Are the success criteria clear?

Provide constructive feedback and suggest improvements.
Return ONLY a JSON object with fields:
- is_good (boolean)
- issues (array of strings with problems)
- suggestions (array of strings with improvements)
- revised_goal (string with improved version if needed)
"""

        try:
            response = await self.host_client.generate(prompt)
            raw = response.content.strip()

            import json
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            data = json.loads(raw.strip())

            result = "Goal Critique:\n"
            if not data.get("is_good", True):
                result += "Goal needs improvement:\n"
                for issue in data.get("issues", []):
                    result += f"  - {issue}\n"

            if data.get("suggestions"):
                result += "\nSuggestions:\n"
                for s in data["suggestions"]:
                    result += f"  - {s}\n"

            if data.get("revised_goal"):
                result += f"\nRevised goal:\n{data['revised_goal']}"

            return result
        except Exception as e:
            logger.error(f"Goal critique failed: {e}")
            return f"Goal critique failed: {e}"
