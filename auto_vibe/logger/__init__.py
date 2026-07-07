"""
Structured logging for AutoVibe.

JSON logging with metrics: tokens, time, success/failure.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    """JSON log formatter for parsing."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if hasattr(record, "metrics"):
            log_entry["metrics"] = record.metrics
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(
    level: str = "INFO",
    log_file: str | None = None,
    json_format: bool = True,
) -> logging.Logger:
    """Configure logging and return root logger."""
    logger = logging.getLogger("auto_vibe")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    formatter = JSONFormatter() if json_format else logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (optional)
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

    return logger


class Metrics:
    """Session metrics collection: tokens, time, success/failure."""

    def __init__(self) -> None:
        self._start_time: float = time.time()
        self.total_prompt_tokens: int = 0
        self.total_completion_tokens: int = 0
        self.iteration_count: int = 0
        self.success_count: int = 0
        self.fail_count: int = 0
        self.iteration_times: list[float] = []
        self.errors: list[dict[str, Any]] = []

    def record_iteration(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        elapsed: float,
        success: bool,
    ) -> None:
        self.iteration_count += 1
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.iteration_times.append(elapsed)
        if success:
            self.success_count += 1
        else:
            self.fail_count += 1

    def record_error(self, error: str, iteration: int, context: str | None = None) -> None:
        self.errors.append({
            "iteration": iteration,
            "error": error,
            "context": context,
        })

    def summary(self) -> dict[str, Any]:
        total_tokens = self.total_prompt_tokens + self.total_completion_tokens
        total_time = sum(self.iteration_times)
        return {
            "session_duration_seconds": round(time.time() - self._start_time, 2),
            "total_tokens": total_tokens,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "iterations": self.iteration_count,
            "successes": self.success_count,
            "failures": self.fail_count,
            "avg_iteration_time": round(
                sum(self.iteration_times) / max(len(self.iteration_times), 1), 2
            ),
            "total_iteration_time": round(total_time, 2),
            "errors": self.errors,
        }

    def reset(self) -> None:
        self.__init__()


# Global metrics instance
_metrics: Metrics | None = None


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def reset_metrics() -> None:
    global _metrics
    _metrics = None


__all__ = [
    "JSONFormatter",
    "Metrics",
    "get_metrics",
    "reset_metrics",
    "setup_logging",
]
