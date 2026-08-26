"""Точка входа: python -m meeting_informer."""
from __future__ import annotations

import argparse
import logging
import os
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from .app import InformerApp


def _default_events_path() -> str:
    env = os.environ.get("MEETING_INFORMER_EVENTS")
    if env:
        return env
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "meeting-informer", "events.txt")


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    parser = argparse.ArgumentParser(prog="meeting-informer")
    parser.add_argument("--events", default=_default_events_path())
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv[1:])

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    os.makedirs(os.path.dirname(args.events), exist_ok=True)
    if not os.path.exists(args.events):
        _create_template(args.events)

    InformerApp(args.events)
    Gtk.main()
    return 0


def _create_template(path: str):
    header = (
        "# Расписание встреч. Формат: YYYY-MM-DD HH:MM | Название\n"
        "# Каждая встреча напомнит за 15 мин, 5 мин, 1 мин и в момент начала.\n\n"
        "2026-08-26 09:00 | Пример встречи\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
    except OSError as e:
        print(f"Не удалось создать {path}: {e}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
