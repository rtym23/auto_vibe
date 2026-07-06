# Contributing to AutoVibe

Thank you for your interest in contributing to AutoVibe!

## 🎯 Development Goals

- **Self-Healing**: Code that fixes itself
- **Local-First**: Optimized for local LLM deployment
- **Cost-Efficient**: Minimize API credits usage
- **Production-Ready**: Quick to set up, reliable during use

## 🚀 Quick Start for Contributors

```bash
# Clone and setup
git clone https://github.com/rtym23/auto_vibe.git
cd auto_vibe
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Start development server
python -m auto_vibe.server
```

## 📁 Project Structure

```
auto_vibe/
├── agents/          # Planner and agent logic
├── config/          # Settings and configuration
├── core/            # Main loop, executor, analyzer, fixer
├── cost/            # Cost tracking and calculation
├── dashboard/       # WebSocket dashboard
├── integrations/    # LLM clients, web search, hallucination guard
├── memory/          # MemoryVault with decay
├── network/         # Reconnection management
└── server.py        # MCP server entry point

tests/
├── test_basic.py    # Core module tests
└── test_loop.py     # Loop and executor tests
```

## ✅ Code Standards

- **Language**: Python 3.10+
- **Comments**: English, clear and concise
- **Type Hints**: Use where possible
- **Docstrings**: Google-style for public APIs
- **Testing**: pytest with async support

## 🧪 Writing Tests

```python
# Example test structure
import pytest
from auto_vibe.module import MyClass

def test_my_class_creation():
    """Test that MyClass can be created."""
    obj = MyClass()
    assert obj is not None

@pytest.mark.asyncio
async def test_async_method():
    """Test async method behavior."""
    result = await some_async_method()
    assert result == expected
```

## 🔧 Adding New Features

1. **Fork** the repository
2. Create a **feature branch** (`git checkout -b feature/amazing-feature`)
3. **Write code** with tests
4. **Run tests** to ensure nothing breaks
5. **Commit** with clear messages
6. **Push** to your fork
7. Create a **Pull Request**

## 🐛 Reporting Issues

Include:
- Python version
- Operating system
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs

## 📝 Commit Messages

Use conventional commits:
- `feat: add new feature`
- `fix: resolve bug`
- `test: add tests`
- `docs: update documentation`
- `refactor: improve code structure`

## 📧 Contact

For questions, reach out via GitHub Issues.

---

**Happy Coding! 🚀**
