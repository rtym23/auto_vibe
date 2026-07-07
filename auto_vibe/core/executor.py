import asyncio
import os
from dataclasses import dataclass
from typing import Optional

from auto_vibe.config.settings import ExecutorConfig


@dataclass
class ExecutionResult:
    """
    Command execution result.
    """
    stdout: str
    stderr: str
    exit_code: int
    duration: float


class Executor:
    """
    Executes commands in an isolated environment.
    """

    def __init__(self, config: ExecutorConfig):
        self.config = config

    async def run_command(self, command: str, timeout: Optional[float] = None) -> ExecutionResult:
        """
        Runs a command in shell.
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds (default from config)
        """
        if timeout is None:
            timeout = self.config.timeout
        
        start_time = asyncio.get_event_loop().time()
        
        try:
            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = asyncio.get_event_loop().time() - start_time
                return ExecutionResult(
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    exit_code=-1,
                    duration=round(duration, 2),
                )

            duration = asyncio.get_event_loop().time() - start_time

            return ExecutionResult(
                stdout=stdout.decode("utf-8", errors="replace").strip(),
                stderr=stderr.decode("utf-8", errors="replace").strip(),
                exit_code=process.returncode or 0,
                duration=round(duration, 2),
            )
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            return ExecutionResult(
                stdout="",
                stderr=f"Execution error: {str(e)}",
                exit_code=-1,
                duration=round(duration, 2),
            )
