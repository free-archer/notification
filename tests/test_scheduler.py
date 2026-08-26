"""Тесты отбора напоминаний по времени."""
import unittest
from datetime import datetime, timedelta

from meeting_informer.parser import Event
from meeting_informer.scheduler import MAX_AGE, compute_reminders, due_reminders


def ev(y, m, d, hh, mm, title="Встреча"):
    return Event(dt=datetime(y, m, d, hh, mm), title=title)


class ComputeRemindersTest(unittest.TestCase):
    def test_four_stages(self):
        e = ev(2026, 8, 26, 14, 30)
        rems = list(compute_reminders(e))
        self.assertEqual(len(rems), 4)
        stages = [r.stage for r in rems]
        self.assertEqual(stages, ["-15m", "-5m", "-1m", "start"])
        self.assertEqual(rems[0].trigger, datetime(2026, 8, 26, 14, 15))
        self.assertEqual(rems[3].trigger, datetime(2026, 8, 26, 14, 30))

    def test_keys_unique_per_stage(self):
        e = ev(2026, 8, 26, 14, 30)
        keys = [r.key for r in compute_reminders(e)]
        self.assertEqual(len(keys), len(set(keys)))


class DueRemindersTest(unittest.TestCase):
    def test_nothing_due_far_before(self):
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 11, 0)
        self.assertEqual(due_reminders([e], now, set()), [])

    def test_15min_due_at_exact_boundary(self):
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 15)
        due = due_reminders([e], now, set())
        self.assertEqual([r.stage for r in due], ["-15m"])

    def test_only_15min_due_when_within_minutes(self):
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 16, 30)
        due = due_reminders([e], now, set())
        self.assertEqual([r.stage for r in due], ["-15m"])

    def test_start_due_at_start(self):
        e = ev(2026, 8, 26, 14, 30)
        # При непрерывной работе -1m уже сработал на 14:29, поэтому его key
        # в fired_keys. В 14:30 остаётся только "start".
        fired = {list(compute_reminders(e))[2].key}  # -1m
        now = datetime(2026, 8, 26, 14, 30)
        due = due_reminders([e], now, fired)
        self.assertEqual([r.stage for r in due], ["start"])

    def test_past_event_not_due(self):
        # Прошло более MAX_AGE — событие в прошлом, стадии не выстреливают.
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 15, 0)
        self.assertEqual(due_reminders([e], now, set()), [])

    def test_no_cascade_on_late_launch(self):
        # Запуск за секунду до начала: срабатывает только -1m.
        # Стадии -15m и -5m уже "остарели" (больше MAX_AGE), а start ещё
        # не наступил (его триггер = 14:30, а сейчас 14:29:59).
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 29, 59)
        stages = [r.stage for r in due_reminders([e], now, set())]
        self.assertEqual(stages, ["-1m"])

    def test_all_but_overdue_on_start_fresh(self):
        # Чистый запуск ровно в момент начала с пустым fired: "созрели"
        # только недавние выдержки (-1m и start), без каскада -15m/-5m.
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 30)
        stages = [r.stage for r in due_reminders([e], now, set())]
        self.assertIn("start", stages)
        self.assertIn("-1m", stages)
        self.assertNotIn("-15m", stages)
        self.assertNotIn("-5m", stages)

    def test_fired_key_suppressed(self):
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 15)
        due = due_reminders([e], now, set())
        key = due[0].key
        self.assertEqual(due_reminders([e], now, {key}), [])

    def test_old_trigger_within_max_age_but_just_after(self):
        e = ev(2026, 8, 26, 14, 30)
        now = datetime(2026, 8, 26, 14, 15) + MAX_AGE
        due = due_reminders([e], now, set())
        self.assertEqual([r.stage for r in due], ["-15m"])


if __name__ == "__main__":
    unittest.main()
