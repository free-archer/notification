"""Тесты атомарного обновления файла расписания (CLI-валидатор)."""
import os
import tempfile
import unittest

from meeting_informer.updater import _atomic_write, update


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "events.txt")

    def tearDown(self):
        for f in os.listdir(self.dir):
            os.unlink(os.path.join(self.dir, f))
        os.rmdir(self.dir)

    def test_adds_event_to_new_file(self):
        report = update(["2026-08-26 14:30 | Встреча A"], self.path)
        self.assertIn("Добавлено: 1", report)
        with open(self.path, encoding="utf-8") as f:
            self.assertIn("2026-08-26 14:30 | Встреча A", f.read())

    def test_no_duplicate_on_second_run(self):
        update(["2026-08-26 14:30 | Встреча A"], self.path)
        report = update(["2026-08-26 14:30 | Встреча A"], self.path)
        self.assertIn("Добавлено: 0", report)
        self.assertIn("Пропущено (дубликат)", report)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read().count("Встреча A"), 1)

    def test_preserves_existing_lines_and_comments(self):
        update(["2026-08-26 14:30 | A"], self.path)
        update(["# важный комментарий", "", "2026-08-27 09:00 | B"], self.path)
        with open(self.path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# важный комментарий", content)
        self.assertIn("2026-08-26 14:30 | A", content)
        self.assertIn("2026-08-27 09:00 | B", content)

    def test_atomic_no_temp_leftover(self):
        update(["2026-08-26 14:30 | A"], self.path)
        leftovers = [f for f in os.listdir(self.dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_invalid_input_does_not_corrupt(self):
        update(["2026-08-26 14:30 | A"], self.path)
        with open(self.path, encoding="utf-8") as f:
            before = f.read()
        report = update(["bad line", "2026-08-26 14:30 | A"], self.path)
        self.assertIn("Ошибки: 1", report)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(f.read(), before)


class AtomicWriteTest(unittest.TestCase):
    def test_replaces_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "f.txt")
            _atomic_write(p, "hello")
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), "hello")
            _atomic_write(p, "world")
            with open(p, encoding="utf-8") as f:
                self.assertEqual(f.read(), "world")


if __name__ == "__main__":
    unittest.main()
