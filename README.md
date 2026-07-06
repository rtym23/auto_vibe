# AutoVibe 🤖

**Self-Healing AI Developer with MCP Integration**

AutoVibe is an autonomous agentic loop that automatically analyzes code, generates fixes, and learns from previous iterations. Built for local LLM deployment with support for Ollama, LM Studio, and cloud APIs.

![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Tests](https://img.shields.io/badge/tests-31%2F31-brightgreen)

## 🚀 Features

- **Self-Healing Loop**: Automatically detect, analyze, and fix code errors
- **Real Code Generation**: LLM-powered code generation (not just stubs)
- **Memory with Decay**: Remembers successful solutions with exponential decay
- **Cost Tracking**: Real-time cost monitoring per iteration
- **Checkpointing**: Resume from saved state on context overflow
- **Token Counting**: Prevents context overflow for local models (~65K limit)
- **WebSocket Dashboard**: Real-time monitoring on port 7891
- **MCP Integration**: Full Model Context Protocol support
- **Real-time Metrics**: Total requests, success/fail rates, token usage
- **Multi-tab Logs**: All, Network, Neural Net, Debug, IDE Errors tabs
- **IDE Error Display**: Separate tab for IDE errors with detailed info
- **Auto-refresh**: Dashboard updates every 5 seconds

## 📋 Requirements

- Python 3.10+
- Local LLM (Ollama, LM Studio) or cloud API
- RTX 4060 Ti 16GB+ recommended for local models

## 🛠️ Installation

```bash
# Clone the repository
git clone https://github.com/your-repo/auto-vibe.git
cd auto-vibe

# Install dependencies
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"

# Configure .env file
cp .env.example .env
# Edit .env with your LLM settings
```

## ⚡ Quick Start

```python
from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import create_llm_client
from auto_vibe.core.loop import AutoVibeLoop

# Load settings
settings = Settings.load()

# Create LLM client
client = create_llm_client(settings.llm)

# Create and run the loop
loop = AutoVibeLoop(settings, client)

# Generate code for a task
result = await loop.run(
    task="Create a calculator with advanced functions",
    target_file="calculator.py"
)

print(f"Success: {result}")
```

## 🎯 MCP Tools

AutoVibe provides the following MCP tools:

| Tool | Description |
|------|-------------|
| `ask_ai(prompt)` | Ask the AI a question |
| `get_status()` | Get system status |
| `fix_file(file_path, error_description)` | Fix a specific file |
| `run_loop(task, target_file, command)` | Run the self-healing loop |
| `plan_and_execute(prompt)` | Create plan and execute stages |

## 📊 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AutoVibeLoop                           │
├─────────────────────────────────────────────────────────────┤
│  1. Generate Code (LLM)                                     │
│  2. Execute (Executor)                                      │
│  3. Analyze Error (Analyzer)                                │
│  4. Web Search (WebSearcher)                                │
│  5. Verify (HallucinationGuard)                             │
│  6. Fix (Fixer)                                             │
│  7. Save to Memory (MemoryVault)                            │
│  8. Track Cost (CostCalculator)                             │
│  9. Checkpoint if needed                                    │
└─────────────────────────────────────────────────────────────┘
```

## 🔧 Configuration

Configuration is managed through `Settings` class with support for:

- **LLM**: Provider, model, base URL, API key
- **Executor**: Timeout, max memory, venv usage
- **Memory**: Enabled, decay rate, max entries
- **Cost**: Enabled, price per 1K tokens
- **Strategy**: Default mode, max iterations
- **Dashboard**: Host, port (default 7891)
- **Tokens**: Max context tokens (default 60000)

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_basic.py -v

# Run with coverage
pytest tests/ --cov=auto_vibe --cov-report=html
```

## 📈 Cost Tracking

AutoVibe tracks costs per iteration:

```
==================================================
  AutoVibe — Cost Summary
==================================================
  Iterations:       3
  Total tokens:     6,800
  Total time:       9.00 s
  Session duration: 12.50 s
  Estimated cost:   0.006800 USD
  Avg cost/iter:    0.002267 USD

  Per-iteration breakdown:
  -----------------------------------------------
  # 1  qwen3-8b             1,500 tokens    2.00 s  0.001500 USD
  # 2  qwen3-8b             2,300 tokens    3.00 s  0.002300 USD
  # 3  qwen3-8b             3,000 tokens    4.00 s  0.003000 USD
==================================================
```

## 🔄 Checkpointing

When context limit is reached (default 60K tokens):
1. Save current state to `~/.auto_vibe/checkpoint.json`
2. Clear context
3. Resume from checkpoint on next run

## 📝 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

See CONTRIBUTING.md for guidelines.

---

**Built with care**
