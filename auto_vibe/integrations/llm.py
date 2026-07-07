"""LLM module with error handling and retry logic."""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol

import httpx
from pydantic import BaseModel

from auto_vibe.config.settings import LLMConfig


logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Base LLM error class."""
    pass


class LLMConnectionError(LLMError):
    """LLM connection error."""
    pass


class LLMTimeoutError(LLMError):
    """Request timeout error."""
    pass


class LLMResponseError(LLMError):
    """LLM response error."""
    pass


class LLMResponse(BaseModel):
    content: str
    usage: dict[str, int]
    model: str


class LLMClient(Protocol):
    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        ...


class MockLLMClient:
    """Mock LLM client for demo and testing."""

    def __init__(self, config: LLMConfig | None = None):
        self.config = config
        self._response_index = 0

    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        import time
        await asyncio.sleep(0.5)

        if "fix" in prompt.lower() or "error" in prompt.lower():
            content = self._generate_fix(prompt)
        elif "test" in prompt.lower():
            content = self._generate_test(prompt)
        elif "plan" in prompt.lower() or "stage" in prompt.lower():
            content = self._generate_plan(prompt)
        else:
            content = self._generate_code(prompt)

        return LLMResponse(
            content=content,
            usage={"prompt_tokens": len(prompt) // 4, "completion_tokens": len(content) // 4, "total_tokens": (len(prompt) + len(content)) // 4},
            model="mock-model",
        )

    def _generate_fix(self, prompt: str) -> str:
        if "undefined_variable" in prompt or "name 'undefined" in prompt:
            return '''# Fixed: defined the variable before use
result = 42
print(result)
'''
        if "syntax" in prompt.lower():
            return '''# Fixed: syntax error corrected
print("Hello, World!")
'''
        return '''# Fixed: applied correction
value = "fixed"
print(value)
'''

    def _generate_test(self, prompt: str) -> str:
        return '''import pytest

def test_basic():
    assert True

def test_example():
    result = 1 + 1
    assert result == 2

def test_edge_case():
    data = []
    assert len(data) == 0
'''

    def _generate_code(self, prompt: str) -> str:
        if "hello" in prompt.lower():
            return 'print("Hello, World!")'
        if "fibonacci" in prompt.lower():
            return '''def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

for i in range(10):
    print(fibonacci(i))
'''
        if "sort" in prompt.lower():
            return '''def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)

print(quicksort([3, 6, 8, 10, 1, 2, 1]))
'''
        return f'# Generated code for: {prompt[:50]}\\nresult = "demo_output"\\nprint(result)\\n'

    def _generate_plan(self, prompt: str) -> str:
        return '''Plan:
1. Stage: Analyze the task and understand requirements
2. Stage: Generate the implementation code
3. Stage: Run tests and verify correctness
4. Stage: Fix any issues found
5. Stage: Final validation and cleanup
'''





class BaseLLMClient:
    """Base class with common error handling and retry logic."""
    
    def __init__(
        self,
        config: LLMConfig,
        max_retries: int = 3,
        base_delay: float = 1.0,
        timeout: float = None,
    ):
        self.config = config
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout or config.timeout
        self._client: httpx.AsyncClient | None = None
    
    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=httpx.Timeout(self.timeout),
            )
        return self._client
    
    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        last_error: Exception | None = None
        
        for attempt in range(self.max_retries):
            try:
                response = await self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
                
            except httpx.TimeoutException as e:
                last_error = LLMTimeoutError(f"Timeout (attempt {attempt + 1}/{self.max_retries}): {e}")
                logger.warning(f"Timeout: {e}")
                
            except httpx.ConnectError as e:
                last_error = LLMConnectionError(f"Connection error (attempt {attempt + 1}/{self.max_retries}): {e}")
                logger.warning(f"Connection error: {e}")
                
            except httpx.HTTPStatusError as e:
                if 400 <= e.response.status_code < 500:
                    raise LLMResponseError(f"HTTP {e.response.status_code}: {e.response.text[:200]}")
                last_error = LLMResponseError(f"HTTP {e.response.status_code} (attempt {attempt + 1}/{self.max_retries})")
                logger.warning(f"HTTP error: {e.response.status_code}")
                
            except httpx.HTTPError as e:
                last_error = LLMError(f"HTTP error (attempt {attempt + 1}/{self.max_retries}): {e}")
                logger.warning(f"HTTP error: {e}")
            
            if attempt < self.max_retries - 1:
                delay = self.base_delay * (2 ** attempt)
                logger.info(f"Retry in {delay}s...")
                await asyncio.sleep(delay)
        
        raise last_error or LLMError("Unknown error")
    
    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        raise NotImplementedError


class OllamaClient(BaseLLMClient):
    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = await self._request_with_retry("POST", "/api/generate", json=payload)
        data = response.json()

        return LLMResponse(
            content=data["response"],
            usage={
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
            },
            model=self.config.model,
        )


class OpenAIClient(BaseLLMClient):
    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
        }
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        response = await self._request_with_retry(
            "POST",
            "/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        usage = data["usage"]

        return LLMResponse(
            content=message["content"],
            usage={
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
            },
            model=self.config.model,
        )


def create_llm_client(config: LLMConfig) -> LLMClient:
    if config.provider == "mock":
        return MockLLMClient(config)
    elif config.provider == "ollama":
        return OllamaClient(config)
    elif config.provider == "openai":
        return OpenAIClient(config)
    else:
        raise ValueError(f"Unsupported provider: {config.provider}")
