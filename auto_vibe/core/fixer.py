"""Fixer — error correction using LLM.

Capabilities:
- Multi-pass fixing with validation
- Fix history tracking
- Semantic understanding of errors
"""

from __future__ import annotations

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict
from enum import Enum

from auto_vibe.integrations.llm import LLMClient, LLMError


logger = logging.getLogger(__name__)


class FixStatus(Enum):
    """Fix status."""
    SUCCESS = "success"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"
    PARTIAL = "partial"


@dataclass
class FixResult:
    """Fix result."""
    status: FixStatus
    fixed_code: str
    explanation: str
    attempts: int = 1
    validation_passed: bool = False
    error_after_fix: Optional[str] = None


class Fixer:
    """
    Proposes fixes based on errors using LLM.

    Features:
    - Multi-pass fixing with validation
    - Error history tracking
    - Attempt limiting
    """

    def __init__(
        self,
        llm_client: LLMClient,
        max_attempts: int = 3,
        validate_after_fix: bool = True,
    ):
        self.llm_client = llm_client
        self.max_attempts = max_attempts
        self.validate_after_fix = validate_after_fix

        # Fix history to avoid repeats
        self._fix_history: List[Dict] = []
        self._max_history = 20

    async def suggest_fix(
        self,
        error_msg: str,
        file_path: str | Path | None = None,
        file_content: str | None = None,
    ) -> str | None:
        """
        Uses LLM to generate a fix.

        Args:
            error_msg: Error message
            file_path: Path to the file with the error
            file_content: File content (if known)
        """
        # Build context
        context_parts = []

        if file_path:
            context_parts.append(f"File: {file_path}")

            # If content not passed, read from file
            if file_content is None:
                try:
                    path = Path(file_path)
                    if path.exists():
                        file_content = path.read_text(encoding="utf-8")
                except Exception as e:
                    logger.warning(f"Failed to read file {file_path}: {e}")

        if file_content:
            # Limit context size
            max_context = 4000
            if len(file_content) > max_context:
                file_content = file_content[:max_context] + "\n... (truncated)"
            context_parts.append(f"File contents:\n{file_content}")

        context = "\n\n".join(context_parts) if context_parts else "Context unavailable"

        prompt = f"""You are an expert in fixing code errors.

Error:
{error_msg}

Context (full file):
{context}

Your task: return the FULL corrected file code as a whole. Do not add comments, do not explain what you changed. Return only the code."""

        try:
            response = await self.llm_client.generate(prompt)
            return response.content
        except LLMError as e:
            logger.error(f"LLM error during fix generation: {e}")
            return f"# LLM Error: {e}"
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return f"# Error: {e}"

    async def fix_with_validation(
        self,
        error_msg: str,
        file_path: str | Path,
        validator: Optional[callable] = None,
    ) -> FixResult:
        """
        Fixes a file with result validation.

        Args:
            error_msg: Error message
            file_path: Path to the file
            validator: Optional validation function

        Returns:
            FixResult with fix result
        """
        path = Path(file_path)
        if not path.exists():
            return FixResult(
                status=FixStatus.FAILED,
                fixed_code="",
                explanation=f"File not found: {file_path}",
            )

        original_content = path.read_text(encoding="utf-8")
        current_content = original_content
        last_error = error_msg

        for attempt in range(1, self.max_attempts + 1):
            logger.info(f"Fix attempt {attempt}/{self.max_attempts}")

            # Generate fix
            fix = await self.suggest_fix(
                error_msg=last_error,
                file_path=str(file_path),
                file_content=current_content,
            )

            if not fix or fix.startswith("# Error") or fix.startswith("# LLM Error"):
                return FixResult(
                    status=FixStatus.FAILED,
                    fixed_code=current_content,
                    explanation=f"Failed to generate fix: {fix}",
                    attempts=attempt,
                )

            # Check that code changed
            if fix == current_content:
                if attempt < self.max_attempts:
                    last_error = "Code did not change after previous fix. Try a different approach."
                    continue
                else:
                    return FixResult(
                        status=FixStatus.FAILED,
                        fixed_code=current_content,
                        explanation="Code did not change after all attempts",
                        attempts=attempt,
                    )

            # Validate fix
            validation_passed = True
            error_after_fix = None

            if self.validate_after_fix or validator:
                try:
                    # Basic check - does code compile
                    compile(fix, str(file_path), 'exec')
                except SyntaxError as e:
                    validation_passed = False
                    error_after_fix = f"SyntaxError: {e}"

                # Additional validation
                if validation_passed and validator:
                    try:
                        validation_passed = await validator(fix)
                    except Exception as e:
                        validation_passed = False
                        error_after_fix = f"Validation error: {e}"

            if validation_passed:
                # Write fix
                path.write_text(fix, encoding="utf-8")

                # Add to history
                self._add_to_history(error_msg, fix, attempt)

                return FixResult(
                    status=FixStatus.SUCCESS,
                    fixed_code=fix,
                    explanation=f"Successfully fixed on attempt {attempt}",
                    attempts=attempt,
                    validation_passed=True,
                )

            # If validation failed, try again
            last_error = f"Error after fix: {error_after_fix}\n\nPrevious code:\n{current_content}"
            current_content = fix

        # All attempts exhausted
        return FixResult(
            status=FixStatus.PARTIAL,
            fixed_code=current_content,
            explanation=f"Failed to fix in {self.max_attempts} attempts",
            attempts=self.max_attempts,
            validation_passed=False,
            error_after_fix=last_error,
        )

    def _add_to_history(self, original_error: str, fixed_code: str, attempts: int) -> None:
        """Adds entry to fix history."""
        self._fix_history.append({
            "original_error": original_error[:200],
            "fixed_code_hash": hash(fixed_code),
            "attempts": attempts,
        })

        if len(self._fix_history) > self._max_history:
            self._fix_history = self._fix_history[-self._max_history:]

    def was_already_fixed(self, error_msg: str) -> bool:
        """Checks if a similar fix was already made."""
        error_hash = hash(error_msg[:200])
        for entry in self._fix_history:
            if entry["original_error"] == error_hash:
                return True
        return False

    def get_fix_stats(self) -> dict:
        """Returns fix statistics."""
        return {
            "total_fixes": len(self._fix_history),
            "max_attempts": self.max_attempts,
            "validate_after_fix": self.validate_after_fix,
        }
