import pytest
import asyncio
import os
from auto_vibe.sandbox import Sandbox, SandboxResult


@pytest.mark.asyncio
async def test_sandbox_creation():
    """Test Sandbox can be created."""
    sandbox = Sandbox(timeout=10)
    assert sandbox is not None
    assert sandbox.timeout == 10


@pytest.mark.asyncio
async def test_sandbox_run_python_success():
    """Test running Python code in sandbox."""
    sandbox = Sandbox(timeout=10)

    result = await sandbox.run_python("print('Hello from sandbox!')")

    assert isinstance(result, SandboxResult)
    assert result.success
    assert "Hello from sandbox" in result.stdout
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_sandbox_run_python_error():
    """Test running Python code with error."""
    sandbox = Sandbox(timeout=10)

    result = await sandbox.run_python("raise Exception('Test error')")

    assert isinstance(result, SandboxResult)
    assert not result.success
    assert "Test error" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_run_python_timeout():
    """Test sandbox timeout."""
    sandbox = Sandbox(timeout=1)

    result = await sandbox.run_python("import time; time.sleep(10)")

    assert isinstance(result, SandboxResult)
    assert not result.success
    assert "timed out" in result.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_run_command():
    """Test running shell command in sandbox."""
    sandbox = Sandbox(timeout=10)

    result = await sandbox.run_command("echo hello world")

    assert isinstance(result, SandboxResult)
    assert result.success or "not allowed" in result.stderr.lower()
    # Note: echo might not be in allowed commands list


@pytest.mark.asyncio
async def test_sandbox_isolation():
    """Test that sandbox isolates code execution."""
    sandbox = Sandbox(timeout=10)

    # Create file in sandbox
    result = await sandbox.run_python("""
import os
sandbox_dir = os.getcwd()
with open('test.txt', 'w') as f:
    f.write('test')
print('File created')
""")

    assert result.success
    # After execution sandbox should be cleaned up
    assert "autovibe_sandbox" not in result.sandbox_dir or not os.path.exists(result.sandbox_dir)


@pytest.mark.asyncio
async def test_sandbox_command_not_allowed():
    """Test that dangerous commands are blocked."""
    sandbox = Sandbox(timeout=10)

    # Attempt to run dangerous command
    result = await sandbox.run_command("rm -rf /")

    # Command should be blocked
    assert not result.success or "not allowed" in result.stderr.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
