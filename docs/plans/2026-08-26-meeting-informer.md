# Информатор рабочих встреч — план реализации

> **Цель:** Собрать локальный Linux-информатор встреч с обязательными GTK-окнами и повторяемым системным звуком (сигналы за 15 мин, 5 мин, 1 мин и в момент начала) и Pi-скилл для загрузки расписания по скриншоту.

**Архитектура:** Фоновый Python-процесс на GTK читает `events.txt`, вычисляет четыре точки срабатывания на событие и показывает поверх остальных окон обязательный диалог со звуком до подтверждения. Файл перечитывается по mtime без перезапуска. Запуск — пользовательский systemd unit при входе в локальную GNOME/Wayland-сессию. Pi-скилл обновляет файл через CLI-валидатор с атомарной записью.

**Стек:** Python 3.12, PyGObject (GTK3), `paplay`, systemd `--user`, `unittest` (без pytest).

---

## Структура проекта

```
/home/archer/projects/notification/
├── meeting_informer/
│   ├── __init__.py
│   ├── __main__.py          # entry: python -m meeting_informer
│   ├── parser.py            # Event + разбор events.txt
│   ├── scheduler.py         # точки срабатывания / due-напоминания
│   ├── sound.py             # повторяемый звук через paplay
│   ├── app.py               # GTK main-loop + окна
│   └── updater.py           # CLI-валидатор для скилла (атомарная запись)
├── bin/
│   ├── meeting-informer          # лаунчер (подхват окружения сессии)
│   └── meeting-informer-update   # CLI обновления (симлинк на updater)
├── systemd/meeting-informer.service
├── skills/meeting-informer/SKILL.md
├── tests/
│   ├── test_parser.py
│   ├── test_scheduler.py
│   └── test_updater.py
└── docs/plans/
```

### Устанавливаемые артефакты
- `~/bin/meeting-informer`, `~/bin/meeting-informer-update` — исполняемые (source в проекте).
- `~/.config/systemd/user/meeting-informer.service` — unit.
- `~/.local/share/meeting-informer/events.txt` — расписание.
- `~/.agents/skills/meeting-informer/SKILL.md` — скилл (автозагрузка Pi).

---

## Task 1: parser.py

**Files:** Create `meeting_informer/parser.py`, `tests/test_parser.py`

Формат строки: `YYYY-MM-DD HH:MM | Название`. Пустые строки и `#` игнорируются. Ошибка строки не прерывает чтение.

```python
# meeting_informer/parser.py
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime

LINE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s*\|\s*(.+?)\s*$")

@dataclass(frozen=True)
class Event:
    dt: datetime
    title: str
    @property
    def key(self) -> str:
        return f"{self.dt:%Y-%m-%d %H:%M}|{self.title.strip().casefold()}"

@dataclass
class ParseResult:
    events: list[Event] = field(default_factory=list)
    errors: list[tuple[int, str]] = field(default_factory=list)

def parse_line(line: str) -> Event:
    m = LINE_RE.match(line.strip())
    if not m:
        raise ValueError("неверный формат: ожидается 'YYYY-MM-DD HH:MM | Название'")
    dt = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
    title = m.group(3)
    if not title:
        raise ValueError("пустое название события")
    return Event(dt=dt, title=title)

def parse_text(text: str) -> ParseResult:
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
```

### Тест (unittest)
Проверить: валидная строка; игнор `#` и пустых; сбор ошибок с номером строки; дубликат по тройке; пустое название; заголовок с пробелами/`|`.

## Task 2: scheduler.py

**Files:** Create `meeting_informer/scheduler.py`, `tests/test_scheduler.py`

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from .parser import Event

STAGES = [("-15m","за 15 минут",timedelta(minutes=15)),
          ("-5m","за 5 минут",timedelta(minutes=5)),
          ("-1m","за 1 минуту",timedelta(minutes=1)),
          ("start","начало встречи",timedelta(0))]
MAX_AGE = timedelta(seconds=90)

@dataclass(frozen=True)
class Reminder:
    stage: str; label: str; trigger: datetime; event: Event
    @property
    def key(self) -> str:
        return f"{self.event.key}|{self.stage}"

def compute_reminders(event: Event):
    for stage, label, delta in STAGES:
        yield Reminder(stage, label, event.dt - delta, event)

def due_reminders(events, now, fired_keys):
    due = []
    for ev in events:
        for rem in compute_reminders(ev):
            if rem.key in fired_keys:
                continue
            if rem.trigger <= now and (now - rem.trigger) <= MAX_AGE:
                due.append(rem)
    due.sort(key=lambda r: r.trigger)
    return due
```

**Тест:** триггеры для всех стадий; due при `trigger<=now<=trigger+MAX_AGE`; старые (>90с) и будущие триггеры не срабатывают; прошлые события не дают напоминаний; fired-ключ исключает дубль.

## Task 3: sound.py

**Files:** Create `meeting_informer/sound.py`

```python
from __future__ import annotations
import os, shutil, subprocess
from gi.repository import GLib

DEFAULT_SOUND = "/usr/share/sounds/freedesktop/stereo/bell.oga"
REPEAT_SEC = 3

class SoundPlayer:
    def __init__(self, sound_file=None):
        self.sound_file = (sound_file or os.environ.get("MEETING_INFORMER_SOUND") or DEFAULT_SOUND)
        if not shutil.which("paplay"):
            self.play = self._noop
        self._timers: list[int] = []
    def _noop(self): pass
    def _emit(self):
        subprocess.Popen(["paplay", self.sound_file],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    def start(self):
        self._emit()
        t = GLib.timeout_add(REPEAT_SEC*1000, self._emit)
        self._timers.append(t)
    def stop(self):
        for t in self._timers:
            GLib.source_remove(t)
        self._timers.clear()
```

## Task 4: app.py (GTK)

**Files:** Create `meeting_informer/app.py`, `meeting_informer/__main__.py`

- `InformerApp` — держит путь к файлу, mtime, `fired_keys`, set активных окон.
- `GLib.timeout_add(1000, tick)`; tick перечитывает файл по mtime, вызывает `due_reminders`, для каждого due создаёт окно.
- `ReminderWindow` — `Gtk.Window`, `set_keep_above(True)`, `set_title`, крупная метка времени/стадии, название, кнопка «Понятно»; `delete-event` закрывает (destroy останавливает звук через сигнал `destroy`).
- Звук: `SoundPlayer.start()` при создании окна, `stop()` при уничтожении.

`__main__.py`: парсит аргумент `--events PATH`, дефолт `~/.local/share/meeting-informer/events.txt`; создаёт `InformerApp`, `Gtk.main()`.

## Task 5: updater.py (CLI)

**Files:** Create `meeting_informer/updater.py`, `tests/test_updater.py`

Вход: строки из stdin (по одной на событие) или пути к файлам. Атомарная запись.

```python
from __future__ import annotations
import os, sys, tempfile
from .parser import Event, parse_line, parse_text

def update(text_lines, path) -> str:
    existing_text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing_text = f.read()
    res = parse_text(existing_text)
    keys = {e.key for e in res.events}
    existing_lines = existing_text.splitlines()
    added, skipped, bad = [], [], []
    for raw in text_lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            skipped.append(raw); continue
        try:
            ev = parse_line(line)
        except ValueError as e:
            bad.append((raw, str(e))); continue
        if ev.key in keys:
            skipped.append(raw); continue
        keys.add(ev.key)
        existing_lines.append(line)
        added.append(line)
    if added:
        _atomic_write(path, "\n".join(existing_lines) + "\n")
    return _report(added, skipped, bad)

def _atomic_write(path, content):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".events.", suffix=".tmp")
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)

def _report(added, skipped, bad):
    out = [f"Добавлено: {len(added)}"]
    out += [f"  {l}" for l in added]
    if skipped:
        out.append(f"Пропущено (дубликат): {len(skipped)}")
    if bad:
        out.append(f"Ошибки: {len(bad)}")
        out += [f"  {raw!r}: {msg}" for raw,msg in bad]
    return "\n".join(out)

def main(argv=None):
    argv = argv or sys.argv
    path = os.environ.get("MEETING_INFORMER_EVENTS",
                          os.path.expanduser("~/.local/share/meeting-informer/events.txt"))
    lines = [l for l in sys.stdin.read().splitlines()]
    if not lines:
        print("Нет входных строк"); return 0
    print(update(lines, path))
    return 0
```

**Тест:** добавление; отсутствие дублей при повторном вызове; атомарность (нет `.tmp`-остатков); ошибки не ломают файл; сохранение существующих строк.

## Task 6: лаунчер (bin/meeting-informer)

**Files:** Create `bin/meeting-informer`

Подхватывает окружение графической сессии, если `systemd --user` его не передал (WAYLAND_DISPLAY/DISPLAY/DBUS_SESSION_BUS_ADDRESS/XDG_RUNTIME_DIR — берём из `/proc/<pid>/environ` процесса `gnome-shell`/`gnome-session`), затем `exec python3 -m meeting_informer`.

## Task 7: systemd unit

**Files:** Create `systemd/meeting-informer.service`

```ini
[Unit]
Description=Meeting informer
After=graphical-session.target

[Service]
Type=simple
ExecStart=/home/archer/bin/meeting-informer
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
```

## Task 8: Pi-скилл

**Files:** Create `skills/meeting-informer/SKILL.md`, установить в `~/.agents/skills/meeting-informer/`

Скилл: принимает скриншот календаря, извлекает разовые встречи, формирует `YYYY-MM-DD HH:MM | Название`, прогоняет через `meeting-informer-update` (stdin), показывает отчёт. Запрещено угадывать неоднозначные даты/время — помечать ошибкой.

## Task 9: установка и проверка

- `chmod +x bin/*`, скопировать/симлинки в `~/bin`, создать unit в `~/.config/systemd/user/`, `systemctl --user daemon-reload`.
- Создать тестовое событие на +1 мин, запустить вручную, проверить окно+звук.
- Прослушать звук через `paplay`.
- Скилл: положить в `~/.agents/skills/meeting-informer/`.
- Закоммитить.

---

## Проверка (критерии приёмки)

`python -m unittest discover -s tests` — зелёный.
Лаунчер запускается и показывает окно через ~1с после срабатывания.
Звук повторяется до нажатия «Понятно».
Перечитывание файла без перезапуска (добавить строку — подхватится).
Скилл обновляет файл без дублей и атомарно.
