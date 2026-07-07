"""Orchestrator — coordinates three agents: Architect -> Executor -> Verifier.

Implements a hierarchy:
- Architect: analyzes and plans
- Executor: writes/fixes code
- Verifier: tests and checks

Contains HITL hooks for user confirmation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Optional, Callable, Awaitable, Any, TYPE_CHECKING
from enum import Enum

from auto_vibe.agents.architect import Architect, ExecutionPlan, ArchitectConfig
from auto_vibe.agents.loop_spec import StopGuards, LoopSpecManager
from auto_vibe.cost.calculator import CostCalculator

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AgentRole(Enum):
    """Agent role in the hierarchy."""
    ARCHITECT = "architect"    # Planning
    EXECUTOR = "executor"      # Execution
    VERIFIER = "verifier"      # Verification


class ExecutionPhase(Enum):
    """Execution phase."""
    PLANNING = "planning"      # Architect working
    EXECUTING = "executing"    # Executor working
    VERIFYING = "verifying"    # Verifier working
    DONE = "done"              # Completed


@dataclass
class AgentState:
    """State of a specific agent."""
    role: AgentRole
    current_task: str = ""
    iterations: int = 0
    last_output: str = ""
    errors: List[str] = field(default_factory=list)

    # For similarity detection
    last_code_snapshot: str = ""
    last_error_snapshot: str = ""


@dataclass
class OrchestratorState:
    """State of the entire orchestrator."""
    phase: ExecutionPhase = ExecutionPhase.PLANNING
    current_plan: Optional[ExecutionPlan] = None

    # Agent states
    architect_state: AgentState = field(default_factory=lambda: AgentState(AgentRole.ARCHITECT))
    executor_state: AgentState = field(default_factory=lambda: AgentState(AgentRole.EXECUTOR))
    verifier_state: AgentState = field(default_factory=lambda: AgentState(AgentRole.VERIFIER))

    # Global metrics
    total_iterations: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    # History for similarity detection
    code_history: List[str] = field(default_factory=list)
    error_history: List[str] = field(default_factory=list)

    # Stop conditions
    is_stuck: bool = False
    stuck_reason: str = ""


@dataclass
class HITLConfig:
    """Human-in-the-Loop configuration."""
    # When to ask
    ask_before_start: bool = True
    ask_before_destructive: bool = True
    ask_every_n_iterations: int = 5

    # What to ask
    confirm_destructive_actions: bool = True
    confirm_new_branches: bool = True
    confirm_commits: bool = False

    # Triggers
    destructive_patterns: List[str] = field(default_factory=lambda: [
        "delete", "remove", "drop", "rm ", "unlink"
    ])


class Orchestrator:
    """
    Orchestrator — coordinates three agents:

    1. Architect (Plan)   — Analyzes project, creates plan
    2. Executor (Write)   — Writes/fixes code
    3. Verifier (Check)   — Tests and checks

    Features:
    - HITL hooks for confirmation
    - Similarity-based loop termination
    - Budget caps and timeout
    - Cost tracking
    """

    def __init__(
        self,
        # Agents
        architect: Optional[Architect] = None,
        executor: Optional[Any] = None,  # Will be the code execution logic
        verifier: Optional[Any] = None,  # Will be test runner

        # Configuration
        stop_guards: Optional[StopGuards] = None,
        hitl_config: Optional[HITLConfig] = None,
        cost_calculator: Optional[CostCalculator] = None,

        # Callbacks
        user_confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
        on_thought_update: Callable[[AgentRole, str], Awaitable[None]] | None = None,
    ):
        # Agents (lazy initialization)
        self._architect = architect
        self._executor = executor
        self._verifier = verifier

        # Configuration
        self.stop_guards = stop_guards or StopGuards()
        self.hitl_config = hitl_config or HITLConfig()
        self.cost_calculator = cost_calculator

        # Callbacks
        self.user_confirm_callback = user_confirm_callback
        self.on_thought_update = on_thought_update

        # State
        self.state = OrchestratorState()
        self.spec_manager: Optional[LoopSpecManager] = None

    # === Properties for lazy initialization ===

    @property
    def architect(self) -> Architect:
        if self._architect is None:
            # This will be set by the caller
            raise RuntimeError("Architect not initialized. Set it via constructor.")
        return self._architect

    @architect.setter
    def architect(self, value):
        self._architect = value

    # === HITL Methods ===

    async def _ask_user(self, message: str) -> bool:
        """Requests confirmation from the user."""
        if self.user_confirm_callback:
            return await self.user_confirm_callback(message)

        try:
            response = input(f"\n{message}\n[Y/n]: ").strip().lower()
            return response in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return True

    async def _emit_thought(self, role: AgentRole, thought: str) -> None:
        """Sends agent thoughts for display."""
        if self.on_thought_update:
            await self.on_thought_update(role, thought)
        logger.info(f"[{role.value.upper()}] {thought}")

    async def request_start_approval(self, plan: ExecutionPlan) -> bool:
        """Requests confirmation to start work."""
        if not self.hitl_config.ask_before_start:
            return True

        message = f"""
{'='*60}
ARCHITECT PLAN
{'='*60}
Task: {plan.goal}
Complexity: {plan.complexity.value.upper()}
Stages: {', '.join(plan.stages)}

Risk Assessment: {plan.risk_assessment}
Estimated Stages: {plan.estimated_stages}
Rollback Strategy: {plan.rollback_strategy}

{'='*60}
Start execution?
"""
        return await self._ask_user(message)

    async def request_destructive_approval(self, action: str) -> bool:
        """Requests confirmation for a destructive action."""
        if not self.hitl_config.ask_before_destructive:
            return True

        message = f"""
DESTRUCTIVE ACTION DETECTED

{action}

This action may be irreversible. Continue?
"""
        return await self._ask_user(message)

    def is_destructive(self, action: str) -> bool:
        """Checks if an action is destructive."""
        action_lower = action.lower()
        return any(pattern in action_lower for pattern in self.hitl_config.destructive_patterns)

    # === Similarity Detection ===

    def calculate_similarity(self, text1: str, text2: str) -> float:
        """
        Calculates semantic similarity between two texts.

        Returns:
            0.0 - completely different
            1.0 - identical
        """
        if not text1 or not text2:
            return 0.0

        # Simple word-based comparison
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def check_stuck(self) -> tuple[bool, str]:
        """
        Checks if the loop is stuck in infinite repetition.

        Returns:
            (is_stuck, reason)
        """
        if len(self.state.code_history) < 3:
            return False, ""

        # Check similarity of recent code attempts
        recent_codes = self.state.code_history[-3:]
        if len(recent_codes) >= 2:
            similarity = self.calculate_similarity(
                recent_codes[-1],
                recent_codes[-2]
            )
            if similarity > 0.85:
                return True, f"Code similarity too high: {similarity:.2%}"

        # Check similarity of recent errors
        if len(self.state.error_history) >= 2:
            recent_errors = self.state.error_history[-3:]
            similarity = self.calculate_similarity(
                recent_errors[-1],
                recent_errors[-2]
            )
            if similarity > 0.8:
                return True, f"Error similarity too high: {similarity:.2%}"

        return False, ""

    def record_attempt(self, code: str, error: str) -> None:
        """Records an attempt for similarity analysis."""
        if code:
            self.state.code_history.append(code[:1000])  # Limit size
            # Keep only last 10
            if len(self.state.code_history) > 10:
                self.state.code_history = self.state.code_history[-10:]

        if error:
            self.state.error_history.append(error[:500])
            if len(self.state.error_history) > 10:
                self.state.error_history = self.state.error_history[-10:]

    # === Main Execution Loop ===

    async def run(
        self,
        task: str,
        execute_callback: Callable[[str, Any], Awaitable[tuple[bool, str]]],
        output_dir: str = "looper-output",
    ) -> bool:
        """
        Main loop: Architect -> Executor -> Verifier

        Args:
            task: Task description
            execute_callback: Function for code execution (returns success, output)
            output_dir: Output directory

        Returns:
            True if task completed successfully
        """
        logger.info(f"Starting orchestrator for task: {task}")

        # Initialize
        self.state.start_time = time.time()
        self.spec_manager = LoopSpecManager(output_dir)

        # === PHASE 1: ARCHITECT ===
        self.state.phase = ExecutionPhase.PLANNING
        await self._emit_thought(AgentRole.ARCHITECT, "Analyzing task and creating plan...")

        plan = await self.architect.analyze_and_plan(task)
        self.state.current_plan = plan
        self.state.architect_state.current_task = task
        self.state.architect_state.last_output = f"Created plan with {len(plan.stages)} stages"

        # Log plan
        self.spec_manager.append_log(f"## Architect Plan\n- Goal: {plan.goal}\n- Complexity: {plan.complexity.value}\n- Stages: {plan.stages}")

        # HITL: Request start approval
        if not await self.request_start_approval(plan):
            logger.info("User cancelled execution")
            return False

        # === PHASE 2-3: EXECUTOR -> VERIFIER Loop ===
        success = False
        max_attempts = self.stop_guards.max_iterations

        for attempt in range(1, max_attempts + 1):
            self.state.total_iterations = attempt
            self.state.executor_state.iterations = attempt

            # Check stop guards
            if self._should_stop():
                reason = f"Stopped: {self.state.stuck_reason or 'max iterations'}"
                logger.info(reason)
                self.spec_manager.append_log(f"## Stopped\n{reason}")
                break

            # Check if stuck
            is_stuck, reason = self.check_stuck()
            if is_stuck:
                self.state.is_stuck = True
                self.state.stuck_reason = reason
                logger.warning(f"Loop stuck: {reason}")
                self.spec_manager.append_log(f"## Stuck\n{reason}")

                # Ask user what to do
                user_choice = await self._ask_user(
                    f"Loop appears stuck: {reason}\n\n"
                    f"Options:\n"
                    f"1. Continue anyway\n"
                    f"2. Rollback and stop\n"
                    f"3. Reset and try again\n"
                )

                if not user_choice:
                    # User said no to continuing
                    break

            # HITL: Check for destructive actions
            if self.is_destructive(task):
                if not await self.request_destructive_approval(task):
                    logger.info("User cancelled destructive action")
                    break

            # Execute stage
            await self._emit_thought(AgentRole.EXECUTOR, f"Attempt {attempt}/{max_attempts}")

            stage_result, output = await execute_callback(task, {
                "attempt": attempt,
                "plan": plan,
                "history": self.state.code_history,
            })

            # Record for similarity detection
            self.record_attempt(output, "" if stage_result else output)

            # Verify result
            self.state.phase = ExecutionPhase.VERIFYING
            await self._emit_thought(AgentRole.VERIFIER, "Verifying result...")

            verification_passed = await self._verify_result(stage_result, output)

            if verification_passed:
                success = True
                self.state.phase = ExecutionPhase.DONE
                await self._emit_thought(AgentRole.VERIFIER, "Verification passed!")
                self.spec_manager.append_log(f"## Success\nCompleted in {attempt} attempts")
                break

            # Not successful, continue loop
            await self._emit_thought(AgentRole.VERIFIER, "Verification failed, will retry...")
            self.spec_manager.append_log(f"## Attempt {attempt}\nFailed, will retry")

            # HITL: Ask every N iterations
            if self.hitl_config.ask_every_n_iterations > 0:
                if attempt % self.hitl_config.ask_every_n_iterations == 0:
                    continue_loop = await self._ask_user(
                        f"After {attempt} attempts, still not successful. Continue?"
                    )
                    if not continue_loop:
                        break

        # Finalize
        self.state.end_time = time.time()

        return success

    async def _verify_result(self, success: bool, output: str) -> bool:
        """
        Verifies the result via the Verifier agent.

        In a real implementation, this would call test_generator
        and check via TypedVerifier.
        """
        # Basic check: did execution succeed?
        if not success:
            return False

        # TODO: Integrate with TestGenerator for TDD
        # TODO: Integrate with TypedVerifier for programmatic checks

        return True

    def _should_stop(self) -> bool:
        """Checks stop conditions."""
        # Max iterations
        if self.state.total_iterations >= self.stop_guards.max_iterations:
            self.state.stuck_reason = f"Max iterations: {self.state.total_iterations}"
            return True

        # Budget
        if self.stop_guards.budget_cap_usd:
            if self.state.total_cost_usd >= self.stop_guards.budget_cap_usd:
                self.state.stuck_reason = f"Budget cap: ${self.state.total_cost_usd:.2f}"
                return True

        # Timeout
        if self.stop_guards.timeout_seconds and self.state.start_time > 0:
            elapsed = time.time() - self.state.start_time
            if elapsed >= self.stop_guards.timeout_seconds:
                self.state.stuck_reason = f"Timeout: {elapsed:.0f}s"
                return True

        return False

    def get_state_summary(self) -> dict:
        """Returns state summary."""
        return {
            "phase": self.state.phase.value,
            "total_iterations": self.state.total_iterations,
            "is_stuck": self.state.is_stuck,
            "stuck_reason": self.state.stuck_reason,
            "total_cost_usd": self.state.total_cost_usd,
            "elapsed_seconds": (
                (self.state.end_time or time.time()) - self.state.start_time
                if self.state.start_time else 0
            ),
            "architect_thought": self.state.architect_state.last_output,
            "executor_iterations": self.state.executor_state.iterations,
        }


# === Factory function for easy setup ===

def create_orchestrator(
    llm_client,
    config: Optional[dict] = None,
    user_confirm_callback: Optional[Callable] = None,
) -> Orchestrator:
    """
    Creates a configured Orchestrator.

    Args:
        llm_client: LLM client
        config: Configuration (optional)
        user_confirm_callback: Confirmation callback

    Returns:
        Configured Orchestrator
    """
    config = config or {}

    # Create Architect
    architect_config = ArchitectConfig(
        auto_detect_complexity=config.get("auto_detect_complexity", True),
        always_ask_for_complex=config.get("always_ask_for_complex", True),
    )
    architect = Architect(
        llm_client=llm_client,
        config=architect_config,
        user_confirm_callback=user_confirm_callback,
    )

    # Create HITL config
    hitl_config = HITLConfig(
        ask_before_start=config.get("ask_before_start", True),
        ask_before_destructive=config.get("ask_before_destructive", True),
        ask_every_n_iterations=config.get("ask_every_n_iterations", 5),
    )

    # Create stop guards
    stop_guards = StopGuards(
        max_iterations=config.get("max_iterations", 10),
        max_revisions=config.get("max_revisions", 3),
        max_no_progress=config.get("max_no_progress", 3),
        budget_cap_usd=config.get("budget_cap_usd"),
        timeout_seconds=config.get("timeout_seconds"),
    )

    return Orchestrator(
        architect=architect,
        stop_guards=stop_guards,
        hitl_config=hitl_config,
        user_confirm_callback=user_confirm_callback,
    )
