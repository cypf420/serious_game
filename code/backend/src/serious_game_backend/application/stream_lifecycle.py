from __future__ import annotations

from threading import Event, Lock
from time import monotonic
from typing import Callable


StreamCancelled = Callable[[], bool] | None
StreamCancelCallback = Callable[[], None]


class StreamCancellation:
    """Thread-safe cancellation plus callbacks bound to an exact attempt."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._callbacks: list[StreamCancelCallback] = []

    def is_set(self) -> bool:
        return self._event.is_set()

    def add_callback(self, callback: StreamCancelCallback) -> None:
        call_now = False
        with self._lock:
            if self._event.is_set():
                call_now = True
            else:
                self._callbacks.append(callback)
        if call_now:
            callback()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = tuple(self._callbacks)
            self._callbacks.clear()
        for callback in callbacks:
            callback()


def ensure_stream_open(cancelled: StreamCancelled) -> None:
    if cancelled is not None and cancelled():
        raise ConnectionAbortedError("NPC response stream disconnected")


def wait_for_stream_ack(
    acknowledged: Event,
    cancelled: StreamCancelled,
    *,
    timeout: float = 10.0,
) -> bool:
    deadline = monotonic() + timeout
    while True:
        ensure_stream_open(cancelled)
        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        if acknowledged.wait(min(0.05, remaining)):
            ensure_stream_open(cancelled)
            return True
