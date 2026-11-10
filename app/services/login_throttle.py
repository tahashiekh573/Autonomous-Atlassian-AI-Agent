"""In-process brute-force protection for the login endpoint (per email, sliding window)."""

import time
from collections import defaultdict, deque

from app.core.exceptions import AppError


class TooManyAttemptsError(AppError):
    status_code = 429
    code = "too_many_attempts"


class LoginThrottle:
    def __init__(self, max_failures: int = 10, window_seconds: float = 900) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str) -> deque[float]:
        entries = self._failures[key]
        cutoff = time.monotonic() - self._window
        while entries and entries[0] < cutoff:
            entries.popleft()
        return entries

    def check(self, email: str) -> None:
        if len(self._prune(email.strip().lower())) >= self._max:
            raise TooManyAttemptsError("Too many failed sign-in attempts; try again later.")

    def failed(self, email: str) -> None:
        self._prune(email.strip().lower()).append(time.monotonic())

    def succeeded(self, email: str) -> None:
        self._failures.pop(email.strip().lower(), None)
