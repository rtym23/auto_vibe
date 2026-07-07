from fastmcp import FastMCP
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from auto_vibe.config.settings import Settings
from auto_vibe.integrations.llm import create_llm_client, LLMClient
from auto_vibe.core.loop import AutoVibeLoop
from auto_vibe.agents.planner import Planner
from auto_vibe.network.reconnect import ReconnectManager, ConnectionMonitor

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)

# Initialize MCP server
mcp = FastMCP("AutoVibe")

# Load settings at module level
settings = Settings.load()

# Project root for path validation
PROJECT_ROOT = Path.cwd().resolve()

# Global LLM client (singleton)
_llm_client = None
_client_initialized = False

# Reconnection manager
reconnect_manager = ReconnectManager(max_retries=5)

# Connection monitor
connection_monitor: ConnectionMonitor | None = None

# Dashboard instance
_dashboard_app = None


def _start_dashboard():
    """Start the dashboard in a separate thread."""
    global _dashboard_app
    
    if not settings.dashboard.enabled:
        logger.info("Dashboard is disabled in settings")
        return
    
    try:
        from auto_vibe.dashboard.app import DashboardApp
        _dashboard_app = DashboardApp(settings)
        
        # Add initial logs before starting
        _dashboard_app._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": f"AutoVibe server starting on {settings.dashboard.host}:{settings.dashboard.port}",
            "level": "info",
            "source": "server"
        })
        _dashboard_app._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": f"LLM Provider: {settings.llm.provider}, Model: {settings.llm.model}",
            "level": "info",
            "source": "server"
        })
        _dashboard_app._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": "Dashboard initialized and ready",
            "level": "info",
            "source": "server"
        })
        
        logger.info(f"Starting dashboard on {settings.dashboard.host}:{settings.dashboard.port}")
        
        # Run in a separate thread (non-daemon to keep it alive)
        dashboard_thread = threading.Thread(target=_dashboard_app.run, daemon=True)
        dashboard_thread.start()
        
        # Give it a moment to start
        import time
        time.sleep(0.5)
        
        logger.info("Dashboard started successfully")
    except Exception as e:
        logger.error(f"Failed to start dashboard: {e}")
        import traceback
        traceback.print_exc()


def get_dashboard():
    """Get the dashboard instance."""
    return _dashboard_app


def _validate_path(file_path: str) -> Path | None:
    """Validate that a file path is within the project root.

    Returns the resolved path if valid, None otherwise.
    """
    try:
        resolved = Path(file_path).resolve()
        if resolved.is_relative_to(PROJECT_ROOT):
            return resolved
        logger.warning(f"Path traversal attempt blocked: {file_path}")
        return None
    except Exception:
        return None


async def _get_llm_client() -> 'LLMClient':
    """Get global LLM client (singleton)."""
    global _llm_client, _client_initialized

    if _llm_client is not None and _client_initialized:
        return _llm_client

    _llm_client = create_llm_client(settings.llm)
    _client_initialized = True
    logger.info(f"LLM client initialized: {settings.llm.model}")
    return _llm_client


async def _ensure_connection():
    """Ensure active connection with LLM."""
    global connection_monitor

    if settings.llm.provider == "mock":
        return await _get_llm_client()

    if connection_monitor is None:
        connection_monitor = ConnectionMonitor(
            check_interval=30.0,
            on_disconnect=lambda: logger.warning("Connection lost!")
        )
        await connection_monitor.start()

    try:
        client = await reconnect_manager.connect(
            _get_llm_client,
            on_disconnect=lambda e: print(f"Connection lost: {e}")
        )
        return client
    except Exception as e:
        logger.error(f"Failed to establish connection: {e}")
        raise


async def _reset_client():
    """Reset LLM client for reconnection."""
    global _llm_client, _client_initialized
    _llm_client = None
    _client_initialized = False
    logger.info("LLM client reset for reconnection")


@mcp.tool()
async def ask_ai(prompt: str) -> str:
    """Ask AI a question."""
    dashboard = get_dashboard()
    if dashboard:
        dashboard.add_log(f"ask_ai called with prompt: {prompt[:100]}...", "info", "mcp")
        dashboard.add_task_update("ask_ai", "running", 0, {"prompt": prompt[:50]})
    
    client = await _ensure_connection()
    
    if dashboard:
        dashboard.add_log("Generating response via LLM...", "info", "llm")
    
    response = await client.generate(prompt)
    
    if dashboard:
        dashboard.add_log(f"Response generated ({len(response.content)} chars)", "success", "llm")
        dashboard.record_request(True, response.usage.get("total_tokens", 0) if response.usage else 0)
        dashboard.add_task_update("ask_ai", "completed", 100, {"response_length": len(response.content)})
    
    return response.content


@mcp.tool()
def get_status() -> str:
    """Get system status."""
    status = f"AutoVibe version {settings.llm.model} is running."
    if connection_monitor and connection_monitor._running:
        status += " [Connection monitor active]"
    return status


@mcp.tool()
async def fix_file(file_path: str, error_description: str) -> str:
    """Fix file based on error description."""
    from auto_vibe.core.fixer import Fixer
    
    dashboard = get_dashboard()
    if dashboard:
        dashboard.add_log(f"fix_file called for: {file_path}", "info", "mcp")
        dashboard.add_task_update(f"fix:{file_path}", "running", 0, {"error": error_description[:100]})

    validated_path = _validate_path(file_path)
    if validated_path is None:
        if dashboard:
            dashboard.add_log("Access denied: path outside project directory", "error", "mcp")
        return "Access denied: path is outside the project directory"

    if not validated_path.exists():
        if dashboard:
            dashboard.add_log(f"File not found: {file_path}", "error", "mcp")
        return f"File not found: {file_path}"

    file_content = validated_path.read_text(encoding="utf-8")
    
    if dashboard:
        dashboard.add_log(f"Reading file: {file_path} ({len(file_content)} chars)", "info", "mcp")

    client = await _ensure_connection()
    fixer = Fixer(client)

    if dashboard:
        dashboard.add_log("Analyzing error and generating fix...", "info", "llm")

    fix = await fixer.suggest_fix(
        error_msg=error_description,
        file_path=str(validated_path),
        file_content=file_content,
    )

    if fix and not fix.startswith("# Error"):
        validated_path.write_text(fix.strip(), encoding="utf-8")
        if dashboard:
            dashboard.add_log(f"Fix applied to {file_path}", "success", "mcp")
            dashboard.add_task_update(f"fix:{file_path}", "completed", 100, {"fix_length": len(fix)})
        return f"Fixed: {file_path}"
    else:
        if dashboard:
            dashboard.add_log(f"Failed to get fix: {fix[:100] if fix else 'None'}...", "warning", "llm")
            dashboard.add_task_update(f"fix:{file_path}", "failed", 100, {})
        return f"Failed to get fix: {fix}"


@mcp.tool()
async def run_loop(task: str, target_file: str | None = None, command: str | None = None) -> str:
    """Run task fixing loop."""
    dashboard = get_dashboard()
    if dashboard:
        dashboard.add_log(f"run_loop started: {task[:50]}...", "info", "mcp")
        dashboard.add_task_update(f"loop:{task[:30]}", "running", 0, {"task": task, "target_file": target_file})
    
    if target_file is not None:
        validated_path = _validate_path(target_file)
        if validated_path is None:
            if dashboard:
                dashboard.add_log("Access denied: target_file outside project directory", "error", "mcp")
            return "Access denied: target_file is outside the project directory"
        target_file = str(validated_path)

    client = await _ensure_connection()
    loop = AutoVibeLoop(settings, client)
    
    if dashboard:
        dashboard.add_log("Starting AutoVibeLoop execution...", "info", "loop")

    result = await loop.run(
        task=task,
        target_file=target_file,
        command=command,
    )
    
    if dashboard:
        if result:
            dashboard.add_log(f"run_loop completed successfully", "success", "loop")
            dashboard.add_task_update(f"loop:{task[:30]}", "completed", 100, {"result": "success"})
        else:
            dashboard.add_log(f"run_loop failed or stopped", "error", "loop")
            dashboard.add_task_update(f"loop:{task[:30]}", "failed", 100, {"result": "failure"})
    
    return "Success" if result else "Failure"


@mcp.tool()
async def plan_and_execute(prompt: str) -> str:
    """Create task plan and execute stages."""
    dashboard = get_dashboard()
    if dashboard:
        dashboard.add_log(f"plan_and_execute started: {prompt[:50]}...", "info", "mcp")
        dashboard.add_task_update(f"plan:{prompt[:30]}", "running", 0, {"prompt": prompt})
    
    client = await _ensure_connection()
    planner = Planner(client)
    
    if dashboard:
        dashboard.add_log("Creating task plan...", "info", "planner")

    plan = await planner.create_plan(prompt)
    
    if dashboard:
        dashboard.add_log(f"Plan created with {len(plan.stages)} stages", "info", "planner")

    async def execute_stage(stage):
        if dashboard:
            dashboard.add_log(f"Executing stage: {stage.description[:50]}...", "info", "planner")
        loop = AutoVibeLoop(settings, client)
        return await loop.run(
            task=stage.description,
            target_file=stage.target_file,
            command=stage.command,
        )

    result = await planner.execute_plan(plan, execute_stage)

    if result:
        if dashboard:
            dashboard.add_log(f"Plan executed successfully! {len(plan.stages)} stages completed.", "success", "planner")
            dashboard.add_task_update(f"plan:{prompt[:30]}", "completed", 100, {"stages": len(plan.stages)})
        return f"Plan executed successfully! {len(plan.stages)} stages completed."
    else:
        if dashboard:
            dashboard.add_log(f"Execution stopped at stage {plan.current_stage}", "warning", "planner")
            dashboard.add_task_update(f"plan:{prompt[:30]}", "failed", 100, {"stopped_at": plan.current_stage})
        return f"Execution stopped at stage {plan.current_stage}"


def main():
    """Entry point for MCP server."""
    # Start dashboard automatically
    _start_dashboard()
    
    # Run MCP server
    mcp.run()


if __name__ == "__main__":
    main()
