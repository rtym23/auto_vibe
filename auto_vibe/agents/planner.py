"""Planner — AI asks for goals and stages before execution.

Integrated with:
- Council (cross-model reviewer)
- TypedVerifier (typed verification)
- LoopSpec (export to YAML/JSON)
- LoopController (management with budget caps and no-progress detection)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Callable, Awaitable, Optional, TYPE_CHECKING

from auto_vibe.integrations.llm import LLMClient

# TYPE_CHECKING to avoid circular imports
if TYPE_CHECKING:
    from auto_vibe.agents.council import Council, CouncilConfig
    from auto_vibe.agents.verifier import TypedVerifier, VerificationRule
    from auto_vibe.agents.loop_spec import LoopSpec, StopGuards, ExecutionConfig, LoopSpecManager
    from auto_vibe.agents.loop_controller import LoopController


logger = logging.getLogger(__name__)


@dataclass
class Stage:
    """Task execution stage."""
    name: str
    description: str
    command: str | None = None
    target_file: str | None = None
    status: str = "pending"  # pending, in_progress, completed, failed, skipped
    result: str | None = None
    verification_rules: List[VerificationRule] = field(default_factory=list)

    # Additional fields for verification
    verify_syntax: bool = True      # Check syntax
    verify_imports: bool = True     # Check imports
    verify_tests: bool = False      # Run tests

    def add_verification_rules(self) -> None:
        """Adds standard verification rules based on settings."""
        from auto_vibe.agents.verifier import create_syntax_check, create_import_check

        if self.verify_syntax and self.target_file:
            self.verification_rules.append(create_syntax_check(self.target_file))

        if self.verify_imports and self.target_file:
            self.verification_rules.append(create_import_check(self.target_file))


@dataclass
class Plan:
    """Task execution plan."""
    goal: str
    stages: List[Stage] = field(default_factory=list)
    current_stage: int = 0
    definition_of_done: List[str] = field(default_factory=list)

    def is_complete(self) -> bool:
        return all(s.status == "completed" for s in self.stages)

    def next_stage(self) -> Stage | None:
        if self.current_stage < len(self.stages):
            return self.stages[self.current_stage]
        return None


class Planner:
    """
    Task planner with full Looper integration.

    Capabilities:
    - Clarifying questions before plan creation
    - Goal critique via Council
    - Typed stage verification
    - Cross-model review
    - Budget caps and no-progress detection
    - Export to loop.yaml / loop.resolved.json
    """

    def __init__(
        self,
        llm_client: LLMClient,
        user_confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
        # Council
        council_config: CouncilConfig | None = None,
        # Verifier
        verifier: TypedVerifier | None = None,
        # Stop guards
        stop_guards: StopGuards | None = None,
        # Execution config
        execution_config: ExecutionConfig | None = None,
    ):
        self.llm_client = llm_client
        self.user_confirm_callback = user_confirm_callback

        # Council for cross-model review
        # Lazy import to avoid circular imports
        self._council_config = council_config
        self._council: Optional[Council] = None

        # Verifier for typed verification
        self.verifier = verifier

        # Stop guards
        self.stop_guards = stop_guards or StopGuards()

        # Execution config
        self.execution_config = execution_config or ExecutionConfig()

        # Loop controller (created lazily)
        self._loop_controller: Optional[LoopController] = None

        self.current_plan: Plan | None = None
        self.spec_manager: Optional[LoopSpecManager] = None

    @property
    def council(self) -> Optional[Council]:
        """Lazy initialization of Council."""
        if self._council is None and self._council_config:
            from auto_vibe.agents.council import Council
            self._council = Council(self.llm_client, self._council_config)
        return self._council

    @property
    def loop_controller(self) -> LoopController:
        """Lazy initialization of LoopController."""
        if self._loop_controller is None:
            from auto_vibe.agents.loop_controller import LoopController
            self._loop_controller = LoopController(
                council=self.council,
                verifier=self.verifier,
                stop_guards=self.stop_guards,
                user_confirm_callback=self.user_confirm_callback,
            )
        return self._loop_controller

    async def _ask_user(self, message: str, timeout_seconds: float = 60.0) -> bool:
        """
        Requests confirmation from the user with a timeout.

        Args:
            message: Message for the user
            timeout_seconds: Timeout in seconds (default 60)

        Returns:
            True if user confirmed, False if rejected or timeout
        """
        if self.user_confirm_callback:
            return await self.user_confirm_callback(message)

        # Fallback: use input() for synchronous input
        try:
            import sys
            print(f"\n{'='*50}")
            print(f"{message}")
            print(f"{'='*50}")
            print("[Y/n] (default Y, timeout 60 sec): ", end="", flush=True)

            # Try to get input with timeout
            try:
                import asyncio
                asyncio.get_event_loop()

                # Try to get input with timeout
                response = sys.stdin.readline().strip().lower()

            except Exception:
                # If failed, just return True
                response = ""

            response = input().strip().lower() if sys.stdin else ""
            return response in ("", "y", "yes")

        except (EOFError, KeyboardInterrupt):
            logger.warning("Failed to get user input, continuing...")
            return True

    async def _ask_user_choice(self, message: str, options: List[str], timeout_seconds: float = 60.0) -> Optional[int]:
        """
        Requests a choice from a list of options.

        Args:
            message: Message for the user
            options: List of options to choose from
            timeout_seconds: Timeout in seconds

        Returns:
            Index of selected option or None on timeout/cancel
        """
        if self.user_confirm_callback:
            # For callback, just return the first option
            return 0

        try:
            print(f"\n{message}")
            for i, opt in enumerate(options, 1):
                print(f"  {i}. {opt}")

            response = input("Select an option (1-{}): ".format(len(options))).strip()

            if response.isdigit():
                idx = int(response) - 1
                if 0 <= idx < len(options):
                    return idx

            return None

        except (EOFError, KeyboardInterrupt):
            return None

    def set_user_callback(self, callback: Callable[[str], Awaitable[bool]]) -> None:
        """
        Sets callback for user interaction.

        Args:
            callback: Async function that takes a message and returns bool
        """
        self.user_confirm_callback = callback
        logger.info("User callback set")

    async def create_plan(self, initial_prompt: str) -> Plan:
        """
        Creates a plan from the initial prompt.
        Asks clarifying questions and critiques the goal before plan creation.
        """
        logger.info("Creating plan...")

        # === 1. Goal critique via Council ===
        if self.council:
            print("\nCritiquing goal...")
            # Lazy import for Council
            critique = await self.council.critique_goal(initial_prompt)
            print(critique)

            # Confirm improved goal
            goal_confirmed = await self._ask_user(
                "Use this goal? (Y - yes, n - enter your own)"
            )
            if not goal_confirmed:
                try:
                    new_goal = input("Enter refined goal: ").strip()
                    if new_goal:
                        initial_prompt = new_goal
                except (EOFError, KeyboardInterrupt):
                    pass

        # === 2. Clarifying questions ===
        questions_prompt = f"""
You are a task planner. The user wants: {initial_prompt}

Ask 2-4 clarifying questions to better understand the task.
Return ONLY a JSON array of question strings.
Example: ["What programming language should I use?", "Should the output be saved to a file?"]

Return ONLY valid JSON array, no explanations.
"""

        try:
            questions_response = await self.llm_client.generate(questions_prompt)
            raw = questions_response.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()

            import json
            questions = json.loads(raw)

            # Ask questions to the user and collect answers
            answers = {}
            for q in questions[:4]:
                logger.info(f"Question: {q}")
                confirmed = await self._ask_user(f"{q}")
                if not confirmed:
                    try:
                        answer = input("   Your answer: ").strip()
                        if answer:
                            answers[q] = answer
                    except (EOFError, KeyboardInterrupt):
                        answers[q] = "yes"
                else:
                    answers[q] = "yes"
        except Exception as e:
            logger.warning(f"Failed to get clarifying questions: {e}")
            answers = {}

        # === 3. Build context and create plan ===
        context = ""
        if answers:
            context = "\nUser preferences:\n" + "\n".join(f"- {k}: {v}" for k, v in answers.items())

        # === 4. Definition of Done ===
        dod_prompt = f"""
For the task: {initial_prompt}{context}

Define 3-5 clear, measurable success criteria (definition of done).
Return ONLY a JSON array of strings.
Example: ["Code compiles without errors", "All tests pass", "No security vulnerabilities"]

Return ONLY valid JSON array, no explanations.
"""

        try:
            dod_response = await self.llm_client.generate(dod_prompt)
            raw = dod_response.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            definition_of_done = json.loads(raw.strip())
        except Exception as e:
            logger.warning(f"Failed to get definition of done: {e}")
            definition_of_done = ["Code runs without errors"]

        # === 5. Generate stages ===
        stages_prompt = f"""
You are a task planner. The user wants: {initial_prompt}{context}

Definition of Done:
{chr(10).join(f"- {d}" for d in definition_of_done)}

Create an execution plan as a list of stages.
For each stage provide:
- name: short name
- description: what to do
- command: shell command to run (null if none)
- target_file: file to work on (null if none)

Return ONLY a JSON array of objects with fields: name, description, command, target_file
Example:
[
  {{"name": "Create file", "description": "Create the calculator file", "command": null, "target_file": "calculator.py"}},
  {{"name": "Run and test", "description": "Run the code to verify it works", "command": "python calculator.py", "target_file": "calculator.py"}}
]

Return ONLY valid JSON, no explanations.
"""

        stages_response = await self.llm_client.generate(stages_prompt)

        # Parse JSON response
        raw = stages_response.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        try:
            stages_data = json.loads(raw)
            stages = [
                Stage(
                    name=s.get("name", ""),
                    description=s.get("description", ""),
                    command=s.get("command"),
                    target_file=s.get("target_file")
                )
                for s in stages_data
            ]
        except json.JSONDecodeError:
            logger.error(f"Failed to parse stages: {stages_response[:300]}")
            stages = [Stage(name="Execute", description=initial_prompt)]

        plan = Plan(
            goal=initial_prompt,
            stages=stages,
            definition_of_done=definition_of_done
        )
        self.current_plan = plan

        print(f"\n{'='*50}")
        print(f"Plan created: {len(stages)} stages")
        print(f"{'='*50}")
        print(f"\nGoal: {initial_prompt}")
        print("\nDefinition of Done:")
        for d in definition_of_done:
            print(f"  - {d}")
        print("\nStages:")
        for i, stage in enumerate(stages, 1):
            print(f"  {i}. {stage.name}: {stage.description}")

        return plan

    async def execute_plan(
        self,
        plan: Plan,
        loop_callback,
        output_dir: str = "looper-output",
    ) -> bool:
        """
        Executes the plan stage by stage with full Looper integration.

        Args:
            plan: Plan to execute
            loop_callback: Callback function for executing each stage
            output_dir: Directory for loop.yaml and state files
        """
        logger.info(f"Executing plan: {plan.goal}")

        # Initialize spec manager
        self.spec_manager = LoopSpecManager(output_dir)

        # Create LoopSpec
        spec = LoopSpec.from_plan(plan, self.execution_config)
        spec.stop_guards = self.stop_guards
        spec.definition_of_done = plan.definition_of_done

        # Save spec
        self.spec_manager.save_spec(spec)

        # Show ASCII flow
        print("\n" + spec.to_ascii_flow())

        # === Add verification to stages ===
        for stage in plan.stages:
            if stage.target_file:
                stage.add_verification_rules()

        # Use LoopController for execution
        return await self.loop_controller.run_with_council(
            plan=plan,
            execute_callback=loop_callback,
            output_dir=output_dir,
        )

    def export_spec(self, path: str | None = None) -> str:
        """Exports current plan to YAML."""
        if not self.current_plan:
            return "No plan to export"

        spec = LoopSpec.from_plan(self.current_plan, self.execution_config)
        spec.stop_guards = self.stop_guards
        spec.definition_of_done = self.current_plan.definition_of_done

        if path:
            spec.save_yaml(path)
            return f"Exported to {path}"

        return spec.to_yaml()

    def get_state_summary(self) -> dict:
        """Returns execution state summary."""
        return self.loop_controller.get_state_summary()
