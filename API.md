# AutoVibe API Documentation

## Overview

AutoVibe provides a Python API for autonomous code generation and self-healing loops. It integrates with local LLMs (Ollama, LM Studio) and cloud APIs.

## Core Classes

### AutoVibeLoop

Main loop that handles code generation, execution, and fixing.

```python
from auto_vibe.core.loop import AutoVibeLoop
from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import create_llm_client

settings = Settings.load()
client = create_llm_client(settings.llm)
loop = AutoVibeLoop(settings, client)
```

#### Methods

##### `run(task, target_file=None, command=None)`

Run the self-healing loop for a task.

**Parameters:**
- `task` (str): Description of the task
- `target_file` (str | Path, optional): Target file path
- `command` (str, optional): Command to run for verification

**Returns:**
- `bool`: True if task completed successfully

**Example:**
```python
result = await loop.run(
    task="Create a calculator with advanced functions",
    target_file="calculator.py"
)
```

##### `count_tokens(text)`

Count tokens in text (approximate).

**Parameters:**
- `text` (str): Text to count tokens for

**Returns:**
- `int`: Approximate token count

---

### MemoryVault

Persistent memory with decay for storing solutions.

```python
from auto_vibe.memory.vault import MemoryVault
from auto_vibe.config.settings import MemoryConfig

config = MemoryConfig(enabled=True)
vault = MemoryVault(config)
```

#### Methods

##### `add_entry(content, metadata=None)`

Add a new entry to memory.

**Parameters:**
- `content` (str): The content to store
- `metadata` (dict, optional): Additional metadata

##### `get_recent_entries(limit=10)`

Get recent memory entries.

**Parameters:**
- `limit` (int): Maximum number of entries

**Returns:**
- `List[Dict]`: List of memory entries

##### `save_checkpoint(state)`

Save current state for recovery.

**Parameters:**
- `state` (dict): State to save

##### `load_checkpoint()`

Load saved checkpoint.

**Returns:**
- `dict` or `None`: Saved state or None

##### `search_memory(query, limit=5)`

Search memory for entries.

**Parameters:**
- `query` (str): Search query
- `limit` (int): Maximum results

**Returns:**
- `List[Dict]`: Matching entries

---

### CostCalculator

Track and calculate costs for LLM usage.

```python
from auto_vibe.cost.calculator import CostCalculator
from auto_vibe.config.settings import CostConfig

config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
calc = CostCalculator(config)
```

#### Methods

##### `start_session()`

Start a new cost tracking session.

##### `record_iteration(iteration_num, prompt_tokens, completion_tokens, elapsed_seconds, model_name)`

Record a single iteration's cost.

**Parameters:**
- `iteration_num` (int): Iteration number
- `prompt_tokens` (int): Prompt tokens used
- `completion_tokens` (int): Completion tokens used
- `elapsed_seconds` (float): Time taken
- `model_name` (str): Model name

**Returns:**
- `IterationRecord`: Cost record

##### `get_total_cost()`

Get total cost for session.

**Returns:**
- `dict`: Total tokens, time, and cost

##### `format_summary()`

Get human-readable cost summary.

**Returns:**
- `str`: Formatted summary

---

### Settings

Configuration management.

```python
from auto_vibe.config.settings import Settings

# Load from default locations
settings = Settings.load()

# Or with custom path
settings = Settings.load("~/.auto_vibe/config.yaml")
```

#### Configuration Sections

##### LLM Configuration

```python
settings.llm.provider  # "ollama", "openai", "mesh_llm"
settings.llm.model     # Model name (e.g., "qwen3-8b-q4_k_m")
settings.llm.base_url  # API base URL
settings.llm.api_key   # API key (if needed)
```

##### Executor Configuration

```python
settings.executor.timeout       # Command timeout in seconds
settings.executor.max_memory_mb # Max memory in MB
settings.executor.use_venv      # Use virtual environment
```

##### Memory Configuration

```python
settings.memory.enabled       # Enable memory
settings.memory.decay_rate    # Decay rate (0-1)
settings.memory.max_entries   # Max entries to store
settings.memory.vault_path    # Path to vault file
```

##### Cost Configuration

```python
settings.cost.enabled            # Enable cost tracking
settings.cost.price_per_1k_tokens # Price per 1K tokens
settings.cost.currency           # Currency code
```

##### Dashboard Configuration

```python
settings.dashboard.enabled  # Enable dashboard
settings.dashboard.host     # Host to bind to
settings.dashboard.port     # Port (default 7891)
```

##### Token Configuration

```python
settings.tokens.max_context_tokens     # Max context tokens (default 60000)
settings.tokens.checkpoint_interval    # Checkpoint every N iterations
settings.max_tokens                     # Alias for max_context_tokens
```

---

## MCP Tools

AutoVibe exposes the following MCP tools:

### `ask_ai(prompt: str) -> str`

Ask the AI a question directly.

**Parameters:**
- `prompt` (str): Question or task description

**Returns:**
- `str`: AI response

### `get_status() -> str`

Get system status.

**Returns:**
- `str`: Status message

### `fix_file(file_path: str, error_description: str) -> str`

Fix a specific file based on error description.

**Parameters:**
- `file_path` (str): Path to file to fix
- `error_description` (str): Description of the error

**Returns:**
- `str`: Success or failure message

### `run_loop(task: str, target_file: str | None = None, command: str | None = None) -> str`

Run the self-healing loop.

**Parameters:**
- `task` (str): Task description
- `target_file` (str, optional): Target file path
- `command` (str, optional): Verification command

**Returns:**
- `str`: "✅ Успех" or "❌ Неудача"

### `plan_and_execute(prompt: str) -> str`

Create a plan and execute it in stages.

**Parameters:**
- `prompt` (str): Goal description

**Returns:**
- `str`: Execution result

---

## Error Handling

All async methods may raise:

- `LLMConnectionError`: Cannot connect to LLM
- `LLMTimeoutError`: LLM request timed out
- `LLMResponseError`: Invalid LLM response

---

## Examples

### Basic Code Generation

```python
import asyncio
from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import create_llm_client
from auto_vibe.core.loop import AutoVibeLoop

async def main():
    settings = Settings.load()
    client = create_llm_client(settings.llm)
    loop = AutoVibeLoop(settings, client)
    
    result = await loop.run(
        task="Create a calculator with advanced functions",
        target_file="calculator.py"
    )
    
    print(f"Success: {result}")

asyncio.run(main())
```

### Cost Tracking

```python
from auto_vibe.cost.calculator import CostCalculator
from auto_vibe.config.settings import CostConfig

config = CostConfig(enabled=True, price_per_1k_tokens=0.001)
calc = CostCalculator(config)
calc.start_session()

# After each iteration
calc.record_iteration(
    iteration_num=1,
    prompt_tokens=1000,
    completion_tokens=500,
    elapsed_seconds=2.5,
    model_name="qwen3-8b"
)

print(calc.format_summary())
```

### Memory Search

```python
from auto_vibe.memory.vault import MemoryVault
from auto_vibe.config.settings import MemoryConfig

config = MemoryConfig(enabled=True)
vault = MemoryVault(config)

# Search for previous solutions
results = vault.search_memory("calculator", limit=5)
for entry in results:
    print(entry["content"])
```

---

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_MAX_TOKENS` | 60000 | Default context limit |
| `DEFAULT_PORT` | 7891 | Dashboard port |
| `CHECKPOINT_PATH` | ~/.auto_vibe/checkpoint.json | Checkpoint file |
| `VAULT_PATH` | ~/.auto_vibe/vault.json | Memory vault file |
