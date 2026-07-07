"""Typed verification — programmatic checks for results."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Callable, Awaitable
from enum import Enum

from auto_vibe.core.executor import Executor


logger = logging.getLogger(__name__)


class VerificationType(Enum):
    """Verification type."""
    PROGRAMMATIC = "programmatic"  # Programmatic check (command)
    LLM_JUDGE = "llm_judge"        # Check via LLM
    HUMAN = "human"                # Human confirmation


@dataclass
class VerificationResult:
    """Verification result."""
    verification_type: VerificationType
    passed: bool
    message: str
    details: dict = field(default_factory=dict)

    def is_pass(self) -> bool:
        return self.passed


@dataclass
class VerificationRule:
    """Verification rule."""
    name: str
    description: str
    verification_type: VerificationType

    # For PROGRAMMATIC
    command: str | None = None
    expected_exit_code: int = 0
    expected_output: str | None = None
    output_pattern: str | None = None

    # For LLM_JUDGE
    criteria: List[str] = field(default_factory=list)

    # For HUMAN
    prompt: str | None = None


class TypedVerifier:
    """
    Typed verifier — checks results via:
    - Programmatic commands
    - LLM judge
    - Human confirmation
    """

    def __init__(
        self,
        executor: Executor | None = None,
        llm_client=None,  # Optional LLM client for LLM_JUDGE
        human_callback: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.executor = executor or Executor()
        self.llm_client = llm_client
        self.human_callback = human_callback

    async def verify(
        self,
        rules: List[VerificationRule],
        context: dict | None = None,
    ) -> VerificationResult:
        """
        Checks a set of rules.

        Args:
            rules: List of verification rules
            context: Context for checking (files, results, etc.)

        Returns:
            Verification result
        """
        context = context or {}
        results: List[VerificationResult] = []

        for rule in rules:
            result = await self._verify_rule(rule, context)
            results.append(result)

            if not result.passed:
                return VerificationResult(
                    verification_type=rule.verification_type,
                    passed=False,
                    message=f"Rule '{rule.name}' failed: {result.message}",
                    details={"rule": rule.name, "results": [r.__dict__ for r in results]},
                )

        return VerificationResult(
            verification_type=VerificationType.PROGRAMMATIC,
            passed=True,
            message=f"All {len(rules)} verification rules passed",
            details={"results": [r.__dict__ for r in results]},
        )

    async def _verify_rule(
        self,
        rule: VerificationRule,
        context: dict,
    ) -> VerificationResult:
        """Checks a single rule."""
        if rule.verification_type == VerificationType.PROGRAMMATIC:
            return await self._verify_programmatic(rule, context)
        elif rule.verification_type == VerificationType.LLM_JUDGE:
            return await self._verify_llm_judge(rule, context)
        elif rule.verification_type == VerificationType.HUMAN:
            return await self._verify_human(rule, context)
        else:
            return VerificationResult(
                verification_type=rule.verification_type,
                passed=False,
                message=f"Unknown verification type: {rule.verification_type}",
            )

    async def _verify_programmatic(
        self,
        rule: VerificationRule,
        context: dict,
    ) -> VerificationResult:
        """Programmatic check via command."""
        if not rule.command:
            return VerificationResult(
                verification_type=VerificationType.PROGRAMMATIC,
                passed=False,
                message="No command specified for programmatic verification",
            )

        # Substitute context into the command
        command = rule.command
        for key, value in context.items():
            command = command.replace(f"{{{key}}}", str(value))

        try:
            result = await self.executor.run_command(command)

            # Check exit code
            if result.exit_code != rule.expected_exit_code:
                return VerificationResult(
                    verification_type=VerificationType.PROGRAMMATIC,
                    passed=False,
                    message=f"Command failed with exit code {result.exit_code}, expected {rule.expected_exit_code}",
                    details={"stdout": result.stdout, "stderr": result.stderr},
                )

            # Check expected output
            if rule.expected_output:
                if rule.expected_output not in result.stdout:
                    return VerificationResult(
                        verification_type=VerificationType.PROGRAMMATIC,
                        passed=False,
                        message=f"Expected output not found: {rule.expected_output}",
                        details={"stdout": result.stdout},
                    )

            # Check output pattern
            if rule.output_pattern:
                if not re.search(rule.output_pattern, result.stdout):
                    return VerificationResult(
                        verification_type=VerificationType.PROGRAMMATIC,
                        passed=False,
                        message=f"Output pattern not matched: {rule.output_pattern}",
                        details={"stdout": result.stdout},
                    )

            return VerificationResult(
                verification_type=VerificationType.PROGRAMMATIC,
                passed=True,
                message=f"Command passed: {command}",
                details={"stdout": result.stdout},
            )

        except Exception as e:
            return VerificationResult(
                verification_type=VerificationType.PROGRAMMATIC,
                passed=False,
                message=f"Verification error: {e}",
            )

    async def _verify_llm_judge(
        self,
        rule: VerificationRule,
        context: dict,
    ) -> VerificationResult:
        """Check via LLM judge."""
        if not self.llm_client:
            return VerificationResult(
                verification_type=VerificationType.LLM_JUDGE,
                passed=False,
                message="No LLM client configured for judge verification",
            )

        content = context.get("content", "")
        criteria_text = "\n".join(f"- {c}" for c in rule.criteria)

        prompt = f"""Evaluate the following code against the criteria.

Code:
```
{content}
```

Criteria:
{criteria_text}

Return ONLY a JSON object with fields:
- passed (boolean)
- message (string with explanation)
- score (float 0-1)
"""

        try:
            response = await self.llm_client.generate(prompt)
            raw = response.content.strip()

            import json
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            data = json.loads(raw.strip())

            return VerificationResult(
                verification_type=VerificationType.LLM_JUDGE,
                passed=data.get("passed", False),
                message=data.get("message", ""),
                details={"score": data.get("score", 0.5)},
            )
        except Exception as e:
            return VerificationResult(
                verification_type=VerificationType.LLM_JUDGE,
                passed=False,
                message=f"LLM judge error: {e}",
            )

    async def _verify_human(
        self,
        rule: VerificationRule,
        context: dict,
    ) -> VerificationResult:
        """Human verification."""
        prompt = rule.prompt or f"Confirm: {rule.description}"

        if self.human_callback:
            confirmed = await self.human_callback(prompt)
        else:
            # Fallback to input()
            try:
                response = input(f"\n{prompt}\n[Y/n]: ").strip().lower()
                confirmed = response in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt):
                confirmed = True

        return VerificationResult(
            verification_type=VerificationType.HUMAN,
            passed=confirmed,
            message="Confirmed by human" if confirmed else "Rejected by human",
        )


# Utilities for creating typical verification rules
def create_syntax_check(target_file: str) -> VerificationRule:
    """Creates a syntax check rule."""
    return VerificationRule(
        name="syntax_check",
        description=f"Check Python syntax of {target_file}",
        verification_type=VerificationType.PROGRAMMATIC,
        command=f"python -m py_compile {target_file}",
        expected_exit_code=0,
    )


def create_import_check(target_file: str) -> VerificationRule:
    """Creates an import check rule."""
    return VerificationRule(
        name="import_check",
        description=f"Check imports in {target_file}",
        verification_type=VerificationType.PROGRAMMATIC,
        command=f'python -c "import importlib.util; spec = importlib.util.spec_from_file_location(\"test\", r\"{target_file}\"); mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"',
        expected_exit_code=0,
    )


def create_test_check(command: str, expected_output: str | None = None) -> VerificationRule:
    """Creates a test check rule."""
    return VerificationRule(
        name="test_check",
        description=f"Run tests: {command}",
        verification_type=VerificationType.PROGRAMMATIC,
        command=command,
        expected_exit_code=0,
        expected_output=expected_output,
    )


def create_lint_check(target_file: str, linter: str = "ruff") -> VerificationRule:
    """Creates a lint check rule."""
    return VerificationRule(
        name="lint_check",
        description=f"Run {linter} on {target_file}",
        verification_type=VerificationType.PROGRAMMATIC,
        command=f"{linter} check {target_file}",
        expected_exit_code=0,
    )
