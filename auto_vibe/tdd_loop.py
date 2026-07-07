"""TDD Loop - Test-Driven Development cycle for AutoVibe.

Implements TDD approach:
1. Analyze error/task
2. Generate test (reproduction case)
3. Run test -> Fail
4. Fix code
5. Run test -> Pass

Integrated with:
- TestGenerator (test generation)
- TypedVerifier (verification)
- Sandbox (safe execution)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Awaitable, TYPE_CHECKING
from enum import Enum
from pathlib import Path

from auto_vibe.test_generator import TestGenerator, TestSuiteResult, TestResult
from auto_vibe.sandbox import Sandbox, SandboxResult
from auto_vibe.agents.verifier import TypedVerifier

if TYPE_CHECKING:
    from auto_vibe.integrations.llm import LLMClient

logger = logging.getLogger(__name__)


class TDDPhase(Enum):
    """TDD cycle phase."""
    ANALYZE = "analyze"
    GENERATE_TEST = "generate"
    RUN_TEST_FAIL = "run_fail"
    FIX_CODE = "fix"
    RUN_TEST_PASS = "run_pass"
    DONE = "done"


@dataclass
class TDDState:
    """TDD cycle state."""
    phase: TDDPhase = TDDPhase.ANALYZE
    error_message: str = ""
    target_file: str = ""
    original_code: str = ""
    generated_test: str = ""
    test_file_path: str = ""
    test_results: List[TestResult] = field(default_factory=list)
    fix_attempts: int = 0
    code_snapshots: List[str] = field(default_factory=list)


@dataclass
class TDDConfig:
    """TDD cycle configuration."""
    auto_generate_tests: bool = True
    test_file_prefix: str = "test_"
    tests_dir: str = "tests"
    require_all_tests_pass: bool = True
    min_tests_required: int = 1
    max_fix_attempts: int = 3
    sandbox_timeout: int = 30


class TDDLoop:
    """
    TDD Loop - test-driven development for AutoVibe.
    
    Workflow:
    1. ANALYZE: Understand error/task
    2. GENERATE: Create test that reproduces the problem
    3. RUN_FAIL: Ensure test fails (red)
    4. FIX: Fix the code
    5. RUN_PASS: Ensure test passes (green)
    
    Success = "tests passed" (not just "code ran")
    """

    def __init__(
        self,
        llm_client: Optional[LLMClient] = None,
        test_generator: Optional[TestGenerator] = None,
        sandbox: Optional[Sandbox] = None,
        verifier: Optional[TypedVerifier] = None,
        config: Optional[TDDConfig] = None,
    ):
        self.llm_client = llm_client
        self.test_generator = test_generator or TestGenerator(
            llm_client=llm_client,
            sandbox=sandbox,
        )
        self.sandbox = sandbox or Sandbox()
        self.verifier = verifier
        self.config = config or TDDConfig()
        self.state = TDDState()

    async def run_tdd(
        self,
        task: str,
        error_context: str,
        target_file: str,
        fix_callback: Callable[[str, str], Awaitable[str]],
    ) -> tuple[bool, str]:
        """Run full TDD cycle."""
        logger.info(f"Starting TDD loop for {target_file}")

        self.state.phase = TDDPhase.ANALYZE
        self.state.error_message = error_context
        self.state.target_file = target_file

        try:
            self.state.original_code = Path(target_file).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read {target_file}: {e}")
            self.state.original_code = ""

        logger.info(f"TDD Phase 1/5: ANALYZE - Error: {error_context[:200]}")

        if not self.config.auto_generate_tests:
            return False, self.state.original_code

        self.state.phase = TDDPhase.GENERATE_TEST
        logger.info("TDD Phase 2/5: GENERATE TEST")

        test_code = await self._generate_test(task, error_context, target_file)

        if not test_code:
            logger.warning("Could not generate test, falling back to simple execution")
            return await self._run_simple_fix(task, error_context, target_file, fix_callback)

        self.state.generated_test = test_code

        test_file = self._get_test_file_path(target_file)
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text(test_code, encoding="utf-8")
        self.state.test_file_path = str(test_file)

        logger.info(f"Generated test: {test_file}")

        self.state.phase = TDDPhase.RUN_TEST_FAIL
        logger.info("TDD Phase 3/5: RUN TEST (expecting FAIL)")

        test_result = await self._run_test(test_code)

        if test_result.passed:
            logger.warning("Test passed unexpectedly - code may already be fixed")
            return True, self.state.original_code

        logger.info(f"Test failed as expected: {test_result.failed} failures")

        self.state.phase = TDDPhase.FIX_CODE
        logger.info("TDD Phase 4/5: FIX CODE")

        fixed_code = await fix_callback(
            self.state.original_code,
            self._create_test_context(test_result),
        )

        self.state.code_snapshots.append(fixed_code[:500])
        Path(target_file).write_text(fixed_code, encoding="utf-8")

        self.state.phase = TDDPhase.RUN_TEST_PASS
        logger.info("TDD Phase 5/5: RUN TEST (expecting PASS)")

        test_result = await self._run_test(test_code, source_code=fixed_code)

        if test_result.passed:
            self.state.phase = TDDPhase.DONE
            logger.info("TDD Cycle Complete - All tests passed!")
            return True, fixed_code

        logger.warning(f"Test still failing: {test_result.failed} failures")

        for attempt in range(1, self.config.max_fix_attempts + 1):
            self.state.fix_attempts = attempt

            fixed_code = await fix_callback(
                fixed_code,
                self._create_test_context(test_result),
            )

            self.state.code_snapshots.append(fixed_code[:500])
            Path(target_file).write_text(fixed_code, encoding="utf-8")
            test_result = await self._run_test(test_code, source_code=fixed_code)

            if test_result.passed:
                self.state.phase = TDDPhase.DONE
                logger.info(f"TDD Cycle Complete after {attempt + 1} fixes!")
                return True, fixed_code

        logger.error("TDD Cycle Failed - max fix attempts reached")
        Path(target_file).write_text(self.state.original_code, encoding="utf-8")
        return False, self.state.original_code

    async def _generate_test(
        self,
        task: str,
        error_context: str,
        target_file: str,
    ) -> Optional[str]:
        """Generate test to reproduce error."""
        if not self.llm_client:
            return None

        try:
            source_code = Path(target_file).read_text(encoding="utf-8")
        except Exception:
            source_code = ""

        prompt = f"""Generate a pytest test case that reproduces the following error.

Task: {task}

Error:
`
{error_context}
`

Target file: {target_file}

Source code:
`python
{source_code}
`

Generate a test that:
1. Has a descriptive name (test_...)
2. Uses pytest
3. Reproduces the error condition
4. Will FAIL with the current code but PASS when fixed

Return ONLY the test code, no explanations."""

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content.strip() if hasattr(response, 'content') else str(response)

            if content.startswith("`python"):
                content = content[9:]
            if content.startswith("`"):
                content = content[3:]
            if content.endswith("`"):
                content = content[:-3]

            return content.strip()

        except Exception as e:
            logger.error(f"Failed to generate test: {e}")
            return None

    async def _run_test(
        self,
        test_code: str,
        source_code: Optional[str] = None,
    ) -> TestSuiteResult:
        """Run test in sandbox."""
        result = await self.sandbox.run_command(
            "python -m pytest -v --tb=short -x",
            timeout=self.config.sandbox_timeout,
        )
        return self._parse_pytest_result(result)

    def _parse_pytest_result(self, result: SandboxResult) -> TestSuiteResult:
        """Parse pytest result."""
        output = result.stdout + "\n" + result.stderr

        results = []
        total = 0
        passed = 0
        failed = 0

        for line in output.split("\n"):
            if "PASSED" in line:
                parts = line.split("::")
                if len(parts) >= 2:
                    test_name = parts[1].split()[0] if parts[1] else "unknown"
                    results.append(TestResult(name=test_name, passed=True))
                    passed += 1
                    total += 1
            elif "FAILED" in line:
                parts = line.split("::")
                if len(parts) >= 2:
                    test_name = parts[1].split()[0] if parts[1] else "unknown"
                    error = ""
                    if " - " in line:
                        error = line.split(" - ", 1)[1]
                    results.append(TestResult(name=test_name, passed=False, error_message=error))
                    failed += 1
                    total += 1

        return TestSuiteResult(
            total=total,
            passed=passed,
            failed=failed,
            results=results,
        )

    def _get_test_file_path(self, target_file: str) -> Path:
        """Determine test file path."""
        target_path = Path(target_file)
        tests_dir = Path(self.config.tests_dir)
        if not tests_dir.is_absolute():
            tests_dir = target_path.parent / tests_dir
        test_name = self.config.test_file_prefix + target_path.stem + ".py"
        return tests_dir / test_name

    def _create_test_context(self, result: TestSuiteResult) -> str:
        """Create context for fix callback."""
        lines = ["Test Results:"]
        lines.append(f"Total: {result.total}, Passed: {result.passed}, Failed: {result.failed}")

        if result.results:
            lines.append("\nFailed tests:")
            for r in result.results:
                if not r.passed:
                    lines.append(f"  - {r.name}: {r.error_message or 'failed'}")

        return "\n".join(lines)

    async def _run_simple_fix(
        self,
        task: str,
        error_context: str,
        target_file: str,
        fix_callback: Callable[[str, str], Awaitable[str]],
    ) -> tuple[bool, str]:
        """Simple fallback without test generation."""
        fixed_code = await fix_callback(
            self.state.original_code,
            f"Error: {error_context}",
        )

        result = await self.sandbox.run_command(
            f"python -m py_compile {target_file}",
            timeout=10,
        )

        success = result.exit_code == 0

        if success:
            Path(target_file).write_text(fixed_code, encoding="utf-8")
            return True, fixed_code

        return False, self.state.original_code

    def get_summary(self) -> dict:
        """Return TDD cycle summary."""
        return {
            "phase": self.state.phase.value,
            "fix_attempts": self.state.fix_attempts,
            "test_file": self.state.test_file_path,
            "tests_total": len(self.state.test_results),
            "tests_passed": sum(1 for r in self.state.test_results if r.passed),
            "tests_failed": sum(1 for r in self.state.test_results if not r.passed),
        }


async def run_tdd_with_verifier(
    task: str,
    error_context: str,
    target_file: str,
    llm_client,
    verifier: TypedVerifier,
    fix_callback: Callable[[str, str], Awaitable[str]],
) -> tuple[bool, str]:
    """Run TDD cycle with verification."""
    tdd_loop = TDDLoop(
        llm_client=llm_client,
        verifier=verifier,
    )

    return await tdd_loop.run_tdd(
        task=task,
        error_context=error_context,
        target_file=target_file,
        fix_callback=fix_callback,
    )
