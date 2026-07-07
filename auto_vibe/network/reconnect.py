"""Reconnection on connection loss."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Any


logger = logging.getLogger(__name__)


class ReconnectManager:
    """
    Reconnection manager. Automatically reconnects
    on connection loss with exponential backoff.
    """

    def __init__(
        self,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.current_retry = 0

    async def connect(
        self,
        connect_func: Callable[[], Any],
        on_disconnect: Callable[[Exception], None] | None = None,
    ) -> Any:
        """
        Connects with automatic reconnection.

        Args:
            connect_func: Function to establish connection
            on_disconnect: Callback on disconnect

        Returns:
            Established connection
        """
        while self.current_retry < self.max_retries:
            try:
                logger.info(f"Connection attempt {self.current_retry + 1}/{self.max_retries}")
                connection = await connect_func()
                self.current_retry = 0  # Reset counter on success
                return connection

            except Exception as e:
                self.current_retry += 1
                logger.warning(f"Connection error: {e}")

                if on_disconnect:
                    on_disconnect(e)

                if self.current_retry >= self.max_retries:
                    logger.error("Maximum number of retries exceeded")
                    raise

                # Calculate delay with exponential backoff
                delay = min(
                    self.base_delay * (self.exponential_base ** (self.current_retry - 1)),
                    self.max_delay
                )
                logger.info(f"Retrying in {delay:.1f} sec...")
                await asyncio.sleep(delay)

        raise ConnectionError("Failed to establish connection")

    def reset(self) -> None:
        """Resets retry counter."""
        self.current_retry = 0


class ConnectionMonitor:
    """
    Connection monitoring. Periodically checks
    availability and notifies on disconnects.
    """

    def __init__(
        self,
        check_interval: float = 30.0,
        on_disconnect: Callable[[], None] | None = None,
    ):
        self.check_interval = check_interval
        self.on_disconnect = on_disconnect
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Starts monitoring."""
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Connection monitoring started")

    async def stop(self) -> None:
        """Stops monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Connection monitoring stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await asyncio.sleep(self.check_interval)
                # Connection check can be added here
                # For example, pinging the server
                logger.debug("Checking connection...")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
                if self.on_disconnect:
                    self.on_disconnect()
