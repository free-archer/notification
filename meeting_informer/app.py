"""GTK-приложение информатора: основной цикл, окна напоминаний."""
from __future__ import annotations

import logging
import os
from datetime import datetime

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk

from .parser import Event, parse_file
from .scheduler import Reminder, due_reminders
from .sound import SoundPlayer

TICK_SEC = 1.0
LOG = logging.getLogger("meeting_informer")

# Цвета подписи этапа напоминания по коду стадии.
# 15 минут — зелёный, 5 минут — синий, 1 минута — красный, начало — красный жирный.
STAGE_STYLE = {
    "-15m": "#2e7d32",
    "-5m": "#1565c0",
    "-1m": "#c62828",
    "start": "#c62828",
}


class ReminderWindow(Gtk.Window):
    """Обязательное окно напоминания. Остаётся поверх остальных окон,
    не закрывается автоматически, звучит до подтверждения."""

    def __init__(self, reminder: Reminder, sound: SoundPlayer):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self._sound = sound

        self.set_title("Напоминание о встрече")
        self.set_default_size(420, 180)
        self.set_resizable(True)
        self.set_keep_above(True)
        self.set_modal(False)
        self.set_skip_taskbar_hint(False)
        # Заявляем окно как уведомление, чтобы менеджер окон не прятал его.
        self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
        self.set_urgency_hint(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(18)
        box.set_margin_bottom(18)
        box.set_margin_start(18)
        box.set_margin_end(18)
        self.add(box)

        stage_label = Gtk.Label()
        stage_label.set_halign(Gtk.Align.START)
        color = STAGE_STYLE.get(reminder.stage, "#000000")
        if reminder.stage == "start":
            stage_label.set_markup(
                f"<b><span foreground='{color}'>{reminder.label}</span></b>"
            )
        else:
            stage_label.set_markup(
                f"<span foreground='{color}'>{reminder.label}</span>"
            )
        box.pack_start(stage_label, False, False, 0)

        time_label = Gtk.Label()
        time_label.set_markup(
            f"<span size='large'>{reminder.event.dt:%H:%M}  "
            f"{reminder.event.dt:%d.%m.%Y}</span>"
        )
        time_label.set_halign(Gtk.Align.START)
        box.pack_start(time_label, False, False, 0)

        title_label = Gtk.Label(label=reminder.event.title)
        title_label.set_halign(Gtk.Align.START)
        title_label.set_line_wrap(True)
        title_label.set_justify(Gtk.Justification.LEFT)
        box.pack_start(title_label, False, False, 0)

        button = Gtk.Button(label="Понятно")
        button.set_halign(Gtk.Align.END)
        button.connect("clicked", lambda *_: self.destroy())
        box.pack_start(button, False, False, 0)

        self.connect("destroy", self._on_destroy)
        self.connect("delete-event", lambda *_: self.destroy() or True)

        self._sound.start()
        self.show_all()
        self.present()

    def _on_destroy(self, *_):
        self._sound.stop()


class InformerApp:
    """Держит состояние и основной цикл проверки расписания."""

    def __init__(self, events_path: str, sound: SoundPlayer | None = None):
        self.events_path = events_path
        self.sound = sound or SoundPlayer()
        self.events: list[Event] = []
        self.mtime: float | None = None
        self.fired_keys: set[str] = set()
        GLib.timeout_add(int(TICK_SEC * 1000), self._tick)
        self._reload(force_init=True)

    def _reload(self, force_init: bool = False):
        try:
            mtime = os.path.getmtime(self.events_path)
        except OSError:
            mtime = None
        if not force_init and mtime == self.mtime:
            return
        self.mtime = mtime
        res = parse_file(self.events_path)
        self.events = res.events
        if force_init:
            LOG.info("Загружено событий: %d, ошибок: %d", len(self.events), len(res.errors))
        else:
            LOG.info("Файл обновлён: событий %d, ошибок %d", len(self.events), len(res.errors))
        for lineno, msg in res.errors:
            LOG.error("Строка %d: %s", lineno, msg)

    def _tick(self):
        try:
            self._reload()
            now = datetime.now()
            for rem in due_reminders(self.events, now, self.fired_keys):
                self._fire(rem)
        except Exception:
            LOG.exception("Ошибка в цикле проверки")
        return True  # продолжить таймер

    def _fire(self, rem: Reminder):
        self.fired_keys.add(rem.key)
        LOG.info("Напоминание: [%s] %s (%s)", rem.stage, rem.event.title, rem.event.dt)
        ReminderWindow(rem, self.sound)
