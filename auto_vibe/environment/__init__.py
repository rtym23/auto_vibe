"""Environment — dev environment, terminals, shadow workspace."""

from auto_vibe.environment.manager import EnvironmentManager
from auto_vibe.environment.terminals import TerminalManager
from auto_vibe.environment.shadow import ShadowWorkspace

__all__ = ["EnvironmentManager", "TerminalManager", "ShadowWorkspace"]
