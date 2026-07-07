"""Executor agent for running commands and code."""

import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from auto_vibe.integrations.llm import LLMClient


class AgentExecutor:
    """Executor agent that runs shell commands and code."""

    def __init__(self, client: LLMClient):
        self.client = client

    async def run_command(self, command: str, timeout: int = 60) -> dict[str, Any]:
        """Run a shell command and return the result."""
        try:
            args = shlex.split(command)
            result = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "Command timed out"
            }
        except Exception as e:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }

    async def run_python(self, code: str) -> dict[str, Any]:
        """Run Python code and return the result."""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                tmp_path = f.name
            try:
                result = subprocess.run(
                    ["python", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                return {
                    "success": result.returncode == 0,
                    "returncode": result.returncode,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
            finally:
                Path(tmp_path).unlink(missing_ok=True)
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": "Code execution timed out"
            }
        except Exception as e:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": str(e)
            }
