"""Повторяемый системный звук до подтверждения напоминания."""
from __future__ import annotations

import os
import shutil
import subprocess

from gi.repository import GLib

DEFAULT_SOUND = "/usr/share/sounds/freedesktop/stereo/bell.oga"
REPEAT_SEC = 3


class SoundPlayer:
    """Проигрывает системный звук в цикле, пока не вызван stop()."""

    def __init__(self, sound_file: str | None = None):
        self.sound_file = (
            sound_file or os.environ.get("MEETING_INFORMER_SOUND") or DEFAULT_SOUND
        )
        self._timers: list[int] = []
        # Если paplay недоступен, превращаем проигрывание в no-op.
        self._enabled = shutil.which("paplay") is not None

    def _emit(self):
        if self._enabled:
            subprocess.Popen(
                ["paplay", self.sound_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True

    def start(self):
        """Запустить цикл звука. Сначала играет сразу, затем повторяется."""
        self._emit()
        t = GLib.timeout_add(REPEAT_SEC * 1000, self._emit)
        self._timers.append(t)

    def stop(self):
        """Остановить цикл звука."""
        for t in self._timers:
            GLib.source_remove(t)
        self._timers.clear()
