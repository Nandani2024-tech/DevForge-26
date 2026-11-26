"""Cross-platform process-tree peak RSS measurement using psutil."""
from __future__ import annotations

import threading
from types import TracebackType

import psutil

from wards.config import RSS_SAMPLE_INTERVAL_SEC


def _sample_tree_rss_bytes(proc: psutil.Process) -> int:
    """Sum RSS of the current process and all recursive children. O(processes)."""
    total = 0
    try:
        total += proc.memory_info().rss
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0
    try:
        children = proc.children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        children = []
    for child in children:
        try:
            total += child.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


class MemorySampler:
    """Background daemon sampler for cross-platform process-tree peak RSS."""

    def __init__(self, interval_sec: float = RSS_SAMPLE_INTERVAL_SEC) -> None:
        self._interval_sec = interval_sec
        self._proc = psutil.Process()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._peak_bytes = 0
        self._thread: threading.Thread | None = None

    def _record_sample(self) -> None:
        rss = _sample_tree_rss_bytes(self._proc)
        with self._lock:
            if rss > self._peak_bytes:
                self._peak_bytes = rss

    def _run(self) -> None:
        while not self._stop.wait(self._interval_sec):
            self._record_sample()

    def start(self) -> MemorySampler:
        self._record_sample()
        self._thread = threading.Thread(target=self._run, name="rss-sampler", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> float:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        self._record_sample()
        return self.peak_rss_mb

    @property
    def peak_rss_mb(self) -> float:
        with self._lock:
            return round(self._peak_bytes / (1024 * 1024), 2)

    def __enter__(self) -> MemorySampler:
        return self.start()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()
