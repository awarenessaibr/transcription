"""In-memory fake for ``AcousticProbePort``."""
from __future__ import annotations


class FakeAcousticProbe:
    """Returns canned responses keyed by ``(path, start, end)``.

    Raises ``KeyError`` for any unconfigured probe so tests stay explicit.
    """

    def __init__(
        self,
        info: dict | None = None,
        windows: dict | None = None,
        extracts: dict | None = None,
    ) -> None:
        self._info = info or {}
        self._windows = windows or {}
        self._extracts = extracts or {}
        self.calls_audio_info: list[str] = []
        self.calls_window_stats: list[tuple[str, float, float]] = []
        self.calls_extract: list[tuple[str, float, float, str]] = []

    def audio_info(self, path: str) -> dict:
        self.calls_audio_info.append(path)
        if path in self._info:
            return dict(self._info[path])
        raise KeyError(f"FakeAcousticProbe: no audio_info for {path!r}")

    def window_stats(self, path: str, start: float, end: float) -> dict:
        self.calls_window_stats.append((path, start, end))
        key = (path, round(start, 3), round(end, 3))
        if key in self._windows:
            return dict(self._windows[key])
        # Fallback: any-key match for tests that don't care about exact times.
        if path in self._windows:
            return dict(self._windows[path])
        raise KeyError(f"FakeAcousticProbe: no window_stats for {key}")

    def extract_window(
        self, src_path: str, start: float, end: float, dst_path: str
    ) -> str:
        self.calls_extract.append((src_path, start, end, dst_path))
        return self._extracts.get(src_path, dst_path)
