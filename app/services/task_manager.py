"""Tracks background run tasks so they can be awaited (tests) and cancelled on shutdown."""

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class TaskManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def spawn(self, key: str, coro: Coroutine[Any, Any, None]) -> None:
        if self.is_running(key):
            coro.close()
            raise RuntimeError(f"A task for {key} is already running.")
        task = asyncio.create_task(coro, name=f"run-{key}")
        self._tasks[key] = task
        task.add_done_callback(lambda t: self._finished(key, t))

    def _finished(self, key: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(key) is task:
            self._tasks.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background task %s crashed", key, exc_info=task.exception())

    def is_running(self, key: str) -> bool:
        task = self._tasks.get(key)
        return task is not None and not task.done()

    async def wait(self, key: str) -> None:
        while (task := self._tasks.get(key)) is not None:
            await asyncio.gather(task, return_exceptions=True)

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
