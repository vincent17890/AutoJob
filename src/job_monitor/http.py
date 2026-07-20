from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout_seconds: float = 20.0,
        max_attempts: int = 3,
        backoff_seconds: float = 1.0,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "job-monitor/0.1"},
        )
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds
        self._sleeper = sleeper

    def get_json(self, url: str) -> Any:
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(url)
                if response.status_code in TRANSIENT_STATUS_CODES:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self._max_attempts:
                    break
                self._sleeper(self._backoff_seconds * (2 ** (attempt - 1)))

        if last_error is None:
            raise RuntimeError(f"failed to fetch {url}")
        raise last_error
