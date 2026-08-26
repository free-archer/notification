"""CLI-валидатор для Pi-скилла: атомарное обновление файла расписания.

Читает строки из stdin (по одной на событие) и дописывает их в файл,
не создавая точных дубликатов по тройке «дата, время, название».
Существующие строки сохраняются как есть. Запись атомарная.
"""
from __future__ import annotations

import os
import sys
import tempfile

from .parser import parse_line, parse_text


def _atomic_write(path: str, content: str):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".events.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(text_lines: list[str], path: str) -> str:
    existing_text = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            existing_text = f.read()

    res = parse_text(existing_text)
    keys = {e.key for e in res.events}
    # Существующие строки сохраняем как есть (включая комментарии).
    existing_lines = existing_text.splitlines()

    added: list[str] = []
    skipped: list[str] = []
    bad: list[tuple[str, str]] = []
    # Комментарии из входных данных сохраняем как есть (полезная разметка),
    # пустые строки игнорируем, чтобы не плодить мусор.
    preserved_comments: list[str] = []

    for raw in text_lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            preserved_comments.append(raw)
            continue
        try:
            ev = parse_line(line)
        except ValueError as e:
            bad.append((raw, str(e)))
            continue
        if ev.key in keys:
            skipped.append(raw)
            continue
        keys.add(ev.key)
        added.append(line)

    if added or preserved_comments:
        merged = "\n".join(existing_lines + preserved_comments + added)
        # Гарантируем завершающий перевод строки, чтобы информатор корректно
        # прочитал последнюю запись.
        merged = merged.rstrip("\n") + "\n"
        _atomic_write(path, merged)

    return _report(added, skipped, bad)


def _report(added, skipped, bad) -> str:
    out = [f"Добавлено: {len(added)}"]
    out += [f"  {line}" for line in added]
    if skipped:
        out.append(f"Пропущено (дубликат): {len(skipped)}")
    if bad:
        out.append(f"Ошибки: {len(bad)}")
        out += [f"  {raw!r}: {msg}" for raw, msg in bad]
    return "\n".join(out)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv
    path = os.environ.get(
        "MEETING_INFORMER_EVENTS",
        os.path.expanduser("~/.local/share/meeting-informer/events.txt"),
    )
    lines = [l for l in sys.stdin.read().splitlines()]
    if not lines:
        print("Нет входных строк")
        return 0
    print(update(lines, path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
