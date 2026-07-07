"""Architect Agent — codebase analysis and high-level planning.

Architect does not write code, but:
- Analyzes project structure via project_analyzer.py
- Creates high-level plans for complex tasks
- Assesses risks and dependencies
- Interacts with HITL hooks for confirmation

Integrated with:
- ProjectAnalyzer (structure analysis)
- Planner (stage creation)
- LoopController (execution management)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable, Awaitable, TYPE_CHECKING
from enum import Enum

from auto_vibe.project_analyzer import ProjectAnalyzer
from auto_vibe.integrations.llm import LLMClient

if TYPE_CHECKING:
    pass  # Future: import Plan, Stage from planner

logger = logging.getLogger(__name__)


class TaskComplexity(Enum):
    """Task complexity levels."""
    SIMPLE = "simple"           # Single file, single change
    MEDIUM = "medium"           # Multiple files, dependencies
    COMPLEX = "complex"         # Many files, architectural changes
    EXPERIMENTAL = "experimental"  # Risky changes


@dataclass
class ExecutionPlan:
    """High-level execution plan from Architect."""
    goal: str
    complexity: TaskComplexity
    stages: List[str] = field(default_factory=list)  # High-level stage names
    risk_assessment: str = ""
    dependencies: List[str] = field(default_factory=list)
    estimated_stages: int = 0
    requires_human_approval: bool = False
    rollback_strategy: str = ""

    # For HITL
    approval_needed_for: List[str] = field(default_factory=list)


@dataclass
class ArchitectConfig:
    """Architect Agent configuration."""
    # Project analysis
    max_files_to_analyze: int = 50
    include_test_files: bool = False

    # Planning
    default_complexity: TaskComplexity = TaskComplexity.MEDIUM
    auto_detect_complexity: bool = True

    # HITL
    always_ask_for_complex: bool = True
    destructive_threshold: TaskComplexity = TaskComplexity.COMPLEX

    # Prompts
    analysis_prompt_template: str = """
You are an Architect Agent analyzing a codebase.

Task: {task}

Project Structure:
{project_summary}

Analyze and provide:
1. Complexity assessment (simple/medium/complex/experimental)
2. List of high-level stages needed
3. Dependencies and risks
4. Whether human approval is needed (for complex/destructive tasks)
5. Rollback strategy if things go wrong

Return ONLY valid JSON:
{{"complexity": "medium", "stages": ["Analyze", "Implement", "Test"], "risk": "...", "needs_approval": true, "rollback": "..."}}
"""


class Architect:
    """
    Architect Agent — analyzes the project and creates high-level plans.

    Does not write code, but determines WHAT needs to be done and HOW to do it safely.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        project_analyzer: Optional[ProjectAnalyzer] = None,
        config: Optional[ArchitectConfig] = None,
        user_confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
    ):
        self.llm_client = llm_client
        self.project_analyzer = project_analyzer or ProjectAnalyzer()
        self.config = config or ArchitectConfig()
        self.user_confirm_callback = user_confirm_callback

        # Analysis cache
        self._project_cache: Optional[Dict[str, Any]] = None

    async def _ask_user(self, message: str) -> bool:
        """Requests confirmation from the user."""
        if self.user_confirm_callback:
            return await self.user_confirm_callback(message)

        try:
            response = input(f"\n{message}\n[Y/n]: ").strip().lower()
            return response in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            return True

    async def analyze_and_plan(self, task: str) -> ExecutionPlan:
        """
        Main method: analyzes the task and creates a plan.

        Args:
            task: Task description from the user

        Returns:
            ExecutionPlan with a high-level plan
        """
        logger.info(f"Architect analyzing task: {task}")

        # 1. Analyze project structure
        project_summary = await self._analyze_project()

        # 2. Assess complexity
        complexity = await self._assess_complexity(task, project_summary)

        # 3. Create plan via LLM
        plan = await self._create_execution_plan(task, project_summary, complexity)

        # 4. Check if HITL is needed
        if self._needs_human_approval(plan):
            plan.requires_human_approval = True
            plan.approval_needed_for = self._get_approval_points(plan)

        return plan

    async def _analyze_project(self) -> str:
        """Analyzes project structure (with caching)."""
        if self._project_cache is not None:
            return self._project_cache["summary"]

        logger.info("Analyzing project structure...")
        self.project_analyzer.analyze_project()

        summary = self.project_analyzer.get_project_summary()

        self._project_cache = {
            "summary": summary,
            "files": self.project_analyzer.file_cache,
            "graph": self.project_analyzer.dependency_graph,
        }

        return summary

    async def _assess_complexity(
        self,
        task: str,
        project_summary: str
    ) -> TaskComplexity:
        """Determines task complexity."""
        if not self.config.auto_detect_complexity:
            return self.config.default_complexity

        # Keywords for complexity detection
        complex_keywords = [
            "refactor", "architecture", "redesign", "migrate",
            "multi", "agent", "orchestrat", "system"
        ]
        experimental_keywords = [
            "experimental", "ai", "ml", "neural", "self-heal",
            "autonomous", "agentic"
        ]

        task_lower = task.lower()

        if any(kw in task_lower for kw in experimental_keywords):
            return TaskComplexity.EXPERIMENTAL
        if any(kw in task_lower for kw in complex_keywords):
            return TaskComplexity.COMPLEX

        # Check number of files in the project
        file_count = len(self.project_analyzer.file_cache)
        if file_count > 30:
            return TaskComplexity.COMPLEX
        if file_count > 10:
            return TaskComplexity.MEDIUM

        return TaskComplexity.SIMPLE

    async def _create_execution_plan(
        self,
        task: str,
        project_summary: str,
        complexity: TaskComplexity
    ) -> ExecutionPlan:
        """Creates a high-level plan via LLM."""
        prompt = self.config.analysis_prompt_template.format(
            task=task,
            project_summary=project_summary
        )

        try:
            response = await self.llm_client.generate(prompt)
            raw = response.content.strip() if hasattr(response, 'content') else str(response)

            # Parse JSON
            import json
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
            data = json.loads(raw.strip())

            return ExecutionPlan(
                goal=task,
                complexity=TaskComplexity(data.get("complexity", "medium")),
                stages=data.get("stages", []),
                risk_assessment=data.get("risk", ""),
                dependencies=data.get("dependencies", []),
                estimated_stages=len(data.get("stages", [])),
                requires_human_approval=data.get("needs_approval", False),
                rollback_strategy=data.get("rollback", "git revert"),
            )

        except Exception as e:
            logger.warning(f"Failed to parse LLM response: {e}")
            # Fallback simple plan
            return ExecutionPlan(
                goal=task,
                complexity=complexity,
                stages=["Analyze", "Implement", "Verify"],
                risk_assessment="Auto-generated simple plan",
                estimated_stages=3,
            )

    def _needs_human_approval(self, plan: ExecutionPlan) -> bool:
        """Determines if human-in-the-loop is needed."""
        # Complex or experimental tasks
        if plan.complexity in (
            TaskComplexity.COMPLEX,
            TaskComplexity.EXPERIMENTAL
        ):
            return True

        # Destructive operations
        destructive_patterns = ["delete", "remove", "drop", "migration"]
        if any(p in plan.goal.lower() for p in destructive_patterns):
            return True

        return self.config.always_ask_for_complex and plan.complexity >= self.config.destructive_threshold

    def _get_approval_points(self, plan: ExecutionPlan) -> List[str]:
        """Determines where confirmation is needed."""
        points = []

        # Always ask at the start for complex tasks
        if plan.complexity >= TaskComplexity.COMPLEX:
            points.append("start")

        # Ask before the final stage
        if plan.estimated_stages > 2:
            points.append("before_final")

        return points

    async def request_approval(
        self,
        plan: ExecutionPlan,
        current_stage: str
    ) -> bool:
        """
        Requests confirmation from the user via HITL.

        Args:
            plan: Current plan
            current_stage: Current stage

        Returns:
            True if the user confirmed
        """
        if not plan.requires_human_approval:
            return True

        if current_stage not in plan.approval_needed_for and current_stage != "start":
            return True

        message = "\n" + "="*50
        message += "\nArchitect Approval Request"
        message += "\n" + "="*50
        message += f"\nTask: {plan.goal}"
        message += f"\nComplexity: {plan.complexity.value}"
        message += f"\nCurrent stage: {current_stage}"
        message += f"\n\nRisk: {plan.risk_assessment}"
        message += f"\n\nRollback: {plan.rollback_strategy}"
        message += "\n" + "="*50
        message += "\nProceed?"

        return await self._ask_user(message)

    def get_related_files(self, file_path: str, max_files: int = 5) -> List[str]:
        """Get related files for context."""
        return self.project_analyzer._find_related_files(file_path, max_files)

    def get_file_context(self, file_path: str) -> str:
        """Get file context for passing to the executor."""
        return self.project_analyzer.get_context_for_file(file_path)
