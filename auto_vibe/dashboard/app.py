"""Web monitoring panel with WebSocket."""

from __future__ import annotations

import logging
import os
import secrets
import threading
from datetime import datetime
from typing import Any, Callable, Set

from flask import Flask, jsonify, render_template_string, request
from flask_socketio import SocketIO, emit

from auto_vibe.config.settings import Settings


logger = logging.getLogger(__name__)


class DashboardApp:
    """
    Web monitoring panel on Flask with WebSocket.
    Real-time logging and control for neural network operations.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.app = Flask(__name__)
        self.app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
        self.socketio = SocketIO(
            self.app,
            cors_allowed_origins=["http://localhost:7891", "http://127.0.0.1:7891"],
            async_mode="threading"
        )
        self._clients: Set[str] = set()
        self._logs: list = []
        self._max_logs = 500
        self._current_task: dict | None = None
        self._active_tasks: dict = {}
        self._metrics: dict = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_tokens": 0,
            "session_start": datetime.now().isoformat(),
        }
        self._network_stats: dict = {
            "requests_count": 0,
            "avg_latency_ms": 0,
            "last_request_time": None,
            "errors_count": 0,
            "reconnects_count": 0,
        }
        self._debug_info: dict = {
            "connection_status": "disconnected",
            "llm_provider": settings.llm.provider,
            "llm_model": settings.llm.model,
            "memory_usage_mb": 0,
            "uptime_seconds": 0,
        }
        self._settings_cache = settings.model_dump()
        self._ide_errors: list = []
        self._log_callbacks: list[Callable] = []
        self._start_time = datetime.now()
        self._setup_routes()
        self._setup_socket_events()
        self._start_log_listener()

    def _start_log_listener(self) -> None:
        """Start listening to Python logging and forward to dashboard."""
        # Add startup logs immediately
        self._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": "Dashboard initialized - waiting for connections...",
            "level": "info",
            "source": "system"
        })
        self._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": f"LLM: {self.settings.llm.provider}/{self.settings.llm.model}",
            "level": "info",
            "source": "system"
        })
        self._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": "All auto_vibe logs will appear here in real-time",
            "level": "info",
            "source": "system"
        })
        
        # Set up handler in main thread to avoid threading issues
        handler = _DashboardLogHandler(self)
        handler.setLevel(logging.DEBUG)
        
        # Add to auto_vibe logger
        auto_vibe_logger = logging.getLogger("auto_vibe")
        auto_vibe_logger.addHandler(handler)
        auto_vibe_logger.setLevel(logging.DEBUG)
        
        # Also add to root logger for catch-all
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(logging.DEBUG)

    def _setup_routes(self) -> None:
        @self.app.route("/")
        def index():
            return render_template_string(DASHBOARD_HTML)

        @self.app.route("/api/status")
        def status():
            return jsonify({
                "status": "ok",
                "version": "1.0.0",
                "clients": len(self._clients),
                "logs_count": len(self._logs),
                "current_task": self._current_task,
                "metrics": self._metrics,
            })

        @self.app.route("/api/logs")
        def get_logs():
            limit = request.args.get("limit", 50, type=int)
            return jsonify(self._logs[-limit:])

        @self.app.route("/api/settings")
        def get_settings():
            return jsonify(self._settings_cache)

        @self.app.route("/api/settings", methods=["POST"])
        def update_settings():
            data = request.get_json()
            if data:
                self._settings_cache.update(data)
                self.add_log("Settings updated", "info", "settings")
            return jsonify({"status": "ok"})

        @self.app.route("/api/metrics")
        def get_metrics():
            return jsonify(self._metrics)

        @self.app.route("/api/network")
        def get_network_stats():
            # Update uptime
            self._debug_info["uptime_seconds"] = int((datetime.now() - self._start_time).total_seconds())
            return jsonify(self._network_stats)

        @self.app.route("/api/debug")
        def get_debug_info():
            # Update runtime info
            self._debug_info["uptime_seconds"] = int((datetime.now() - self._start_time).total_seconds())
            self._debug_info["clients_count"] = len(self._clients)
            self._debug_info["logs_count"] = len(self._logs)
            self._debug_info["active_tasks_count"] = len(self._active_tasks)
            return jsonify(self._debug_info)

        @self.app.route("/api/tasks")
        def get_active_tasks():
            return jsonify(self._active_tasks)

        @self.app.route("/api/clear-logs", methods=["POST"])
        def clear_logs():
            self._logs = []
            return jsonify({"status": "ok"})

        @self.app.route("/api/ide-errors")
        def get_ide_errors():
            return jsonify(self._ide_errors)

        @self.app.route("/api/ide-errors", methods=["POST"])
        def add_ide_error():
            data = request.get_json()
            if data:
                self._ide_errors.append({
                    "timestamp": datetime.now().isoformat(),
                    "error": data.get("error", ""),
                    "file": data.get("file", ""),
                    "line": data.get("line", 0),
                    "severity": data.get("severity", "error")
                })
                if len(self._ide_errors) > 100:
                    self._ide_errors = self._ide_errors[-100:]
            return jsonify({"status": "ok"})

        @self.app.route("/api/ide-errors", methods=["DELETE"])
        def clear_ide_errors():
            self._ide_errors = []
            return jsonify({"status": "ok"})

    def _setup_socket_events(self) -> None:
        @self.socketio.on("connect")
        def handle_connect():
            sid = request.sid
            self._clients.add(sid)
            logger.info(f"Dashboard client connected: {sid}")
            emit("clients_update", {"count": len(self._clients)})
            emit("log", {
                "level": "info",
                "message": "Connected to AutoVibe Dashboard",
                "timestamp": datetime.now().isoformat(),
                "source": "system"
            })
            emit("metrics", self._metrics)
            if self._current_task:
                emit("task_update", self._current_task)

        @self.socketio.on("disconnect")
        def handle_disconnect():
            sid = request.sid
            self._clients.discard(sid)
            logger.info(f"Dashboard client disconnected: {sid}")
            emit("clients_update", {"count": len(self._clients)})

        @self.socketio.on("send_log")
        def handle_log(data):
            self.add_log(
                data.get("message", ""),
                data.get("level", "info"),
                data.get("source", "client")
            )

    def add_log(self, message: str, level: str = "info", source: str = "system") -> None:
        """Adds a log entry and broadcasts to all clients."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "message": message,
            "level": level,
            "source": source
        }
        self._logs.append(entry)
        if len(self._logs) > self._max_logs:
            self._logs = self._logs[-self._max_logs:]
        
        # Only emit if there are connected clients
        if self._clients:
            try:
                self.socketio.emit("log", entry)
            except Exception as e:
                logger.warning(f"Failed to emit log: {e}")

    def add_ide_error(self, error: str, file: str = "", line: int = 0, severity: str = "error") -> None:
        """Adds an IDE error and broadcasts to all clients."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "error": error,
            "file": file,
            "line": line,
            "severity": severity
        }
        self._ide_errors.append(entry)
        if len(self._ide_errors) > 100:
            self._ide_errors = self._ide_errors[-100:]
        
        if self._clients:
            try:
                self.socketio.emit("ide_error", entry)
            except Exception as e:
                logger.warning(f"Failed to emit ide_error: {e}")

    def add_task_update(self, task_id: str, status: str, progress: float = 0, details: dict | None = None) -> None:
        """Sends a task update."""
        self._current_task = {
            "task_id": task_id,
            "status": status,
            "progress": progress,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Track active tasks
        if status == "running":
            self._active_tasks[task_id] = self._current_task.copy()
        elif status in ["completed", "failed"] and task_id in self._active_tasks:
            self._active_tasks[task_id]["status"] = status
            self._active_tasks[task_id]["progress"] = progress
            self._active_tasks[task_id]["completed_at"] = datetime.now().isoformat()
        
        if self._clients:
            try:
                self.socketio.emit("task_update", self._current_task)
            except Exception as e:
                logger.warning(f"Failed to emit task_update: {e}")

    def update_metrics(self, **kwargs) -> None:
        """Update metrics and broadcast."""
        self._metrics.update(kwargs)
        if self._clients:
            try:
                self.socketio.emit("metrics", self._metrics)
            except Exception as e:
                logger.warning(f"Failed to emit metrics: {e}")

    def record_request(self, success: bool, tokens: int = 0) -> None:
        """Record an LLM request."""
        self._metrics["total_requests"] += 1
        if success:
            self._metrics["successful_requests"] += 1
        else:
            self._metrics["failed_requests"] += 1
        self._metrics["total_tokens"] += tokens
        
        # Update network stats
        self._network_stats["requests_count"] += 1
        if not success:
            self._network_stats["errors_count"] += 1
        
        if self._clients:
            try:
                self.socketio.emit("metrics", self._metrics)
            except Exception as e:
                logger.warning(f"Failed to emit metrics: {e}")

    def update_network_stats(self, latency_ms: float = 0, error: bool = False, reconnect: bool = False) -> None:
        """Update network statistics."""
        if latency_ms > 0:
            # Calculate moving average
            current_avg = self._network_stats["avg_latency_ms"]
            count = self._network_stats["requests_count"]
            if count > 0:
                self._network_stats["avg_latency_ms"] = (current_avg * (count - 1) + latency_ms) / count
        
        self._network_stats["last_request_time"] = datetime.now().isoformat()
        
        if error:
            self._network_stats["errors_count"] += 1
        
        if reconnect:
            self._network_stats["reconnects_count"] += 1
        
        if self._clients:
            try:
                self.socketio.emit("network_stats", self._network_stats)
            except Exception as e:
                logger.warning(f"Failed to emit network_stats: {e}")

    def update_debug_info(self, **kwargs) -> None:
        """Update debug information."""
        self._debug_info.update(kwargs)
        if self._clients:
            try:
                self.socketio.emit("debug_info", self._debug_info)
            except Exception as e:
                logger.warning(f"Failed to emit debug_info: {e}")

    def set_connection_status(self, status: str) -> None:
        """Set connection status."""
        self._debug_info["connection_status"] = status
        if self._clients:
            try:
                self.socketio.emit("debug_info", self._debug_info)
            except Exception as e:
                logger.warning(f"Failed to emit debug_info: {e}")

    def run(self) -> None:
        """Starts server with WebSocket."""
        logger.info(f"Starting Dashboard on {self.settings.dashboard.host}:{self.settings.dashboard.port}")
        
        # Add startup logs
        self._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": f"Dashboard starting on {self.settings.dashboard.host}:{self.settings.dashboard.port}",
            "level": "info",
            "source": "system"
        })
        self._logs.append({
            "timestamp": datetime.now().isoformat(),
            "message": "AutoVibe Dashboard is ready. Waiting for connections...",
            "level": "info",
            "source": "system"
        })
        
        self.socketio.run(
            self.app,
            host=self.settings.dashboard.host,
            port=self.settings.dashboard.port,
            debug=False,
            allow_unsafe_werkzeug=True
        )

    def run_simple(self) -> None:
        """Starts without WebSocket (for compatibility)."""
        self.app.run(host=self.settings.dashboard.host, port=self.settings.dashboard.port)


class _DashboardLogHandler(logging.Handler):
    """Logging handler that forwards logs to dashboard."""

    def __init__(self, dashboard: DashboardApp):
        super().__init__()
        self.dashboard = dashboard

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = record.levelname.lower()
            if level not in ["debug", "info", "warning", "error", "critical"]:
                level = "info"
            
            message = record.getMessage()
            source = record.name or "logger"
            
            self.dashboard.add_log(message, level, source)
        except Exception:
            self.handleError(record)


DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AutoVibe Dashboard</title>
    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        :root {
            --bg-primary: #0f0f1a;
            --bg-secondary: #1a1a2e;
            --bg-tertiary: #16213e;
            --accent-cyan: #00d4ff;
            --accent-green: #00ff88;
            --accent-orange: #ff9500;
            --accent-red: #ff4757;
            --accent-purple: #a855f7;
            --text-primary: #ffffff;
            --text-secondary: #94a3b8;
            --border-color: #2d3748;
        }
        
        body {
            font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid var(--border-color);
            margin-bottom: 24px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            gap: 12px;
        }
        
        .logo h1 {
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .logo-icon {
            width: 40px;
            height: 40px;
            background: linear-gradient(135deg, var(--accent-cyan), var(--accent-purple));
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
        }
        
        .status-badge {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            background: var(--bg-secondary);
            border-radius: 20px;
            border: 1px solid var(--border-color);
        }
        
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 2s infinite;
        }
        
        .status-dot.disconnected {
            background: var(--accent-red);
            animation: none;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }
        
        .card {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            border: 1px solid var(--border-color);
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .card-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .metric-value {
            font-size: 32px;
            font-weight: 700;
            color: var(--accent-cyan);
        }
        
        .metric-value.success { color: var(--accent-green); }
        .metric-value.warning { color: var(--accent-orange); }
        .metric-value.error { color: var(--accent-red); }
        
        .metric-label {
            font-size: 13px;
            color: var(--text-secondary);
            margin-top: 4px;
        }
        
        .progress-bar {
            height: 8px;
            background: var(--bg-tertiary);
            border-radius: 4px;
            overflow: hidden;
            margin-top: 12px;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--accent-cyan), var(--accent-purple));
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        
        .logs-container {
            background: var(--bg-secondary);
            border-radius: 12px;
            border: 1px solid var(--border-color);
            overflow: hidden;
        }
        
        .logs-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 20px;
            background: var(--bg-tertiary);
            border-bottom: 1px solid var(--border-color);
        }
        
        .logs-title {
            font-size: 16px;
            font-weight: 600;
        }
        
        .logs-actions {
            display: flex;
            gap: 8px;
        }
        
        .btn {
            padding: 8px 16px;
            border-radius: 6px;
            border: none;
            cursor: pointer;
            font-size: 13px;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: var(--accent-cyan);
            color: var(--bg-primary);
        }
        
        .btn-primary:hover {
            background: #00b8e0;
        }
        
        .btn-secondary {
            background: var(--bg-secondary);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }
        
        .btn-secondary:hover {
            background: var(--bg-tertiary);
        }
        
        .logs-content {
            height: 400px;
            overflow-y: auto;
            padding: 12px;
        }
        
        .log-entry {
            display: flex;
            align-items: flex-start;
            gap: 12px;
            padding: 10px 12px;
            margin-bottom: 4px;
            border-radius: 6px;
            background: var(--bg-tertiary);
            border-left: 3px solid var(--accent-cyan);
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 13px;
            animation: slideIn 0.2s ease;
        }
        
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        
        .log-entry.log-info { border-left-color: var(--accent-cyan); }
        .log-entry.log-warning { border-left-color: var(--accent-orange); }
        .log-entry.log-error { border-left-color: var(--accent-red); }
        .log-entry.log-debug { border-left-color: var(--text-secondary); }
        .log-entry.log-success { border-left-color: var(--accent-green); }
        
        .log-time {
            color: var(--text-secondary);
            font-size: 11px;
            white-space: nowrap;
        }
        
        .log-source {
            color: var(--accent-purple);
            font-size: 11px;
            padding: 2px 6px;
            background: var(--bg-secondary);
            border-radius: 4px;
            white-space: nowrap;
        }
        
        .log-message {
            flex: 1;
            word-break: break-word;
        }
        
        .log-level {
            font-size: 10px;
            font-weight: 600;
            text-transform: uppercase;
            padding: 2px 6px;
            border-radius: 4px;
        }
        
        .log-level.info { background: rgba(0, 212, 255, 0.2); color: var(--accent-cyan); }
        .log-level.warning { background: rgba(255, 149, 0, 0.2); color: var(--accent-orange); }
        .log-level.error { background: rgba(255, 71, 87, 0.2); color: var(--accent-red); }
        .log-level.debug { background: rgba(148, 163, 184, 0.2); color: var(--text-secondary); }
        .log-level.success { background: rgba(0, 255, 136, 0.2); color: var(--accent-green); }
        
        .settings-panel {
            display: none;
            position: fixed;
            top: 0;
            right: 0;
            width: 400px;
            height: 100vh;
            background: var(--bg-secondary);
            border-left: 1px solid var(--border-color);
            padding: 24px;
            overflow-y: auto;
            z-index: 1000;
            box-shadow: -4px 0 20px rgba(0, 0, 0, 0.3);
        }
        
        .settings-panel.open {
            display: block;
            animation: slideInRight 0.3s ease;
        }
        
        @keyframes slideInRight {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
        }
        
        .settings-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.5);
            z-index: 999;
        }
        
        .settings-overlay.open {
            display: block;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }
        
        .form-input {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: var(--text-primary);
            font-size: 14px;
        }
        
        .form-input:focus {
            outline: none;
            border-color: var(--accent-cyan);
        }
        
        .form-select {
            width: 100%;
            padding: 10px 14px;
            background: var(--bg-tertiary);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            color: var(--text-primary);
            font-size: 14px;
            cursor: pointer;
        }
        
        .task-card {
            background: var(--bg-tertiary);
            border-radius: 8px;
            padding: 16px;
            margin-top: 12px;
        }
        
        .task-status {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .task-status.running { background: rgba(0, 212, 255, 0.2); color: var(--accent-cyan); }
        .task-status.completed { background: rgba(0, 255, 136, 0.2); color: var(--accent-green); }
        .task-status.failed { background: rgba(255, 71, 87, 0.2); color: var(--accent-red); }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
        }
        
        .empty-state-icon {
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }
        
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        
        ::-webkit-scrollbar-track {
            background: var(--bg-tertiary);
        }
        
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        
        ::-webkit-scrollbar-thumb:hover {
            background: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">
                <div class="logo-icon">🤖</div>
                <h1>AutoVibe Dashboard</h1>
            </div>
            <div class="status-badge">
                <div class="status-dot" id="statusDot"></div>
                <span id="statusText">Connecting...</span>
            </div>
        </header>
        
        <div class="grid">
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Total Requests</span>
                </div>
                <div class="metric-value" id="totalRequests">0</div>
                <div class="metric-label">Neural network requests</div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Successful</span>
                </div>
                <div class="metric-value success" id="successfulRequests">0</div>
                <div class="metric-label">Completed successfully</div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Failed</span>
                </div>
                <div class="metric-value error" id="failedRequests">0</div>
                <div class="metric-label">Failed requests</div>
            </div>
            
            <div class="card">
                <div class="card-header">
                    <span class="card-title">Total Tokens</span>
                </div>
                <div class="metric-value" id="totalTokens">0</div>
                <div class="metric-label">Tokens processed</div>
            </div>
        </div>
        
        <div class="card" style="margin-bottom: 24px;">
            <div class="card-header">
                <span class="card-title">Current Task</span>
                <button class="btn btn-secondary" onclick="openSettings()">⚙️ Settings</button>
            </div>
            <div id="currentTask">
                <div class="empty-state">
                    <div class="empty-state-icon">📋</div>
                    <div>No active task</div>
                </div>
            </div>
        </div>
        
        <div class="logs-container">
            <div class="logs-header">
                <div class="tabs">
                    <button class="tab-btn active" data-tab="all" onclick="switchTab('all')">📊 All</button>
                    <button class="tab-btn" data-tab="network" onclick="switchTab('network')">🌐 Network</button>
                    <button class="tab-btn" data-tab="nn" onclick="switchTab('nn')">🧠 Neural Net</button>
                    <button class="tab-btn" data-tab="debug" onclick="switchTab('debug')">🔧 Debug</button>
                    <button class="tab-btn" data-tab="ide" onclick="switchTab('ide')">⚠️ IDE Errors</button>
                </div>
                <div class="logs-actions">
                    <button class="btn btn-secondary" onclick="clearLogs()">Clear</button>
                    <button class="btn btn-primary" onclick="fetchLogs()">Refresh</button>
                </div>
            </div>
            <div class="logs-content" id="logs"></div>
            <div class="logs-content" id="networkLogs" style="display: none;"></div>
            <div class="logs-content" id="nnLogs" style="display: none;"></div>
            <div class="logs-content" id="debugLogs" style="display: none;"></div>
            <div class="logs-content" id="ideErrors" style="display: none;"></div>
        </div>
    </div>
    
    <div class="settings-overlay" id="settingsOverlay" onclick="closeSettings()"></div>
    <div class="settings-panel" id="settingsPanel">
        <h2 style="margin-bottom: 24px;">⚙️ Settings</h2>
        
        <div class="form-group">
            <label class="form-label">LLM Provider</label>
            <select class="form-select" id="llmProvider">
                <option value="ollama">Ollama</option>
                <option value="openai">OpenAI</option>
                <option value="mesh_llm">Mesh LLM</option>
            </select>
        </div>
        
        <div class="form-group">
            <label class="form-label">Model</label>
            <input type="text" class="form-input" id="llmModel" placeholder="qwen3-8b-q4_k_m">
        </div>
        
        <div class="form-group">
            <label class="form-label">Base URL</label>
            <input type="text" class="form-input" id="llmBaseUrl" placeholder="http://localhost:11434">
        </div>
        
        <div class="form-group">
            <label class="form-label">Max Iterations</label>
            <input type="number" class="form-input" id="maxIterations" value="5">
        </div>
        
        <div class="form-group">
            <label class="form-label">Strategy</label>
            <select class="form-select" id="strategy">
                <option value="quick">Quick</option>
                <option value="deep">Deep</option>
                <option value="max">Max</option>
            </select>
        </div>
        
        <div class="form-group">
            <label class="form-label">Timeout (seconds)</label>
            <input type="number" class="form-input" id="timeout" value="30">
        </div>
        
        <div class="form-group">
            <label class="form-label">Memory Enabled</label>
            <select class="form-select" id="memoryEnabled">
                <option value="true">Yes</option>
                <option value="false">No</option>
            </select>
        </div>
        
        <button class="btn btn-primary" style="width: 100%; margin-top: 16px;" onclick="saveSettings()">Save Settings</button>
        <button class="btn btn-secondary" style="width: 100%; margin-top: 8px;" onclick="closeSettings()">Cancel</button>
    </div>
    
    <script>
        const socket = io();
        let currentTab = 'all';
        let autoScroll = true;
        
        socket.on('connect', () => {
            document.getElementById('statusDot').classList.remove('disconnected');
            document.getElementById('statusText').textContent = 'Connected';
            fetchSettings();
        });
        
        socket.on('disconnect', () => {
            document.getElementById('statusDot').classList.add('disconnected');
            document.getElementById('statusText').textContent = 'Disconnected';
        });
        
        socket.on('log', (data) => {
            addLogEntry(data);
        });
        
        socket.on('metrics', (data) => {
            document.getElementById('totalRequests').textContent = data.total_requests || 0;
            document.getElementById('successfulRequests').textContent = data.successful_requests || 0;
            document.getElementById('failedRequests').textContent = data.failed_requests || 0;
            document.getElementById('totalTokens').textContent = (data.total_tokens || 0).toLocaleString();
        });
        
        socket.on('task_update', (data) => {
            updateTaskDisplay(data);
        });
        
        socket.on('clients_update', (data) => {
            console.log('Clients:', data.count);
        });
        
        socket.on('ide_error', (data) => {
            addIdeErrorEntry(data);
        });
        
        socket.on('network_stats', (data) => {
            updateNetworkStats(data);
        });
        
        socket.on('debug_info', (data) => {
            updateDebugInfo(data);
        });
        
        function switchTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === tab);
            });
            
            document.getElementById('logs').style.display = tab === 'all' ? 'block' : 'none';
            document.getElementById('networkLogs').style.display = tab === 'network' ? 'block' : 'none';
            document.getElementById('nnLogs').style.display = tab === 'nn' ? 'block' : 'none';
            document.getElementById('debugLogs').style.display = tab === 'debug' ? 'block' : 'none';
            document.getElementById('ideErrors').style.display = tab === 'ide' ? 'block' : 'none';
            
            if (tab === 'ide') {
                fetchIdeErrors();
            } else if (tab === 'network') {
                fetchNetworkLogs();
            } else if (tab === 'nn') {
                fetchNnLogs();
            } else if (tab === 'debug') {
                fetchDebugLogs();
            }
        }
        
        function addLogEntry(data) {
            const targetDiv = getLogsDivForEntry(data);
            if (!targetDiv) return;
            
            const entry = document.createElement('div');
            entry.className = `log-entry log-${data.level || 'info'}`;
            
            const time = new Date(data.timestamp).toLocaleTimeString();
            const level = data.level || 'info';
            const source = data.source || 'system';
            
            entry.innerHTML = `
                <span class="log-time">${time}</span>
                <span class="log-source">${source}</span>
                <span class="log-message">${escapeHtml(data.message)}</span>
                <span class="log-level ${level}">${level}</span>
            `;
            
            targetDiv.appendChild(entry);
            
            if (autoScroll) {
                targetDiv.scrollTop = targetDiv.scrollHeight;
            }
            
            while (targetDiv.children.length > 200) {
                targetDiv.removeChild(targetDiv.firstChild);
            }
        }
        
        function getLogsDivForEntry(data) {
            const source = data.source || '';
            if (source.includes('network') || source.includes('http') || source.includes('request')) {
                return document.getElementById('networkLogs');
            }
            if (source.includes('nn') || source.includes('neural') || source.includes('llm') || source.includes('model')) {
                return document.getElementById('nnLogs');
            }
            if (source.includes('debug') || source.includes('mcp')) {
                return document.getElementById('debugLogs');
            }
            return document.getElementById('logs');
        }
        
        function addIdeErrorEntry(data) {
            const ideDiv = document.getElementById('ideErrors');
            const entry = document.createElement('div');
            entry.className = `log-entry log-error`;
            
            const time = new Date(data.timestamp).toLocaleTimeString();
            
            entry.innerHTML = `
                <span class="log-time">${time}</span>
                <span class="log-source">${data.file || 'unknown'}:${data.line || 0}</span>
                <span class="log-message">${escapeHtml(data.error)}</span>
                <span class="log-level error">${data.severity || 'error'}</span>
            `;
            
            ideDiv.appendChild(entry);
            
            if (autoScroll) {
                ideDiv.scrollTop = ideDiv.scrollHeight;
            }
        }
        
        async function fetchIdeErrors() {
            try {
                const response = await fetch('/api/ide-errors');
                const errors = await response.json();
                const ideDiv = document.getElementById('ideErrors');
                ideDiv.innerHTML = '';
                errors.forEach(addIdeErrorEntry);
            } catch (e) {
                console.error('Failed to fetch IDE errors:', e);
            }
        }
        
        async function fetchNetworkLogs() {
            try {
                const response = await fetch('/api/logs?limit=50');
                const logs = await response.json();
                const netDiv = document.getElementById('networkLogs');
                netDiv.innerHTML = '';
                logs.filter(l => {
                    const source = l.source || '';
                    return source.includes('network') || source.includes('http') || source.includes('request');
                }).forEach(addLogEntry);
            } catch (e) {
                console.error('Failed to fetch network logs:', e);
            }
        }
        
        async function fetchNnLogs() {
            try {
                const response = await fetch('/api/logs?limit=50');
                const logs = await response.json();
                const nnDiv = document.getElementById('nnLogs');
                nnDiv.innerHTML = '';
                logs.filter(l => {
                    const source = l.source || '';
                    return source.includes('nn') || source.includes('neural') || source.includes('llm') || source.includes('model');
                }).forEach(addLogEntry);
            } catch (e) {
                console.error('Failed to fetch neural net logs:', e);
            }
        }
        
        async function fetchDebugLogs() {
            try {
                const response = await fetch('/api/logs?limit=50');
                const logs = await response.json();
                const dbgDiv = document.getElementById('debugLogs');
                dbgDiv.innerHTML = '';
                logs.filter(l => {
                    const source = l.source || '';
                    return source.includes('debug') || source.includes('mcp');
                }).forEach(addLogEntry);
            } catch (e) {
                console.error('Failed to fetch debug logs:', e);
            }
        }
        
        function updateNetworkStats(data) {
            console.log('Network stats:', data);
        }
        
        function updateDebugInfo(data) {
            console.log('Debug info:', data);
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function updateTaskDisplay(data) {
            const taskDiv = document.getElementById('currentTask');
            if (!data || !data.task_id) {
                taskDiv.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-state-icon">📋</div>
                        <div>No active task</div>
                    </div>
                `;
                return;
            }
            
            const statusClass = data.status === 'running' ? 'running' : 
                               data.status === 'completed' ? 'completed' : 'failed';
            
            taskDiv.innerHTML = `
                <div class="task-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <span style="font-weight: 600;">${escapeHtml(data.task_id)}</span>
                        <span class="task-status ${statusClass}">${data.status}</span>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: ${data.progress || 0}%"></div>
                    </div>
                    <div style="margin-top: 12px; font-size: 13px; color: var(--text-secondary);">
                        ${data.details?.message || ''}
                    </div>
                </div>
            `;
        }
        
        async function fetchLogs() {
            try {
                const response = await fetch('/api/logs?limit=50');
                const logs = await response.json();
                const logsDiv = document.getElementById('logs');
                logsDiv.innerHTML = '';
                logs.forEach(addLogEntry);
            } catch (e) {
                console.error('Failed to fetch logs:', e);
            }
        }
        
        async function clearLogs() {
            try {
                await fetch('/api/clear-logs', { method: 'POST' });
                document.getElementById('logs').innerHTML = '';
                document.getElementById('networkLogs').innerHTML = '';
                document.getElementById('nnLogs').innerHTML = '';
                document.getElementById('debugLogs').innerHTML = '';
            } catch (e) {
                console.error('Failed to clear logs:', e);
            }
        }
        
        async function fetchSettings() {
            try {
                const response = await fetch('/api/settings');
                const settings = await response.json();
                
                if (settings.llm) {
                    document.getElementById('llmProvider').value = settings.llm.provider || 'ollama';
                    document.getElementById('llmModel').value = settings.llm.model || '';
                    document.getElementById('llmBaseUrl').value = settings.llm.base_url || '';
                }
                
                if (settings.strategy) {
                    document.getElementById('maxIterations').value = settings.strategy.max_iterations || 5;
                    document.getElementById('strategy').value = settings.strategy.default || 'deep';
                }
                
                if (settings.executor) {
                    document.getElementById('timeout').value = settings.executor.timeout || 30;
                }
                
                if (settings.memory) {
                    document.getElementById('memoryEnabled').value = settings.memory.enabled ? 'true' : 'false';
                }
            } catch (e) {
                console.error('Failed to fetch settings:', e);
            }
        }
        
        async function saveSettings() {
            const settings = {
                llm: {
                    provider: document.getElementById('llmProvider').value,
                    model: document.getElementById('llmModel').value,
                    base_url: document.getElementById('llmBaseUrl').value
                },
                strategy: {
                    max_iterations: parseInt(document.getElementById('maxIterations').value),
                    default: document.getElementById('strategy').value
                },
                executor: {
                    timeout: parseInt(document.getElementById('timeout').value)
                },
                memory: {
                    enabled: document.getElementById('memoryEnabled').value === 'true'
                }
            };
            
            try {
                await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(settings)
                });
                closeSettings();
            } catch (e) {
                console.error('Failed to save settings:', e);
            }
        }
        
        function openSettings() {
            document.getElementById('settingsPanel').classList.add('open');
            document.getElementById('settingsOverlay').classList.add('open');
        }
        
        function closeSettings() {
            document.getElementById('settingsPanel').classList.remove('open');
            document.getElementById('settingsOverlay').classList.remove('open');
        }
        
        document.getElementById('logs').addEventListener('scroll', function() {
            if (this.scrollTop < 50) {
                autoScroll = false;
            } else {
                autoScroll = true;
            }
        });
        
        fetchLogs();
        
        // Auto-refresh logs every 5 seconds
        setInterval(() => {
            if (currentTab === 'all') fetchLogs();
            else if (currentTab === 'network') fetchNetworkLogs();
            else if (currentTab === 'nn') fetchNnLogs();
            else if (currentTab === 'debug') fetchDebugLogs();
            else if (currentTab === 'ide') fetchIdeErrors();
        }, 5000);
    </script>
</body>
</html>
'''
