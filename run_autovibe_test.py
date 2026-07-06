import asyncio
import sys
import os
from pathlib import Path

# Add current directory to sys.path to allow importing auto_vibe
sys.path.append(os.getcwd())

from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import BaseLLMClient, LLMResponse
from auto_vibe.core.loop import AutoVibeLoop

# Mock LLM Client to avoid needing a real LLM
class MockLLMClient(BaseLLMClient):
    def __init__(self, config):
        super().__init__(config)

    async def generate(self, prompt: str, system_prompt: str | None = None) -> LLMResponse:
        print(f"[MockLLM] Prompt: {prompt[:50]}...")
        
        # If the prompt is about fixing, return the fixed code
        if "fix" in prompt.lower() or "code" in prompt.lower():
            fixed_code = """def super_power(a, b):
    return a ** b

def quantum_sum(numbers):
    res = 0
    for n in numbers:
        res += n
    return res

def factorial_fancy(n):
    if n == 0: return 1
    return n * factorial_fancy(n-1)

print(f"Super power of 2 and 3: {super_power(2, 3)}")
print(f"Quantum sum of [1, 2, 3]: {quantum_sum([1, 2, 3])}")
print(f"Factorial of 5: {factorial_fancy(5)}")
"""
            return LLMResponse(
                content=fixed_code,
                usage={"prompt_tokens": 10, "completion_tokens": 10},
                model="mock-model"
            )
        
        return LLMResponse(
            content="I am a mock LLM.",
            usage={"prompt_tokens": 10, "completion_tokens": 10},
            model="mock-model"
        )

async def main():
    settings = Settings()
    # We'll use the mock client
    llm_client = MockLLMClient(settings.llm)
    
    loop = AutoVibeLoop(settings, llm_client)
    
    target_file = r"c:\Users\Userrr\Downloads\autovibe_test\calculator.py"
    task = "Fix the syntax error and the logic error in the calculator script."
    
    print("--- Starting AutoVibe Loop Test ---")
    success = await loop.run(task=task, target_file=target_file)
    
    if success:
        print("\n✅ TEST PASSED: The loop fixed the file!")
        print("--- Final File Content ---")
        with open(target_file, 'r', encoding='utf-8') as f:
            print(f.read())
    else:
        print("\n❌ TEST FAILED: The loop did not fix the file.")

if __name__ == "__main__":
    asyncio.run(main())
