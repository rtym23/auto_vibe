"""AutoVibe Test Suite - Core Modules Tests.

This test suite covers:
- LLM Client (Ollama, OpenAI)
- MemoryVault (checkpoint, search, decay)
- CostCalculator (tracking, summary)
- Settings and configuration

Run with: pytest tests/ -v
"""

import pytest
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from auto_vibe.config.settings import Settings, LLMConfig, MemoryConfig, CostConfig
from auto_vibe.integrations.llm import OllamaClient, LLMResponse
from auto_vibe.memory.vault import MemoryVault
from auto_vibe.cost.calculator import CostCalculator, IterationRecord


# ============================================================================
# LLM Client Tests
# ============================================================================

@pytest.mark.asyncio
async def test_ollama_client_creation():
    """Test that OllamaClient can be created with config."""
    config = LLMConfig(provider="ollama", model="qwen3-8b-q4_k_m")
    client = OllamaClient(config)
    assert client.config.model == "qwen3-8b-q4_k_m"
    assert client.config.provider == "ollama"


def test_settings_defaults():
    """Test default settings values."""
    settings = Settings()
    assert settings.llm.provider in ["mock", "openai"]
    assert settings.llm.model in ["demo", "zai-org/glm-4.6v-flash"]
    assert settings.dashboard.port == 7891
    assert settings.max_tokens == 60000


def test_settings_load():
    """Test settings can be loaded."""
    settings = Settings.load()
    assert settings is not None
    assert hasattr(settings, 'llm')
    assert hasattr(settings, 'memory')
    assert hasattr(settings, 'cost')


# ============================================================================
# MemoryVault Tests
# ============================================================================

def test_memory_vault_creation():
    """Test MemoryVault can be created."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    assert vault is not None
    assert vault.config.enabled is True


def test_memory_vault_add_entry():
    """Test adding entries to memory."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    
    vault.add_entry("Test task completed", {"status": "success", "task": "test"})
    entries = vault.get_recent_entries(limit=10)
    
    assert len(entries) >= 1
    assert entries[-1]["content"] == "Test task completed"


def test_memory_vault_checkpoint_save():
    """Test checkpoint saving."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    
    state = {
        "iteration": 5,
        "task": "Generate calculator",
        "file_content": "print('hello')"
    }
    
    vault.save_checkpoint(state)
    
    checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
    assert checkpoint_path.exists()
    
    # Verify checkpoint content
    data = json.loads(checkpoint_path.read_text())
    assert data["state"]["iteration"] == 5
    assert data["state"]["task"] == "Generate calculator"


def test_memory_vault_checkpoint_load():
    """Test checkpoint loading."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    
    # First save a checkpoint
    state = {"iteration": 3, "task": "test_task"}
    vault.save_checkpoint(state)
    
    # Then load it
    loaded = vault.load_checkpoint()
    assert loaded is not None
    assert loaded["iteration"] == 3
    assert loaded["task"] == "test_task"


def test_memory_vault_checkpoint_clear():
    """Test checkpoint clearing."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    
    # Save and then clear
    vault.save_checkpoint({"iteration": 1, "task": "test"})
    vault.clear_checkpoint()
    
    checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
    assert not checkpoint_path.exists()


def test_memory_vault_search():
    """Test memory search functionality."""
    config = MemoryConfig(enabled=True)
    vault = MemoryVault(config)
    
    # Add some entries
    vault.add_entry("Fixed syntax error in calculator.py", {"status": "success"})
    vault.add_entry("Generated UI component", {"status": "success"})
    vault.add_entry("Failed to fix import error", {"status": "failed"})
    
    # Search for "calculator"
    results = vault.search_memory("calculator", limit=5)
    assert len(results) >= 1
    assert "calculator" in results[0]["content"].lower()


# ============================================================================
# CostCalculator Tests
# ============================================================================

def test_cost_calculator_creation():
    """Test CostCalculator can be created."""
    config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    calc = CostCalculator(config)
    assert calc is not None
    assert calc.config.price_per_1k_tokens == 0.001


def test_cost_calculator_record_iteration():
    """Test recording iteration costs."""
    config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    calc = CostCalculator(config)
    calc.start_session()
    
    record = calc.record_iteration(
        iteration_num=1,
        prompt_tokens=1000,
        completion_tokens=500,
        elapsed_seconds=2.5,
        model_name="qwen3-8b"
    )
    
    assert record is not None
    assert record.prompt_tokens == 1000
    assert record.completion_tokens == 500
    # Cost = (1000 + 500) / 1000 * 0.001 = 0.0015
    assert record.estimated_cost_usd == 0.0015


def test_cost_calculator_total_cost():
    """Test total cost calculation."""
    config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    calc = CostCalculator(config)
    calc.start_session()
    
    # Record multiple iterations
    calc.record_iteration(1, 1000, 500, 2.0, "qwen3-8b")
    calc.record_iteration(2, 1500, 800, 3.0, "qwen3-8b")
    calc.record_iteration(3, 2000, 1000, 4.0, "qwen3-8b")
    
    totals = calc.get_total_cost()
    
    assert totals["total_tokens"] == 6800  # (1000+500) + (1500+800) + (2000+1000)
    assert totals["total_time"] == 9.0  # 2.0 + 3.0 + 4.0
    assert totals["estimated_cost_usd"] == 0.0068  # 6800/1000 * 0.001


def test_cost_calculator_format_summary():
    """Test summary formatting."""
    config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    calc = CostCalculator(config)
    calc.start_session()
    
    calc.record_iteration(1, 1000, 500, 2.0, "qwen3-8b")
    
    summary = calc.format_summary()
    
    assert "AutoVibe" in summary
    assert "qwen3-8b" in summary
    assert "1,500" in summary  # total tokens


def test_cost_per_iteration():
    """Test average cost per iteration."""
    config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    calc = CostCalculator(config)
    calc.start_session()
    
    calc.record_iteration(1, 1000, 500, 2.0, "qwen3-8b")
    calc.record_iteration(2, 1000, 500, 2.0, "qwen3-8b")
    
    avg = calc.get_cost_per_iteration()
    assert avg == 0.0015  # (1500/1000 * 0.001) per iteration average


# ============================================================================
# Integration Tests
# ============================================================================

def test_full_memory_cost_integration():
    """Test memory and cost work together."""
    # Setup
    memory_config = MemoryConfig(enabled=True)
    cost_config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
    
    vault = MemoryVault(memory_config)
    calc = CostCalculator(cost_config)
    
    # Simulate a task
    task = "Generate calculator with advanced functions"
    
    # Save to memory
    vault.add_entry(f"Task: {task}\nResult: success", {"status": "success", "task": task})
    
    # Record cost
    calc.record_iteration(1, 2000, 1000, 3.0, "qwen3-8b")
    
    # Verify both work
    entries = vault.get_recent_entries(limit=1)
    assert len(entries) >= 1
    
    totals = calc.get_total_cost()
    assert totals["total_tokens"] == 3000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
