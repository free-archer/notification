"""Тесты разбора файла расписания."""
import unittest
from datetime import datetime

from meeting_informer.parser import Event, parse_line, parse_text


class ParseLineTest(unittest.TestCase):
    def test_valid_line(self):
        ev = parse_line("2026-08-26 14:30 | Планёрка отдела")
        self.assertEqual(ev.dt, datetime(2026, 8, 26, 14, 30))
        self.assertEqual(ev.title, "Планёрка отдела")

    def test_whitespace_padding(self):
        ev = parse_line("  2026-08-26 09:05 |  Встреча  ")
        self.assertEqual(ev.title, "Встреча")

    def test_invalid_format_raises(self):
        with self.assertRaises(ValueError):
            parse_line("не строка")
        with self.assertRaises(ValueError):
            parse_line("2026-08-26 | Встреча")
        with self.assertRaises(ValueError):
            parse_line("2026-13-40 99:99 | Встреча")

    def test_empty_title_raises(self):
        with self.assertRaises(ValueError):
            parse_line("2026-08-26 14:30 |")

    def test_key_casefold(self):
        a = parse_line("2026-08-26 14:30 | Встреча")
        b = parse_line("2026-08-26 14:30 | встреча")
        self.assertEqual(a.key, b.key)


class ParseTextTest(unittest.TestCase):
    def test_ignores_empty_and_comments(self):
        text = "# header\n\n2026-08-26 14:30 | A\n  \n2026-08-27 09:00 | B\n"
        res = parse_text(text)
        self.assertEqual(len(res.events), 2)
        self.assertEqual(res.errors, [])

    def test_error_does_not_break_loop(self):
        text = "2026-08-26 14:30 | A\nbad line\n2026-08-27 09:00 | B\n"
        res = parse_text(text)
        self.assertEqual(len(res.events), 2)
        self.assertEqual(len(res.errors), 1)
        self.assertEqual(res.errors[0][0], 2)  # номер строки

    def test_duplicate_flag(self):
        text = "2026-08-26 14:30 | Встреча\n2026-08-26 14:30 | встреча\n"
        res = parse_text(text)
        self.assertEqual(len(res.events), 1)
        self.assertEqual(len(res.errors), 1)
        self.assertIn("дубликат", res.errors[0][1])

    def test_trailing_empty_title_line_counts_as_error(self):
        text = "2026-08-26 14:30 | A\n2026-08-27 09:00 |\n"
        res = parse_text(text)
        self.assertEqual(len(res.events), 1)
        self.assertEqual(len(res.errors), 1)


if __name__ == "__main__":
    unittest.main()
