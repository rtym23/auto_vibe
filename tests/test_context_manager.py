import pytest
from auto_vibe.context_manager import ContextManager, ContextMessage


def test_context_manager_creation():
    """Test ContextManager can be created."""
    cm = ContextManager(max_tokens=1000)
    assert cm is not None
    assert cm.max_tokens == 1000
    assert cm.total_tokens == 0


def test_context_manager_add_message():
    """Test adding messages to context."""
    cm = ContextManager(max_tokens=1000)
    msg = cm.add_message("user", "Hello, world!")
    
    assert msg is not None
    assert msg.role == "user"
    assert msg.content == "Hello, world!"
    assert len(cm.messages) == 1
    assert cm.total_tokens > 0


def test_context_manager_count_tokens():
    """Test token counting."""
    cm = ContextManager(max_tokens=1000)
    tokens = cm.count_tokens("Hello, world!")
    
    assert tokens > 0


def test_context_manager_should_summarize():
    """Test summarization threshold."""
    cm = ContextManager(max_tokens=100, summary_threshold=10)
    
    # Add small messages - should not summarize
    cm.add_message("user", "Short message")
    assert not cm.should_summarize()
    
    # Add more messages to exceed threshold
    cm.add_message("user", "x" * 50)  # ~12 tokens
    cm.add_message("user", "x" * 50)  # ~12 tokens
    assert cm.should_summarize()


def test_context_manager_get_context_for_prompt():
    """Test getting context for prompt."""
    cm = ContextManager(max_tokens=1000)
    cm.add_message("user", "First message")
    cm.add_message("assistant", "Second message")
    cm.summary = "Previous summary"
    
    context = cm.get_context_for_prompt()
    
    assert "Previous summary" in context
    assert "First message" in context
    assert "Second message" in context


def test_context_manager_save_load_checkpoint(tmp_path):
    """Test checkpoint save and load."""
    checkpoint_file = tmp_path / "test_checkpoint.json"
    cm = ContextManager(max_tokens=1000, checkpoint_path=str(checkpoint_file))
    
    cm.add_message("user", "Test message")
    cm.summary = "Test summary"
    cm.save_checkpoint()
    
    # Create new instance and load
    cm2 = ContextManager(max_tokens=1000, checkpoint_path=str(checkpoint_file))
    loaded = cm2.load_checkpoint()
    
    assert loaded
    assert len(cm2.messages) == 1
    assert cm2.messages[0].content == "Test message"
    assert cm2.summary == "Test summary"


def test_context_manager_clear():
    """Test clearing context."""
    cm = ContextManager(max_tokens=1000)
    cm.add_message("user", "Test")
    cm.summary = "Summary"
    cm.total_tokens = 100
    
    cm.clear()
    
    assert len(cm.messages) == 0
    assert cm.summary == ""
    assert cm.total_tokens == 0


def test_context_manager_get_stats():
    """Test getting context stats."""
    cm = ContextManager(max_tokens=1000)
    cm.add_message("user", "Test message")
    
    stats = cm.get_stats()
    
    assert "total_tokens" in stats
    assert "max_tokens" in stats
    assert "message_count" in stats
    assert stats["message_count"] == 1
    assert stats["max_tokens"] == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
