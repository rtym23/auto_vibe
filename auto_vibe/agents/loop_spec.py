"""Loop spec — portable format for exporting and importing plans."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, TYPE_CHECKING
from pathlib import Path
import yaml

if TYPE_CHECKING:
    from auto_vibe.agents.planner import Plan  # Stage used in type hints



logger = logging.getLogger(__name__)


@dataclass
class StopGuards:
    """Stop conditions for the loop."""
    max_iterations: int = 12
    max_revisions: int = 3
    max_no_progress: int = 2  # How many consecutive no-progress attempts allowed
    budget_cap_usd: float | None = None
    budget_cap_tokens: int | None = None
    timeout_seconds: int | None = None


@dataclass
class ExecutionConfig:
    """Execution configuration."""
    host_model: str = "default"
    reviewer_model: str | None = None
    judge_model: str | None = None
    use_different_family: bool = True
    execution_boundary: str = "current_workspace"  # current_workspace, branch, worktree, external


@dataclass
class LoopSpec:
    """
    Loop specification — portable format for export/import.
    Analogous to loop.yaml from Looper.
    """
    # Goal
    goal: str
    goal_context: str = ""
    definition_of_done: List[str] = field(default_factory=list)

    # Plan
    stages: List[dict] = field(default_factory=list)  # Serialized Stage objects

    # Execution
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    # Verification
    verification: List[dict] = field(default_factory=list)  # Serialized VerificationRule objects

    # Stop guards
    stop_guards: StopGuards = field(default_factory=StopGuards)

    # State
    state_file: str = "state.json"
    log_file: str = "run-log.md"

    # Metadata
    version: str = "1.0"
    created_at: str = ""

    @classmethod
    def from_plan(cls, plan: 'Plan', config: ExecutionConfig | None = None) -> "LoopSpec":
        """Create a specification from a plan."""
        from datetime import datetime

        stages_data = []
        for stage in plan.stages:
            stages_data.append({
                "name": stage.name,
                "description": stage.description,
                "command": stage.command,
                "target_file": stage.target_file,
            })

        return cls(
            goal=plan.goal,
            stages=stages_data,
            execution=config or ExecutionConfig(),
            created_at=datetime.now().isoformat(),
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "goal": self.goal,
            "goal_context": self.goal_context,
            "definition_of_done": self.definition_of_done,
            "stages": self.stages,
            "execution": asdict(self.execution),
            "verification": self.verification,
            "stop_guards": asdict(self.stop_guards),
            "state_file": self.state_file,
            "log_file": self.log_file,
            "version": self.version,
            "created_at": self.created_at,
        }

    def to_yaml(self) -> str:
        """Export to YAML format."""
        return yaml.dump(self.to_dict(), default_flow_style=False, sort_keys=False)

    def to_json(self) -> str:
        """Export to JSON format."""
        return json.dumps(self.to_dict(), indent=2)

    def save_yaml(self, path: str | Path) -> None:
        """Save to YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_yaml(), encoding="utf-8")
        logger.info(f"Loop spec saved to {path}")

    def save_json(self, path: str | Path) -> None:
        """Save to JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        logger.info(f"Loop spec saved to {path}")

    @classmethod
    def load_yaml(cls, path: str | Path) -> "LoopSpec":
        """Load from YAML file."""
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls._from_dict(data)

    @classmethod
    def load_json(cls, path: str | Path) -> "LoopSpec":
        """Load from JSON file."""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "LoopSpec":
        """Create from dictionary."""
        execution = ExecutionConfig(**data.get("execution", {}))
        stop_guards = StopGuards(**data.get("stop_guards", {}))

        return cls(
            goal=data.get("goal", ""),
            goal_context=data.get("goal_context", ""),
            definition_of_done=data.get("definition_of_done", []),
            stages=data.get("stages", []),
            execution=execution,
            verification=data.get("verification", []),
            stop_guards=stop_guards,
            state_file=data.get("state_file", "state.json"),
            log_file=data.get("log_file", "run-log.md"),
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", ""),
        )

    def to_plan(self) -> 'Plan':
        """Convert to Plan object."""
        from auto_vibe.agents.planner import Plan, Stage  # Local import

        stages = []
        for s in self.stages:
            stage = Stage(
                name=s.get("name", ""),
                description=s.get("description", ""),
                command=s.get("command"),
                target_file=s.get("target_file"),
            )
            stages.append(stage)

        return Plan(goal=self.goal, stages=stages)

    def to_ascii_flow(self) -> str:
        """
        Generates an ASCII representation of the loop flow (like in Looper).
        """
        lines = ["Loop Flow:", "=" * 50]

        # Goal
        lines.append(f"\nGoal: {self.goal}")

        # Stages with gates
        for i, stage in enumerate(self.stages, 1):
            lines.append(f"\n{i}. {stage['name']}")
            lines.append(f"   {stage['description']}")
            if stage.get('command'):
                lines.append(f"   Command: {stage['command']}")

            # Add gate after each stage (except last)
            if i < len(self.stages):
                lines.append(f"   ↓ [GATE: verify] {'↓' if i < len(self.stages) - 1 else ''}")

        # Stop guards
        lines.append("\n" + "=" * 50)
        lines.append("Stop Guards:")
        sg = self.stop_guards
        lines.append(f"  - Max iterations: {sg.max_iterations}")
        lines.append(f"  - Max revisions: {sg.max_revisions}")
        lines.append(f"  - Max no-progress: {sg.max_no_progress}")
        if sg.budget_cap_usd:
            lines.append(f"  - Budget cap: ${sg.budget_cap_usd}")
        if sg.budget_cap_tokens:
            lines.append(f"  - Token cap: {sg.budget_cap_tokens}")

        return "\n".join(lines)


class LoopSpecManager:
    """Manager for working with LoopSpec."""

    def __init__(self, output_dir: str | Path = "looper-output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save_spec(self, spec: LoopSpec, name: str = "loop") -> None:
        """Save specification in multiple formats."""
        # YAML
        spec.save_yaml(self.output_dir / f"{name}.yaml")
        # JSON resolved
        spec.save_json(self.output_dir / f"{name}.resolved.json")

        # State file
        state = {
            "current_stage": 0,
            "completed_stages": [],
            "iterations": 0,
            "revisions": 0,
            "no_progress_count": 0,
            "total_cost_usd": 0.0,
            "total_tokens": 0,
            "status": "pending",
        }
        (self.output_dir / spec.state_file).write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )

        # Run log
        (self.output_dir / spec.log_file).write_text(
            f"# Run Log\n\nCreated: {spec.created_at}\n\n",
            encoding="utf-8"
        )

        logger.info(f"Loop spec files saved to {self.output_dir}")

    def load_spec(self, name: str = "loop") -> LoopSpec:
        """Load specification."""
        yaml_path = self.output_dir / f"{name}.yaml"
        json_path = self.output_dir / f"{name}.resolved.json"

        if yaml_path.exists():
            return LoopSpec.load_yaml(yaml_path)
        elif json_path.exists():
            return LoopSpec.load_json(json_path)
        else:
            raise FileNotFoundError(f"Loop spec not found in {self.output_dir}")

    def update_state(self, state_updates: dict) -> dict:
        """Update state."""
        state_file = self.output_dir / "state.json"

        if state_file.exists():
            state = json.loads(state_file.read_text(encoding="utf-8"))
        else:
            state = {}

        state.update(state_updates)
        state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

        return state

    def append_log(self, message: str) -> None:
        """Append entry to log."""
        from datetime import datetime
        log_file = self.output_dir / "run-log.md"

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"\n## {timestamp}\n\n{message}\n"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)
