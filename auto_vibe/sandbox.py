"""
Sandbox - isolated code execution.

Features:
- Execution in temporary directory
- Execution time limits
- Isolation from main system
- Safe subprocess with limits
"""

import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass


@dataclass
class SandboxResult:
    """Sandbox execution result."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    sandbox_dir: str


class Sandbox:
    """
    Sandbox for safe code execution.
    
    Uses:
    - Temporary directory for isolation
    - Subprocess with limits
    - Timeout to prevent hangs
    """
    
    def __init__(
        self,
        base_dir: Optional[str] = None,
        timeout: int = 30,
        max_output_size: int = 1024 * 1024,
    ):
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir())
        self.timeout = timeout
        self.max_output_size = max_output_size
        self.active_sandboxes: Dict[str, Path] = {}
    
    def _create_sandbox_dir(self) -> Path:
        """Create unique directory for sandbox."""
        sandbox_id = str(uuid.uuid4())[:8]
        sandbox_dir = self.base_dir / f"autovibe_sandbox_{sandbox_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        return sandbox_dir
    
    def _cleanup_sandbox(self, sandbox_dir: Path) -> None:
        """Clean up sandbox directory."""
        try:
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir)
        except Exception as e:
            print(f"Failed to cleanup sandbox: {e}")
    
    async def run_python(
        self,
        code: str,
        timeout: Optional[int] = None,
        sandbox_dir: Optional[Path] = None,
    ) -> SandboxResult:
        """Execute Python code in sandbox."""
        import time
        start_time = time.time()
        
        if timeout is None:
            timeout = self.timeout
        
        if sandbox_dir is None:
            sandbox_dir = self._create_sandbox_dir()
        
        sandbox_id = sandbox_dir.name
        self.active_sandboxes[sandbox_id] = sandbox_dir
        
        try:
            code_file = sandbox_dir / "script.py"
            code_file.write_text(code, encoding="utf-8")
            
            process = await asyncio.create_subprocess_exec(
                "python",
                str(code_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox_dir),
                env={
                    **os.environ,
                    "PYTHONPATH": str(sandbox_dir),
                    "HOME": str(sandbox_dir),
                    "TMPDIR": str(sandbox_dir),
                }
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = time.time() - start_time
                return SandboxResult(
                    success=False,
                    stdout="",
                    stderr=f"Execution timed out after {timeout} seconds",
                    exit_code=-1,
                    duration=round(duration, 2),
                    sandbox_dir=str(sandbox_dir)
                )
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            if len(stdout_str) > self.max_output_size:
                stdout_str = stdout_str[:self.max_output_size] + "\n... (output truncated)"
            if len(stderr_str) > self.max_output_size:
                stderr_str = stderr_str[:self.max_output_size] + "\n... (output truncated)"
            
            duration = time.time() - start_time
            
            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode or 0,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Sandbox error: {str(e)}",
                exit_code=-1,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
        finally:
            self._cleanup_sandbox(sandbox_dir)
            if sandbox_id in self.active_sandboxes:
                del self.active_sandboxes[sandbox_id]
    
    async def run_command(
        self,
        command: str,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        """Execute shell command in sandbox."""
        import time
        start_time = time.time()
        
        if timeout is None:
            timeout = self.timeout
        
        sandbox_dir = self._create_sandbox_dir()
        sandbox_id = sandbox_dir.name
        self.active_sandboxes[sandbox_id] = sandbox_dir
        
        try:
            allowed_commands = {
                "python", "python3", "pip", "pip3", "pytest", "ruff", "black"
            }
            
            cmd_parts = command.strip().split()
            if cmd_parts and cmd_parts[0] not in allowed_commands:
                if not any(cmd_parts[0].startswith(prefix) for prefix in allowed_commands):
                    return SandboxResult(
                        success=False,
                        stdout="",
                        stderr=f"Command not allowed in sandbox: {cmd_parts[0]}",
                        exit_code=-1,
                        duration=0,
                        sandbox_dir=str(sandbox_dir)
                    )
            
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox_dir),
                env={
                    **os.environ,
                    "HOME": str(sandbox_dir),
                    "TMPDIR": str(sandbox_dir),
                }
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                duration = time.time() - start_time
                return SandboxResult(
                    success=False,
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    exit_code=-1,
                    duration=round(duration, 2),
                    sandbox_dir=str(sandbox_dir)
                )
            
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")
            
            if len(stdout_str) > self.max_output_size:
                stdout_str = stdout_str[:self.max_output_size] + "\n... (output truncated)"
            if len(stderr_str) > self.max_output_size:
                stderr_str = stderr_str[:self.max_output_size] + "\n... (output truncated)"
            
            duration = time.time() - start_time
            
            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout_str,
                stderr=stderr_str,
                exit_code=process.returncode or 0,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return SandboxResult(
                success=False,
                stdout="",
                stderr=f"Sandbox error: {str(e)}",
                exit_code=-1,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
        finally:
            self._cleanup_sandbox(sandbox_dir)
            if sandbox_id in self.active_sandboxes:
                del self.active_sandboxes[sandbox_id]
    
    def cleanup_all(self) -> None:
        """Clean up all active sandbox directories."""
        for sandbox_dir in self.active_sandboxes.values():
            self._cleanup_sandbox(sandbox_dir)
        self.active_sandboxes.clear()
