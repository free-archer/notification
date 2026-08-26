"""Разбор файла расписания format 'YYYY-MM-DD HH:MM | Название'."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Формат: 2026-08-26 14:30 | Планёрка отдела
LINE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\|\s*(.+?)\s*$")


@dataclass(frozen=True)
class Event:
    dt: datetime
    title: str

    @property
    def key(self) -> str:
        """Уникальный идентификатор события (дата, время, название)."""
        return f"{self.dt:%Y-%m-%d %H:%M}|{self.title.strip().casefold()}"


@dataclass
class ParseResult:
    events: list[Event] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)


def parse_line(line: str) -> Event:
    """Разобрать одну строку; при неверном формате кидает ValueError.

    Пустые строки и комментарии должны отсекаться на уровне parse_text,
    здесь ожидается значимая строка.
    """
    m = LINE_RE.match(line.strip())
    if not m:
        raise ValueError("неверный формат: ожидается 'YYYY-MM-DD HH:MM | Название'")
    dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
    title = m.group(3)
    if not title:
        raise ValueError("пустое название события")
    return Event(dt=dt, title=title)


def parse_text(text: str) -> ParseResult:
    """Разобрать весь текст файла.

    Пустые строки и строки с '#' игнорируются. Ошибка одной строки
    не прерывает чтение остальных. Дубликаты по тройке (дата, время,
    название) помечаются как ошибка, но не ломают процесс.
    """
    res = ParseResult()
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            ev = parse_line(line)
        except ValueError as e:
            res.errors.append((lineno, str(e)))
            continue
        if ev.key in seen:
            res.errors.append((lineno, f"дубликат события: {ev.title}"))
            continue
        seen.add(ev.key)
        res.events.append(ev)
    return res


def parse_file(path) -> ParseResult:
    try:
        with open(path, encoding="utf-8") as f:
            return parse_text(f.read())
    except FileNotFoundError:
        return ParseResult()
