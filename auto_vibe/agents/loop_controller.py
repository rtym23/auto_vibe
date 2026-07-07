"""Loop controller — manages loop execution with budget caps and no-progress detection."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import List, Callable, Awaitable, Optional, TYPE_CHECKING
from enum import Enum

from auto_vibe.agents.loop_spec import LoopSpec, StopGuards, LoopSpecManager
from auto_vibe.cost.calculator import CostCalculator

# TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from auto_vibe.agents.council import Council, ReviewType
    from auto_vibe.agents.verifier import TypedVerifier
    from auto_vibe.agents.planner import Plan, Stage


logger = logging.getLogger(__name__)


class LoopStatus(Enum):
    """Loop execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    STOPPED = "stopped"  # Stopped by guard
    CANCELLED = "cancelled"


@dataclass
class LoopState:
    """Loop execution state."""
    status: LoopStatus = LoopStatus.PENDING
    current_stage: int = 0
    completed_stages: List[str] = field(default_factory=list)
    iterations: int = 0
    revisions: int = 0
    no_progress_count: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    # History for no-progress detection
    last_results: List[bool] = field(default_factory=list)

    def should_stop(self, guards: StopGuards) -> tuple[bool, str]:
        """
        Checks stop conditions.

        Returns:
            (should_stop, reason)
        """
        # Max iterations
        if self.iterations >= guards.max_iterations:
            return True, f"Max iterations reached: {self.iterations}/{guards.max_iterations}"

        # Max revisions
        if self.revisions >= guards.max_revisions:
            return True, f"Max revisions reached: {self.revisions}/{guards.max_revisions}"

        # No progress
        if self.no_progress_count >= guards.max_no_progress:
            return True, f"No progress for {self.no_progress_count} attempts"

        # Budget caps
        if guards.budget_cap_usd and self.total_cost_usd >= guards.budget_cap_usd:
            return True, f"Budget cap reached: ${self.total_cost_usd:.2f}/${guards.budget_cap_usd}"

        if guards.budget_cap_tokens and self.total_tokens >= guards.budget_cap_tokens:
            return True, f"Token cap reached: {self.total_tokens}/{guards.budget_cap_tokens}"

        # Timeout
        if guards.timeout_seconds and self.start_time > 0:
            elapsed = time.time() - self.start_time
            if elapsed >= guards.timeout_seconds:
                return True, f"Timeout: {elapsed:.0f}s/{guards.timeout_seconds}s"

        return False, ""

    def record_result(self, success: bool, error_msg: str = "") -> None:
        """
        Records a result for improved no-progress detection.

        Args:
            success: Success or failure
            error_msg: Error message (for similarity analysis)
        """
        self.last_results.append(success)

        # Keep only last N results
        max_history = 5
        if len(self.last_results) > max_history:
            self.last_results = self.last_results[-max_history:]

        # Save error history for analysis
        if error_msg:
            self._error_history.append({
                "success": success,
                "error": error_msg[:200],  # Limit length
                "timestamp": time.time()
            })
            if len(self._error_history) > self._max_error_history:
                self._error_history = self._error_history[-self._max_error_history:]

        # Check for no progress (same result repeatedly)
        if len(self.last_results) >= 3:
            if all(r == self.last_results[0] for r in self.last_results):
                if not success:  # Only count failures as no progress
                    self.no_progress_count += 1
                else:
                    self.no_progress_count = 0
            else:
                self.no_progress_count = 0

    def is_similar_error(self, error_msg: str, threshold: float = 0.7) -> bool:
        """
        Checks if the current error is similar to previous ones.
        Uses simple keyword-based comparison.

        Args:
            error_msg: Error message
            threshold: Similarity threshold (0-1)

        Returns:
            True if error is similar to previous ones
        """
        if not self._error_history:
            return False

        # Extract keywords from the error
        def extract_keywords(msg: str) -> set:
            # Remove file paths and line numbers
            import re
            msg = re.sub(r'/[\w/]+\.py', '', msg)
            msg = re.sub(r'line \d+', '', msg)
            words = set(msg.lower().split())
            # Remove common words
            stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            return words - stop_words

        current_keywords = extract_keywords(error_msg)
        if not current_keywords:
            return False

        # Compare with recent errors
        similar_count = 0
        for entry in self._error_history[-5:]:
            if not entry["success"] and entry.get("error"):
                prev_keywords = extract_keywords(entry["error"])
                if prev_keywords:
                    intersection = len(current_keywords & prev_keywords)
                    union = len(current_keywords | prev_keywords)
                    similarity = intersection / union if union > 0 else 0
                    if similarity >= threshold:
                        similar_count += 1

        return similar_count >= 2


class LoopController:
    """
    Loop controller — manages execution with:
    - Budget caps
    - No-progress detection (improved)
    - Council (cross-model review)
    - Typed verification
    - Stop guards
    """

    def __init__(
        self,
        council: Optional[Council] = None,
        verifier: Optional[TypedVerifier] = None,
        cost_calculator: Optional[CostCalculator] = None,
        stop_guards: Optional[StopGuards] = None,
        user_confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self._council = council  # Lazy initialization
        self._verifier = verifier
        self.cost_calculator = cost_calculator
        self.stop_guards = stop_guards or StopGuards()
        self.user_confirm_callback = user_confirm_callback

        self.state = LoopState()
        self.spec_manager: Optional[LoopSpecManager] = None

        # Error history for improved no-progress detection
        self._error_history: List[dict] = []
        self._max_error_history = 10

    @property
    def council(self):
        """Returns council (may be None)."""
        return self._council

    @council.setter
    def council(self, value):
        """Sets council."""
        self._council = value

    async def _ask_user(self, message: str) -> bool:
        """Requests confirmation from the user."""
        if self.user_confirm_callback:
            return await self.user_confirm_callback(message)

        try:
            response = input(f"\n{message}\n[Y/n]: ").strip().lower()
            return response in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return True

    async def run_with_council(
        self,
        plan: 'Plan',
        execute_callback: Callable[[Stage], Awaitable[bool]],
        output_dir: str = "looper-output",
    ) -> bool:
        """
        Executes the plan with council and verification.

        Args:
            plan: Execution plan
            execute_callback: Stage execution function
            output_dir: Output directory

        Returns:
            True if plan executed successfully
        """

        # Initialize spec manager
        self.spec_manager = LoopSpecManager(output_dir)

        # Create spec
        spec = LoopSpec.from_plan(plan)
        spec.stop_guards = self.stop_guards
        spec.verification = []  # TODO: add verification rules

        # Save spec
        self.spec_manager.save_spec(spec)

        # Start execution
        self.state.status = LoopStatus.RUNNING
        self.state.start_time = time.time()

        logger.info(f"Starting loop: {plan.goal}")

        # Critique goal via council
        if self.council:
            critique = await self.council.critique_goal(plan.goal)
            print(f"\n{critique}")
            self.spec_manager.append_log(f"## Goal Critique\n{critique}")

        # Start confirmation
        confirmed = await self._ask_user(
            f"Start execution of plan with {len(plan.stages)} stages?"
        )
        if not confirmed:
            self.state.status = LoopStatus.CANCELLED
            return False

        # Execute stages
        while True:
            # Check stop guards
            should_stop, reason = self.state.should_stop(self.stop_guards)
            if should_stop:
                logger.info(f"Loop stopped: {reason}")
                self.state.status = LoopStatus.STOPPED
                self.spec_manager.append_log(f"## Stopped\n{reason}")
                return False

            stage = plan.next_stage()
            if stage is None:
                break

            plan.current_stage += 1
            self.state.current_stage = plan.current_stage
            self.state.iterations += 1

            print(f"\n{'='*50}")
            print(f"Stage {plan.current_stage}/{len(plan.stages)}: {stage.name}")
            print(f"{'='*50}")
            print(f"   {stage.description}")

            # Confirmation before stage
            stage_confirmed = await self._ask_user(
                f"Execute stage \"{stage.name}\"?"
            )
            if not stage_confirmed:
                logger.info(f"Stage {stage.name} skipped by user")
                stage.status = "skipped"
                continue

            stage.status = "in_progress"

            # Execute stage
            try:
                result = await execute_callback(stage)
                stage.result = result
                stage.status = "completed" if result else "failed"

                # Record result
                self.state.record_result(result)

                if result:
                    self.state.completed_stages.append(stage.name)
                    self.spec_manager.append_log(
                        f"## Stage {plan.current_stage}: {stage.name}\n**PASSED**"
                    )
                else:
                    self.state.revisions += 1
                    self.spec_manager.append_log(
                        f"## Stage {plan.current_stage}: {stage.name}\n**FAILED**"
                    )

                # Council review after stage
                if self.council and result:
                    print("\nCouncil review...")
                    review = await self.council.review(
                        content=stage.result or "",
                        context=stage.description,
                        review_type=ReviewType.VERDICT,
                    )

                    print(f"   Score: {review.score:.2f}")
                    print(f"   Verdict: {review.verdict}")
                    print(f"   Notes: {review.notes[:200]}...")

                    if not review.is_pass():
                        # Revision needed
                        self.state.revisions += 1

                        if review.suggestions:
                            print("   Suggestions:")
                            for s in review.suggestions:
                                print(f"     - {s}")

                        # Confirmation on revise
                        retry_confirmed = await self._ask_user(
                            "Council requires revision. Continue?"
                        )
                        if not retry_confirmed:
                            self.state.status = LoopStatus.FAILED
                            return False

                # Check stop guards after each stage
                should_stop, reason = self.state.should_stop(self.stop_guards)
                if should_stop:
                    logger.info(f"Loop stopped after stage: {reason}")
                    self.state.status = LoopStatus.STOPPED
                    return False

            except Exception as e:
                logger.error(f"Stage execution error: {e}")
                stage.status = "failed"
                stage.result = str(e)
                self.state.record_result(False)

                error_confirmed = await self._ask_user(
                    f"Error: {e}. Continue?"
                )
                if not error_confirmed:
                    self.state.status = LoopStatus.FAILED
                    return False

        # Finalize
        self.state.end_time = time.time()
        self.state.status = LoopStatus.PASSED if plan.is_complete() else LoopStatus.FAILED

        elapsed = self.state.end_time - self.state.start_time
        print(f"\n{'='*50}")
        print(f"Loop {'PASSED' if self.state.status == LoopStatus.PASSED else 'FAILED'}")
        print(f"{'='*50}")
        print(f"Stages completed: {len(self.state.completed_stages)}/{len(plan.stages)}")
        print(f"Total iterations: {self.state.iterations}")
        print(f"Elapsed time: {elapsed:.1f}s")

        # Final council review
        if self.council and self.state.status == LoopStatus.PASSED:
            print("\nFinal Council review...")
            final_review = await self.council.review(
                content=f"Completed {len(self.state.completed_stages)} stages",
                context=plan.goal,
                review_type=ReviewType.VERDICT,
            )
            print(f"   Final score: {final_review.score:.2f}")
            print(f"   Verdict: {final_review.verdict}")

        return self.state.status == LoopStatus.PASSED

    def get_state_summary(self) -> dict:
        """Returns state summary."""
        return {
            "status": self.state.status.value,
            "current_stage": self.state.current_stage,
            "completed_stages": self.state.completed_stages,
            "iterations": self.state.iterations,
            "revisions": self.state.revisions,
            "no_progress_count": self.state.no_progress_count,
            "total_cost_usd": self.state.total_cost_usd,
            "total_tokens": self.state.total_tokens,
            "elapsed_seconds": (
                (self.state.end_time or time.time()) - self.state.start_time
                if self.state.start_time else 0
            ),
        }
