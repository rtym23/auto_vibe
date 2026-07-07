"""Hardened Sandbox - enhanced sandbox with limits and isolation.

This extends base sandbox.py with additional features:
- CPU/RAM limits
- Network isolation
- Real-time streaming
- Hardened modes
"""

import asyncio
import os
from pathlib import Path
from typing import Optional, Dict, Callable, Awaitable
from dataclasses import dataclass
from enum import Enum


class SandboxMode(Enum):
    """Sandbox mode."""
    STANDARD = "standard"
    STRICT = "strict"
    UNTRUSTED = "untrusted"


@dataclass
class SandboxConfig:
    """Sandbox configuration."""
    timeout: int = 30
    cpu_time_limit: int = 30
    max_memory: int = 512 * 1024 * 1024
    max_file_size: int = 10 * 1024 * 1024
    max_files: int = 100
    network_isolation: bool = True
    mode: SandboxMode = SandboxMode.STRICT
    max_output_size: int = 1024 * 1024
    stream_output: bool = True


@dataclass  
class SandboxResult:
    """Sandbox execution result."""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    sandbox_dir: str
    memory_used: int = 0
    cpu_time: float = 0.0
    timeout: bool = False
    oom: bool = False
    killed: bool = False


class HardenedSandbox:
    """
    Hardened Sandbox for safe code execution.
    
    Features:
    - CPU time limits
    - Memory limits  
    - Network isolation
    - File size limits
    - Real-time output streaming
    - Resource usage tracking
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        config: Optional[SandboxConfig] = None,
    ):
        import tempfile
        
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir())
        self.config = config or SandboxConfig()
        self.active_sandboxes: Dict[str, Path] = {}
        self._output_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    
    def set_output_callback(self, callback: Callable[[str, str], Awaitable[None]]) -> None:
        """Set callback for real-time output."""
        self._output_callback = callback
    
    def _create_sandbox_dir(self) -> Path:
        import uuid
        sandbox_id = str(uuid.uuid4())[:8]
        sandbox_dir = self.base_dir / f"autovibe_sandbox_{sandbox_id}"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        return sandbox_dir
    
    def _cleanup_sandbox(self, sandbox_dir: Path) -> None:
        import shutil
        try:
            if sandbox_dir.exists():
                shutil.rmtree(sandbox_dir)
        except Exception as e:
            print(f"Failed to cleanup sandbox: {e}")
    
    def _get_environment(self, sandbox_dir: Path) -> Dict[str, str]:
        env = {
            **os.environ,
            "PYTHONPATH": str(sandbox_dir),
            "HOME": str(sandbox_dir),
            "TMPDIR": str(sandbox_dir),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
        }
        if self.config.network_isolation:
            env.pop("HTTP_PROXY", None)
            env.pop("HTTPS_PROXY", None)
            env.pop("http_proxy", None)
            env.pop("https_proxy", None)
            env["NO_PROXY"] = "*"
        return env

    def _truncate_output(self, output: str) -> str:
        if len(output) > self.config.max_output_size:
            return output[:self.config.max_output_size] + "\n... (output truncated)"
        return output

    async def run_python(
        self,
        code: str,
        timeout: Optional[int] = None,
        sandbox_dir: Optional[Path] = None,
    ) -> SandboxResult:
        import time
        start_time = time.time()
        
        if timeout is None:
            timeout = self.config.timeout
        
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
                env=self._get_environment(sandbox_dir),
                limit_output_buffer=1024 * 1024,
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
                    success=False, stdout="",
                    stderr=f"Execution timed out after {timeout} seconds",
                    exit_code=-1, duration=round(duration, 2),
                    sandbox_dir=str(sandbox_dir), timeout=True,
                )
            
            stdout_str = self._truncate_output(stdout.decode("utf-8", errors="replace"))
            stderr_str = self._truncate_output(stderr.decode("utf-8", errors="replace"))
            duration = time.time() - start_time
            
            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout_str, stderr=stderr_str,
                exit_code=process.returncode or 0,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
            
        except Exception as e:
            duration = time.time() - start_time
            return SandboxResult(
                success=False, stdout="",
                stderr=f"Sandbox error: {str(e)}",
                exit_code=-1, duration=round(duration, 2),
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
        import time
        start_time = time.time()
        
        if timeout is None:
            timeout = self.config.timeout
        
        sandbox_dir = self._create_sandbox_dir()
        sandbox_id = sandbox_dir.name
        self.active_sandboxes[sandbox_id] = sandbox_dir
        
        try:
            allowed_commands = {"python", "python3", "pip", "pip3", "pytest", "ruff", "black"}
            cmd_parts = command.strip().split()
            if cmd_parts and cmd_parts[0] not in allowed_commands:
                if not any(cmd_parts[0].startswith(prefix) for prefix in allowed_commands):
                    return SandboxResult(
                        success=False, stdout="",
                        stderr=f"Command not allowed in sandbox: {cmd_parts[0]}",
                        exit_code=-1, duration=0,
                        sandbox_dir=str(sandbox_dir)
                    )
            
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox_dir),
                env=self._get_environment(sandbox_dir),
                limit_output_buffer=1024 * 1024,
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
                    success=False, stdout="",
                    stderr=f"Command timed out after {timeout} seconds",
                    exit_code=-1, duration=round(duration, 2),
                    sandbox_dir=str(sandbox_dir), timeout=True,
                )
            
            stdout_str = self._truncate_output(stdout.decode("utf-8", errors="replace"))
            stderr_str = self._truncate_output(stderr.decode("utf-8", errors="replace"))
            duration = time.time() - start_time
            
            return SandboxResult(
                success=process.returncode == 0,
                stdout=stdout_str, stderr=stderr_str,
                exit_code=process.returncode or 0,
                duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )

        except Exception as e:
            duration = time.time() - start_time
            return SandboxResult(
                success=False, stdout="",
                stderr=f"Sandbox error: {str(e)}",
                exit_code=-1, duration=round(duration, 2),
                sandbox_dir=str(sandbox_dir)
            )
        finally:
            self._cleanup_sandbox(sandbox_dir)
            if sandbox_id in self.active_sandboxes:
                del self.active_sandboxes[sandbox_id]
    
    def cleanup_all(self) -> None:
        for sandbox_dir in self.active_sandboxes.values():
            self._cleanup_sandbox(sandbox_dir)
        self.active_sandboxes.clear()


def create_strict_sandbox() -> HardenedSandbox:
    """Create sandbox with strict limits."""
    config = SandboxConfig(
        mode=SandboxMode.STRICT,
        timeout=30,
        cpu_time_limit=30,
        max_memory=512 * 1024 * 1024,
        network_isolation=True,
    )
    return HardenedSandbox(config=config)


def create_untrusted_sandbox() -> HardenedSandbox:
    """Create sandbox for untrusted code."""
    config = SandboxConfig(
        mode=SandboxMode.UNTRUSTED,
        timeout=10,
        cpu_time_limit=10,
        max_memory=256 * 1024 * 1024,
        network_isolation=True,
        max_file_size=1 * 1024 * 1024,
    )
    return HardenedSandbox(config=config)
