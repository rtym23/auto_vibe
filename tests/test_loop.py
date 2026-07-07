"""AutoVibe Test Suite - Loop and Executor Tests.

Tests for:
- AutoVibeLoop (main loop logic)
- Executor (command execution)
- Analyzer (error analysis)
- Fixer (code fixing)

Run with: pytest tests/test_loop.py -v
"""

import pytest
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from auto_vibe.config.settings import Settings, ExecutorConfig
from auto_vibe.core.loop import AutoVibeLoop
from auto_vibe.core.executor import Executor, ExecutionResult
from auto_vibe.core.analyzer import Analyzer
from auto_vibe.core.fixer import Fixer
from auto_vibe.integrations.llm import LLMClient, LLMResponse


# ============================================================================
# Executor Tests
# ============================================================================

@pytest.mark.asyncio
async def test_executor_creation():
    """Test Executor can be created."""
    config = ExecutorConfig(timeout=30, max_memory_mb=512)
    executor = Executor(config)
    assert executor is not None
    assert executor.config.timeout == 30


@pytest.mark.asyncio
async def test_executor_run_simple_command():
    """Test running a simple command."""
    config = ExecutorConfig(timeout=10)
    executor = Executor(config)
    
    result = await executor.run_command("echo hello")
    
    assert result is not None
    assert result.exit_code == 0
    assert "hello" in result.stdout.lower()


@pytest.mark.asyncio
async def test_executor_run_failing_command():
    """Test running a failing command."""
    config = ExecutorConfig(timeout=10)
    executor = Executor(config)
    
    result = await executor.run_command("python -c 'raise Exception(\"test\")'")
    
    assert result is not None
    assert result.exit_code != 0


@pytest.mark.asyncio
async def test_executor_timeout():
    """Test command timeout."""
    config = ExecutorConfig(timeout=1)
    executor = Executor(config)
    
    # Use ping -n on Windows, sleep on Unix
    import sys
    if sys.platform == "win32":
        cmd = "ping -n 10 127.0.0.1"  # Will take ~9 seconds
    else:
        cmd = "sleep 10"
    
    result = await executor.run_command(cmd)
    
    # Should either timeout (-1) or fail
    assert result.exit_code in [-1, 1]


# ============================================================================
# Analyzer Tests
# ============================================================================

def test_analyzer_creation():
    """Test Analyzer can be created."""
    analyzer = Analyzer()
    assert analyzer is not None


def test_analyzer_syntax_error():
    """Test analyzing syntax error."""
    analyzer = Analyzer()
    
    result = ExecutionResult(
        stdout="",
        stderr="SyntaxError: invalid syntax (line 1)",
        exit_code=1,
        duration=0.1
    )
    
    error_msg = analyzer.analyze_error(result)
    
    assert error_msg is not None
    assert "syntax" in error_msg.lower()


def test_analyzer_name_error():
    """Test analyzing name error."""
    analyzer = Analyzer()
    
    result = ExecutionResult(
        stdout="",
        stderr="NameError: name 'undefined_var' is not defined",
        exit_code=1,
        duration=0.1
    )
    
    error_msg = analyzer.analyze_error(result)
    
    assert error_msg is not None
    assert "name" in error_msg.lower() or "undefined" in error_msg.lower()


def test_analyzer_import_error():
    """Test analyzing import error."""
    analyzer = Analyzer()
    
    result = ExecutionResult(
        stdout="",
        stderr="ImportError: No module named 'nonexistent_module'",
        exit_code=1,
        duration=0.1
    )
    
    error_msg = analyzer.analyze_error(result)
    
    assert error_msg is not None
    assert "import" in error_msg.lower()


# ============================================================================
# Fixer Tests
# ============================================================================

@pytest.mark.asyncio
async def test_fixer_creation():
    """Test Fixer can be created."""
    mock_client = MagicMock(spec=LLMClient)
    fixer = Fixer(mock_client)
    
    assert fixer is not None
    assert fixer.llm_client == mock_client


@pytest.mark.asyncio
async def test_fixer_suggest_fix():
    """Test Fixer suggests a fix."""
    # Create mock LLM client
    mock_client = MagicMock(spec=LLMClient)
    mock_client.generate = AsyncMock(return_value=LLMResponse(
        content="# Fixed code\nprint('hello')",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
        model="test-model"
    ))
    
    fixer = Fixer(mock_client)
    
    fix = await fixer.suggest_fix(
        error_msg="SyntaxError: invalid syntax",
        file_path="test.py",
        file_content="print('hello"
    )
    
    assert fix is not None
    assert "fixed" in fix.lower() or "print" in fix.lower()


# ============================================================================
# AutoVibeLoop Tests
# ============================================================================

@pytest.mark.asyncio
async def test_loop_creation():
    """Test AutoVibeLoop can be created."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    
    loop = AutoVibeLoop(settings, mock_client)
    
    assert loop is not None
    assert loop.llm_client == mock_client
    assert loop.memory is not None
    assert loop.cost_calc is not None


def test_loop_count_tokens():
    """Test token counting."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    loop = AutoVibeLoop(settings, mock_client)
    
    # Test with sample text
    text = "Hello, this is a test string for token counting."
    tokens = loop.count_tokens(text)
    
    assert tokens > 0
    assert tokens == len(text) // 3  # Approximate calculation


def test_loop_count_tokens_empty():
    """Test token counting with empty string."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    loop = AutoVibeLoop(settings, mock_client)
    
    assert loop.count_tokens("") == 0
    assert loop.count_tokens(None) == 0


@pytest.mark.asyncio
async def test_loop_get_context_from_memory():
    """Test getting context from memory."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    loop = AutoVibeLoop(settings, mock_client)
    
    # Add some entries to memory
    if loop.memory:
        loop.memory.add_entry("Fixed bug in calculator", {"status": "success"})
    
    context = loop._get_context_from_memory()
    
    # Context should contain previous experience
    assert context is not None


@pytest.mark.asyncio
async def test_loop_save_checkpoint():
    """Test checkpoint saving in loop."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    loop = AutoVibeLoop(settings, mock_client)
    
    loop._save_checkpoint(5, "test task", "print('hello')")
    
    checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
    assert checkpoint_path.exists()


@pytest.mark.asyncio
async def test_loop_load_checkpoint():
    """Test checkpoint loading in loop."""
    settings = Settings()
    mock_client = MagicMock(spec=LLMClient)
    loop = AutoVibeLoop(settings, mock_client)
    
    # Save checkpoint first
    loop._save_checkpoint(3, "test task", "code")
    
    # Create new loop and load checkpoint
    loop2 = AutoVibeLoop(settings, mock_client)
    checkpoint = loop2._load_checkpoint()
    
    assert checkpoint is not None
    assert checkpoint["iteration"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
