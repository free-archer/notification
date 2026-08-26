"""Точки срабатывания и отбор напоминаний, готовых к показу."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .parser import Event

# (stage, label, сдвиг назад от начала события)
STAGES = [
    ("-15m", "за 15 минут", timedelta(minutes=15)),
    ("-5m", "за 5 минут", timedelta(minutes=5)),
    ("-1m", "за 1 минуту", timedelta(minutes=1)),
    ("start", "начало встречи", timedelta(0)),
]

# Напоминание показываем, только если его точка срабатывания наступила
# недавно (в пределах этого окна). Это отсекает события из далёкого прошлого
# и не даёт каскадно выстрелить всем стадиям при позднем запуске.
MAX_AGE = timedelta(seconds=90)


@dataclass(frozen=True)
class Reminder:
    stage: str
    label: str
    trigger: datetime
    event: Event

    @property
    def key(self) -> str:
        return f"{self.event.key}|{self.stage}"


def compute_reminders(event: Event):
    """Все четыре точки срабатывания для одного события."""
    for stage, label, delta in STAGES:
        yield Reminder(stage=stage, label=label, trigger=event.dt - delta, event=event)


def due_reminders(events, now: datetime, fired_keys: set[str]):
    """Список напоминаний, которые нужно показать в момент ``now``.

    Напоминание считается «созревшим», если его точка срабатывания
    ``trigger`` уже наступила (``trigger <= now``) и прошло не более
    ``MAX_AGE`` с момента срабатывания, и оно ещё не было показано
    (не входит в ``fired_keys``).
    """
    due: list[Reminder] = []
    for ev in events:
        for rem in compute_reminders(ev):
            if rem.key in fired_keys:
                continue
            if rem.trigger <= now and (now - rem.trigger) <= MAX_AGE:
                due.append(rem)
    due.sort(key=lambda r: r.trigger)
    return due
