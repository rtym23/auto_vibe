"""Worker agent for executing tasks."""

from typing import Any, Optional
from auto_vibe.integrations.llm import LLMClient


class AgentWorker:
    """Worker agent that executes tasks using LLM."""

    def __init__(self, client: LLMClient):
        self.client = client

    async def execute(self, task: str, context: Optional[dict[str, Any]] = None) -> str:
        """Execute a task with optional context."""
        prompt = f"Execute the task: {task}"
        if context:
            prompt += f"\nContext: {context}"

        response = await self.client.generate(prompt)
        return response.content

    async def analyze(self, data: str) -> dict[str, Any]:
        """Analyze data and return structured result."""
        prompt = f"Analyze and return a structured result: {data}"
        response = await self.client.generate(prompt)
        return {"result": response.content, "status": "success"}
