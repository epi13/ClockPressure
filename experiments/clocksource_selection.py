"""Reversibly select a Linux timekeeping clocksource for a scoped experiment."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class ClocksourceSelection:
    """Select one available clocksource and restore the previous source on exit."""

    def __init__(
        self,
        requested: str,
        *,
        clocksource_root: Path = Path("/sys/devices/system/clocksource/clocksource0"),
    ):
        self.requested = requested
        self.current_path = clocksource_root / "current_clocksource"
        self.available_path = clocksource_root / "available_clocksource"
        self.before: str | None = None
        self.active: str | None = None
        self.after: str | None = None
        self.restored = False

    @property
    def available(self) -> list[str]:
        try:
            return self.available_path.read_text().split()
        except OSError as exc:
            raise RuntimeError(f"cannot read available clocksources at {self.available_path}: {exc}") from exc

    @property
    def record(self) -> dict[str, Any]:
        return {
            "sysfs_current_path": str(self.current_path),
            "before": self.before,
            "requested": self.requested,
            "active": self.active,
            "after_restore": self.after,
            "restored": self.restored,
        }

    def _current(self) -> str:
        try:
            value = self.current_path.read_text().strip()
        except OSError as exc:
            raise RuntimeError(f"cannot read current clocksource at {self.current_path}: {exc}") from exc
        if not value:
            raise RuntimeError(f"current clocksource is empty at {self.current_path}")
        return value

    def _write(self, source: str) -> None:
        try:
            self.current_path.write_text(f"{source}\n")
        except OSError as exc:
            raise RuntimeError(f"cannot select clocksource {source!r} at {self.current_path}: {exc}") from exc

    def __enter__(self) -> "ClocksourceSelection":
        self.before = self._current()
        if self.requested not in self.available:
            raise ValueError(
                f"clocksource {self.requested!r} is unavailable; choices are {self.available}"
            )
        try:
            if self.before != self.requested:
                self._write(self.requested)
            self.active = self._current()
            if self.active != self.requested:
                raise RuntimeError(
                    f"requested clocksource {self.requested!r}, kernel selected {self.active!r}"
                )
        except Exception:
            self._restore()
            raise
        return self

    def _restore(self) -> None:
        if self.before is None:
            return
        try:
            current = self._current()
            if current != self.before:
                self._write(self.before)
            self.after = self._current()
            self.restored = self.after == self.before
        except Exception as exc:
            raise RuntimeError(
                f"failed to restore clocksource {self.before!r} at {self.current_path}: {exc}"
            ) from exc
        if not self.restored:
            raise RuntimeError(
                f"clocksource restoration mismatch: expected {self.before!r}, observed {self.after!r}"
            )

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        self._restore()
        return False
