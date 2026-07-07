"""AutoVibeLoop - main autonomous developer loop."""

from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import LLMClient
from auto_vibe.integrations.web_search import DuckDuckGoSearcher
from auto_vibe.integrations.hallucination_guard import HallucinationGuard
from auto_vibe.core.executor import Executor
from auto_vibe.core.analyzer import Analyzer
from auto_vibe.core.fixer import Fixer
from auto_vibe.strategies.expert import ExpertMode
from auto_vibe.memory.vault import MemoryVault
from auto_vibe.cost.calculator import CostCalculator
from auto_vibe.context_manager import ContextManager
from auto_vibe.sandbox import Sandbox
from auto_vibe.agents.council import Council, CouncilConfig, ReviewType
from auto_vibe.git_manager import GitManager
from auto_vibe.agents.verifier import TypedVerifier, create_syntax_check, create_import_check


logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 60000


class AutoVibeLoop:
    """
    Main autonomous developer loop.
    Supports:
    - Real code generation via LLM
    - Token counting and checkpointing
    - MemoryVault integration
    - CostCalculator integration
    """

    def __init__(self, settings: Settings, llm_client: LLMClient, council_config: CouncilConfig | None = None):
        self.settings = settings
        self.llm_client = llm_client
        self.executor = Executor(settings.executor)
        self.analyzer = Analyzer()
        self.fixer = Fixer(llm_client)
        self.expert_mode = ExpertMode(
            strategy=settings.strategy.default, 
            max_iterations=settings.strategy.max_iterations
        )
        self.web_searcher = DuckDuckGoSearcher()
        self.hallucination_guard = HallucinationGuard(threshold=0.7)
        
        self.council = Council(llm_client, council_config) if council_config else None
        self.verifier = TypedVerifier(executor=self.executor, llm_client=llm_client)
        self.git_manager = GitManager()
        
        self.memory = MemoryVault(settings.memory) if settings.memory.enabled else None
        self.cost_calc = CostCalculator(settings.cost)
        self.cost_calc.start_session()
        
        self.max_tokens = getattr(settings, 'max_tokens', DEFAULT_MAX_TOKENS)
        
        self.context_manager = ContextManager(
            max_tokens=self.max_tokens,
            summary_threshold=int(self.max_tokens * 0.7),
            checkpoint_path="~/.auto_vibe/context_checkpoint.json"
        )
        
        self.context_manager.load_checkpoint()
        
        self.sandbox = Sandbox(
            timeout=settings.executor.timeout,
            base_dir=tempfile.gettempdir()
        )
        
        self.iteration_history: List[Dict[str, Any]] = []

    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        if not text:
            return 0
        return len(text) // 3

    def _get_context_from_memory(self) -> str:
        """Get context from memory to improve prompts."""
        if not self.memory:
            return ""
        
        recent = self.memory.get_recent_entries(limit=5)
        if not recent:
            return ""
        
        context_parts = ["\n--- Previous Experience ---"]
        for entry in recent:
            content = entry.get('content', '')[:500]
            metadata = entry.get('metadata', {})
            status = metadata.get('status', 'unknown')
            context_parts.append(f"[{status}] {content}")
        
        return "\n".join(context_parts)

    def _save_to_memory(self, task: str, result: bool, details: str = "") -> None:
        """Save result to memory."""
        if not self.memory:
            return
        
        status = "success" if result else "failed"
        details = details or ""
        content = f"Task: {task}\nResult: {status}\nDetails: {details[:500]}"
        metadata = {
            "status": status,
            "task": task,
            "iteration": len(self.iteration_history)
        }
        self.memory.add_entry(content, metadata)

    def _save_checkpoint(self, iteration: int, task: str, file_content: Optional[str]) -> None:
        """Save checkpoint state."""
        checkpoint = {
            "iteration": iteration,
            "task": task,
            "file_content": file_content,
            "timestamp": time.time(),
            "history": self.iteration_history[-10:]
        }
        
        checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
        logger.info(f"Checkpoint saved at iteration {iteration}")

    def _load_checkpoint(self) -> Optional[Dict[str, Any]]:
        """Load checkpoint state."""
        checkpoint_path = Path("~/.auto_vibe/checkpoint.json").expanduser()
        if not checkpoint_path.exists():
            return None
        
        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            logger.info(f"Checkpoint loaded from iteration {data.get('iteration', 0)}")
            return data
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    async def _generate_code(self, task: str, target_file: Optional[str], context: str = "") -> Optional[str]:
        """Generate code via LLM."""
        memory_context = self._get_context_from_memory()
        
        prompt = f"""You are an experienced Python developer. Write code for the following task:

Task: {task}

"""
        
        if target_file:
            prompt += f"\nTarget file: {target_file}\n"
            path = Path(target_file)
            if path.exists():
                existing = path.read_text(encoding="utf-8")
                prompt += f"\nExisting code (you can extend or fix):\n`python\n{existing[:3000]}\n`\n"
        
        if memory_context:
            prompt += f"\n{memory_context}\n"
        
        if context:
            prompt += f"\nError context: {context}\n"
        
        prompt += """

Reply ONLY with Python code, no explanations. Code must be complete and working.
Start your response with `python and end with `
"""
        
        token_count = self.count_tokens(prompt)
        if token_count > self.max_tokens:
            logger.warning(f"Prompt too long: {token_count} tokens, saving checkpoint...")
            self._save_checkpoint(0, task, None)
            prompt = prompt[:self.max_tokens * 3]

        try:
            response = await self.llm_client.generate(prompt)
            content = response.content
            
            if "`python" in content:
                start = content.find("`python") + len("`python")
                end = content.find("`", start)
                if end > start:
                    code = content[start:end].strip()
                else:
                    code = content[start:].strip()
            else:
                code = content.strip()
            
            usage = response.usage
            self.cost_calc.record_iteration(
                iteration_num=len(self.iteration_history) + 1,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                elapsed_seconds=1.0,
                model_name=response.model
            )
            
            return code
            
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            return None

    def _build_verify_command(self, target_file: str) -> str:
        """Build verification command for target file."""
        safe_path = target_file.replace("\\", "/")
        return (
            f"python -c \""
            f"import importlib.util, sys; "
            f"spec = importlib.util.spec_from_file_location('test_module', r'{safe_path}'); "
            f"mod = importlib.util.module_from_spec(spec); "
            f"spec.loader.exec_module(mod); "
            f"print('RUNTIME OK')\""
        )

    async def run(
        self,
        task: str,
        target_file: str | Path | None = None,
        command: str | None = None,
    ) -> bool:
        """Run the task fixing loop."""
        print(f"Starting task: {task}")
        if target_file:
            print(f"Target file: {target_file}")

        iteration = 0
        success = False
        current_file_content: str | None = None
        target_file_str = str(target_file) if target_file else None

        checkpoint = self._load_checkpoint()
        if checkpoint and checkpoint.get('task') == task:
            iteration = checkpoint.get('iteration', 0)
            current_file_content = checkpoint.get('file_content')
            print(f"Resuming from checkpoint at iteration {iteration}")

        if target_file and not current_file_content:
            path = Path(target_file)
            if path.exists():
                try:
                    current_file_content = path.read_text(encoding="utf-8")
                    print(f"Read {len(current_file_content)} chars from {target_file}")
                except Exception as e:
                    logger.error(f"Failed to read file: {e}")
                    print(f"Failed to read file: {e}")
                    return False
            else:
                print(f"File does not exist, will be created: {target_file}")

        while not success:
            iteration += 1
            print(f"\nIteration {iteration}...")

            start_time = time.time()

            print("Generating code via LLM...")

            if not current_file_content:
                generated_code = await self._generate_code(task, target_file_str)
                if generated_code:
                    if target_file:
                        try:
                            path = Path(target_file)
                            path.parent.mkdir(parents=True, exist_ok=True)
                            path.write_text(generated_code, encoding="utf-8")
                            current_file_content = generated_code
                            print(f"Generated and saved code to {target_file}")
                        except Exception as e:
                            logger.error(f"Failed to write file: {e}")
                            print(f"Failed to write file: {e}")
                    else:
                        current_file_content = generated_code
                else:
                    print("LLM failed to generate code")
                    break
            
            if self.council and current_file_content:
                print("\nCouncil review after generation...")
                review = await self.council.review(
                    content=current_file_content,
                    context=task,
                    review_type=ReviewType.VERDICT,
                )
                print(f"   Score: {review.score:.2f}")
                print(f"   Verdict: {review.verdict}")
                
                if not review.is_pass():
                    print("Council requires revisions:")
                    for suggestion in review.suggestions[:3]:
                        print(f"   - {suggestion}")
                    
                    if review.verdict == "fail":
                        error_msg = f"Council review failed: {review.notes}"
                        if review.suggestions:
                            fix_prompt = f"Fix code based on feedback: {review.notes}\n\nSuggestions: {', '.join(review.suggestions)}\n\nCode:\n{current_file_content}"
                            fix_response = await self.llm_client.generate(fix_prompt)
                            if fix_response and fix_response.content:
                                current_file_content = fix_response.content.strip()
                                if target_file:
                                    Path(target_file).write_text(current_file_content, encoding="utf-8")
                                print("   Applied fixes from Council")

            print("Running code...")

            if command is None:
                if target_file:
                    command = self._build_verify_command(target_file)
                else:
                    command = "python -c 'print(1)'"

            result = await self.executor.run_command(command)

            if result.exit_code == 0 and "RUNTIME OK" in result.stdout:
                print("Success! Code runs without errors.")
                
                if target_file_str:
                    print("\nRunning additional verification...")
                    
                    rules = [
                        create_syntax_check(target_file_str),
                        create_import_check(target_file_str),
                    ]
                    
                    verification_result = await self.verifier.verify(
                        rules=rules,
                        context={"content": current_file_content, "file": target_file_str}
                    )
                    
                    if verification_result.is_pass():
                        print("   All verification rules passed")
                    else:
                        print(f"   Verification warning: {verification_result.message}")
                
                success = True
                self._save_to_memory(task, True, f"Iteration {iteration}")
                break
            else:
                combined_error = f"{result.stderr}\n{result.stdout}" if result.stdout else result.stderr
                print(f"Error detected: {combined_error[:300]}...")
                error_msg = self.analyzer.analyze_error(result)

                self._save_to_memory(task, False, error_msg)

                print(f"Analyzed: {error_msg}")

                print("Searching for solutions...")
                search_results = await self.web_searcher.search(error_msg, num_results=3)
                for r in search_results:
                    print(f"   - {r.title}: {r.snippet}")

                if not self.expert_mode.should_continue(iteration, error_msg):
                    print("Max iterations reached or strategy says stop.")
                    break

                print("Suggesting fix...")
                fix = await self.fixer.suggest_fix(
                    error_msg=error_msg,
                    file_path=target_file_str,
                    file_content=current_file_content,
                )
                print(f"Suggestion: {fix[:200] if fix else 'None'}...")

                if fix:
                    print("Checking for hallucinations...")
                    verification = await self.hallucination_guard.verify(
                        prompt=error_msg,
                        response=fix,
                        context=search_results[0].snippet if search_results else None
                    )
                    print(f"   Verified: {verification.is_verified} (confidence: {verification.confidence:.2f})")
                    if not verification.is_verified and verification.confidence < 0.5:
                        print("Low confidence fix, searching for alternatives...")
                        continue

                if target_file and fix and not fix.startswith("# Error"):
                    try:
                        path = Path(target_file)
                        fixed_content = fix.strip()
                        path.write_text(fixed_content, encoding="utf-8")
                        current_file_content = fixed_content
                        print(f"Applied fix to {target_file}")
                    except Exception as e:
                        logger.error(f"Failed to apply fix: {e}")
                        print(f"Failed to apply fix: {e}")
                        break
                else:
                    print("No valid fix from LLM, stopping.")
                    break

            elapsed = time.time() - start_time
            self.iteration_history.append({
                "iteration": iteration,
                "task": task,
                "success": success,
                "elapsed": elapsed,
                "error": combined_error[:200] if result.exit_code != 0 else None
            })

            if current_file_content:
                self.context_manager.add_message("user", f"Task: {task}, Iteration: {iteration}")
                if success:
                    self.context_manager.add_message("assistant", f"Success: completed in {iteration} iterations")
                else:
                    self.context_manager.add_message("assistant", f"Error: {error_msg}")

            if self.context_manager.should_summarize():
                print(f"Context at {self.context_manager.total_tokens} tokens, summarizing...")
                summary = self.context_manager.summarize_old_messages(self.llm_client)
                if summary:
                    print(f"Context summarized: {summary[:100]}...")

            self.context_manager.save_checkpoint()

            if iteration % 3 == 0:
                self._save_checkpoint(iteration, task, current_file_content)

        if success:
            print("\nTask completed successfully!")
            
            if self.git_manager.is_git_repo():
                diff = self.git_manager.get_diff()
                if diff and diff.files_changed > 0:
                    print("\nGit changes detected:")
                    print(self.git_manager.format_diff_summary(diff))
                    
                    commit_msg = f"AutoVibe: completed task - {task[:50]}"
                    self.git_manager.add_file(".")
                    if self.git_manager.commit(commit_msg):
                        print("Changes auto-committed!")
                        
                        last = self.git_manager.get_last_commit()
                        if last:
                            print(f"   Commit: {last['hash'][:8]} - {last['message']}")
        else:
            print("\nTask failed or stopped.")

        if self.cost_calc.records:
            print("\n" + self.cost_calc.format_summary())

        return success
