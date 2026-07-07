"""Test generator for AutoVibe.

Generates and runs tests for generated code.
"""

from pathlib import Path
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class TestResult:
    """Test result."""
    name: str
    passed: bool
    error_message: Optional[str] = None
    duration: float = 0.0


@dataclass
class TestSuiteResult:
    """Test suite result."""
    total: int
    passed: int
    failed: int
    results: List[TestResult]


class TestGenerator:
    """
    Test generator and runner for generated code.
    
    Features:
    - Generate unit tests for code
    - Run tests in sandbox
    - Analyze results
    """
    
    def __init__(self, llm_client=None, sandbox=None):
        self.llm_client = llm_client
        self.sandbox = sandbox
    
    async def generate_tests(
        self,
        code: str,
        file_path: str,
        test_type: str = "basic"
    ) -> Optional[str]:
        """Generate tests for code."""
        if not self.llm_client:
            return None
        
        prompt = f"""Generate pytest unit tests for the following Python code.

Code:
`python
{code}
`

Generate a test file with:
- Test class named Test{Path(file_path).stem.title().replace('_', '')}
- At least 3 test methods covering main functionality
- Use pytest fixtures where appropriate
- Include edge case tests

Return ONLY the test code, no explanations."""
        
        try:
            response = await self.llm_client.generate(prompt)
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            print(f"Failed to generate tests: {e}")
            return None
    
    async def run_tests(
        self,
        test_code: str,
        source_code: Optional[str] = None,
        timeout: int = 30
    ) -> TestSuiteResult:
        """Run tests in sandbox."""
        if not self.sandbox:
            return TestSuiteResult(total=0, passed=0, failed=0, results=[])
        
        test_content = test_code
        if source_code:
            test_content = source_code + "\n\n" + test_content
        
        result = await self.sandbox.run_command(
            "python -m pytest -v --tb=short -x",
            timeout=timeout
        )
        
        return self._parse_pytest_output(result.stdout, result.stderr)
    
    def _parse_pytest_output(self, stdout: str, stderr: str) -> TestSuiteResult:
        """Parse pytest output."""
        results = []
        total = 0
        passed = 0
        failed = 0
        
        output = stdout + "\n" + stderr
        
        for line in output.split("\n"):
            if "PASSED" in line:
                test_name = line.split("::")[-1].split(" ")[0] if "::" in line else "unknown"
                results.append(TestResult(name=test_name, passed=True))
                passed += 1
                total += 1
            elif "FAILED" in line:
                test_name = line.split("::")[-1].split(" ")[0] if "::" in line else "unknown"
                error = line.split(" - ")[-1] if " - " in line else "Test failed"
                results.append(TestResult(name=test_name, passed=False, error_message=error))
                failed += 1
                total += 1
        
        return TestSuiteResult(total=total, passed=passed, failed=failed, results=results)
    
    async def generate_and_run(
        self,
        code: str,
        file_path: str,
        source_code: Optional[str] = None
    ) -> TestSuiteResult:
        """Generate and run tests."""
        test_code = await self.generate_tests(code, file_path)
        
        if not test_code:
            return TestSuiteResult(total=0, passed=0, failed=0, results=[])
        
        return await self.run_tests(test_code, source_code)
    
    def format_test_summary(self, result: TestSuiteResult) -> str:
        """Format test results summary."""
        if result.total == 0:
            return "No tests run"
        
        lines = [
            f"Tests: {result.total}",
            f"Passed: {result.passed}",
            f"Failed: {result.failed}",
            ""
        ]
        
        if result.results:
            lines.append("Details:")
            for r in result.results:
                status = "PASS" if r.passed else "FAIL"
                lines.append(f"  {status} {r.name}")
                if r.error_message:
                    lines.append(f"      Error: {r.error_message[:100]}")
        
        return "\n".join(lines)
