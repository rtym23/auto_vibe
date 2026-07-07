"""
Context Manager - context management with summarization and persistent memory.

Features:
- Accurate token counting via tiktoken
- Summarization of old context
- Persistent memory between sessions
"""

import json
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass, asdict

try:
    import tiktoken
except ImportError:
    tiktoken = None


@dataclass
class ContextMessage:
    """Message in context."""
    role: str  # "user", "assistant", "system"
    content: str
    tokens: int = 0


@dataclass
class ContextState:
    """Context state for checkpoint."""
    messages: List[Dict[str, str]]
    summary: str
    total_tokens: int


class ContextManager:
    """
    Context manager with support for:
    - Accurate token counting (tiktoken)
    - Summarization of old messages
    - Persistent memory between sessions
    """

    def __init__(
        self,
        model_name: str = "cl100k_base",  # tiktoken encoding
        max_tokens: int = 60000,
        summary_threshold: int = 40000,  # Start summarization at 40k tokens
        checkpoint_path: str = "~/.auto_vibe/context_checkpoint.json"
    ):
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
        self.checkpoint_path = Path(checkpoint_path).expanduser()
        
        # Initialize tiktoken
        if tiktoken:
            try:
                self.encoding = tiktoken.get_encoding(model_name)
            except Exception:
                self.encoding = tiktoken.get_encoding("cl100k_base")
        else:
            self.encoding = None
        
        # Current context
        self.messages: List[ContextMessage] = []
        self.summary: str = ""
        self.total_tokens: int = 0

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if self.encoding:
            return len(self.encoding.encode(text))
        # Fallback: rough estimate
        return len(text) // 4

    def add_message(self, role: str, content: str) -> ContextMessage:
        """Add message to context."""
        tokens = self.count_tokens(content)
        msg = ContextMessage(role=role, content=content, tokens=tokens)
        self.messages.append(msg)
        self.total_tokens += tokens
        return msg

    def should_summarize(self) -> bool:
        """Check if context needs summarization."""
        return self.total_tokens > self.summary_threshold

    def get_context_for_prompt(self) -> str:
        """Get context for prompt generation."""
        parts = []
        
        if self.summary:
            parts.append(f"[Previous context (summary): {self.summary}]")
        
        # Add last messages (no more than 20k tokens)
        recent_tokens = 0
        recent_messages = []
        
        for msg in reversed(self.messages):
            if recent_tokens + msg.tokens > 20000:
                break
            recent_messages.insert(0, msg)
            recent_tokens += msg.tokens
        
        for msg in recent_messages:
            parts.append(f"{msg.role}: {msg.content}")
        
        return "\n\n".join(parts)

    def summarize_old_messages(self, llm_client, max_messages: int = 10) -> str:
        """
        Summarize old messages via LLM.
        
        Args:
            llm_client: LLM client for summary generation
            max_messages: How many recent messages to leave without summarization
        """
        if len(self.messages) <= max_messages:
            return ""
        
        # Messages to summarize (all except last max_messages)
        to_summarize = self.messages[:-max_messages]
        
        if not to_summarize:
            return ""
        
        summary_text = "\n".join(
            f"{m.role}: {m.content[:200]}..." if len(m.content) > 200 else f"{m.role}: {m.content}"
            for m in to_summarize
        )
        
        # Prompt for summarization
        summarize_prompt = f"""Summarize the following conversation briefly (2-3 sentences), 
keeping key information:

{summary_text}

Brief summary:"""
        
        try:
            # Use LLM for summarization
            response = llm_client.generate(summarize_prompt)
            self.summary = response.content if hasattr(response, 'content') else str(response)
            
            # Keep only last messages
            self.messages = self.messages[-max_messages:]
            
            # Recalculate tokens
            self.total_tokens = sum(m.tokens for m in self.messages)
            self.total_tokens += self.count_tokens(self.summary)
            
            return self.summary
        except Exception as e:
            print(f"Summarization failed: {e}")
            return ""

    def save_checkpoint(self) -> None:
        """Save context state to file."""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        
        state = ContextState(
            messages=[{"role": m.role, "content": m.content} for m in self.messages],
            summary=self.summary,
            total_tokens=self.total_tokens
        )
        
        with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
            json.dump(asdict(state), f, ensure_ascii=False, indent=2)

    def load_checkpoint(self) -> bool:
        """Load context state from file."""
        if not self.checkpoint_path.exists():
            return False
        
        try:
            with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            state = ContextState(**data)
            
            self.messages = [
                ContextMessage(role=m["role"], content=m["content"], tokens=self.count_tokens(m["content"]))
                for m in state.messages
            ]
            self.summary = state.summary
            self.total_tokens = state.total_tokens
            
            return True
        except Exception as e:
            print(f"Failed to load checkpoint: {e}")
            return False

    def clear(self) -> None:
        """Clear context."""
        self.messages.clear()
        self.summary = ""
        self.total_tokens = 0

    def get_stats(self) -> Dict[str, Any]:
        """Get context statistics."""
        return {
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "message_count": len(self.messages),
            "summary_length": len(self.summary),
            "usage_percent": round(self.total_tokens / self.max_tokens * 100, 1)
        }
