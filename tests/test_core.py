import unittest
from datetime import datetime

from cron_expression_kit import CronError, CronExpression


class ParseTests(unittest.TestCase):
    def test_parse_star(self):
        expr = CronExpression.parse("* * * * *")
        self.assertEqual(expr.minute, frozenset(range(60)))
        self.assertEqual(expr.hour, frozenset(range(24)))
        self.assertEqual(expr.day_of_month, frozenset(range(1, 32)))
        self.assertEqual(expr.month, frozenset(range(1, 13)))
        self.assertEqual(expr.day_of_week, frozenset(range(7)))

    def test_parse_list_and_range(self):
        expr = CronExpression.parse("0,30 9-17 * * 1-5")
        self.assertEqual(expr.minute, frozenset({0, 30}))
        self.assertEqual(expr.hour, frozenset(range(9, 18)))
        self.assertEqual(expr.day_of_week, frozenset({1, 2, 3, 4, 5}))

    def test_parse_step(self):
        expr = CronExpression.parse("*/15 */6 * * *")
        self.assertEqual(expr.minute, frozenset({0, 15, 30, 45}))
        self.assertEqual(expr.hour, frozenset({0, 6, 12, 18}))

    def test_parse_range_step(self):
        expr = CronExpression.parse("0 0-23/2 * * *")
        self.assertEqual(expr.hour, frozenset(range(0, 24, 2)))

    def test_month_and_weekday_names(self):
        expr = CronExpression.parse("0 0 1 JAN Mon")
        self.assertEqual(expr.month, frozenset({1}))
        self.assertEqual(expr.day_of_week, frozenset({1}))

    def test_sunday_alias(self):
        expr = CronExpression.parse("0 0 * * 7")
        self.assertEqual(expr.day_of_week, frozenset({0}))

    def test_wrong_field_count(self):
        with self.assertRaises(CronError):
            CronExpression.parse("* * * *")
        with self.assertRaises(CronError):
            CronExpression.parse("* * * * * *")

    def test_out_of_range(self):
        with self.assertRaises(CronError):
            CronExpression.parse("60 * * * *")
        with self.assertRaises(CronError):
            CronExpression.parse("* 24 * * *")
        with self.assertRaises(CronError):
            CronExpression.parse("* * 0 * *")
        with self.assertRaises(CronError):
            CronExpression.parse("* * * 13 *")

    def test_reversed_range(self):
        with self.assertRaises(CronError):
            CronExpression.parse("10-5 * * * *")

    def test_bad_step(self):
        with self.assertRaises(CronError):
            CronExpression.parse("*/0 * * * *")
        with self.assertRaises(CronError):
            CronExpression.parse("5/2 * * * *")


class MatchTests(unittest.TestCase):
    def test_matches_simple(self):
        expr = CronExpression.parse("30 14 * * *")
        self.assertTrue(expr.matches(datetime(2024, 1, 1, 14, 30)))
        self.assertFalse(expr.matches(datetime(2024, 1, 1, 14, 31)))
        self.assertFalse(expr.matches(datetime(2024, 1, 1, 13, 30)))

    def test_dom_or_dow(self):
        expr = CronExpression.parse("0 0 1 * 1")
        # 2024-01-01 is a Monday and the 1st: both rules match.
        self.assertTrue(expr.matches(datetime(2024, 1, 1, 0, 0)))
        # 2024-01-08 is a Monday but not the 1st: dow matches.
        self.assertTrue(expr.matches(datetime(2024, 1, 8, 0, 0)))
        # 2024-02-01 is the 1st but a Thursday: dom matches.
        self.assertTrue(expr.matches(datetime(2024, 2, 1, 0, 0)))
        # 2024-01-02 is neither the 1st nor a Monday.
        self.assertFalse(expr.matches(datetime(2024, 1, 2, 0, 0)))

    def test_dom_only(self):
        expr = CronExpression.parse("0 0 15 * *")
        self.assertTrue(expr.matches(datetime(2024, 3, 15, 0, 0)))
        self.assertFalse(expr.matches(datetime(2024, 3, 16, 0, 0)))

    def test_dow_only(self):
        expr = CronExpression.parse("0 0 * * 0")
        # 2024-01-07 is a Sunday.
        self.assertTrue(expr.matches(datetime(2024, 1, 7, 0, 0)))
        self.assertFalse(expr.matches(datetime(2024, 1, 8, 0, 0)))


class NextFireTests(unittest.TestCase):
    def test_next_minute(self):
        expr = CronExpression.parse("* * * * *")
        after = datetime(2024, 1, 1, 0, 0, 30)
        self.assertEqual(expr.next_fire(after), datetime(2024, 1, 1, 0, 1))

    def test_inclusive(self):
        expr = CronExpression.parse("30 14 * * *")
        moment = datetime(2024, 1, 1, 14, 30)
        self.assertEqual(expr.next_fire(moment, inclusive=True), moment)
        self.assertEqual(
            expr.next_fire(moment), datetime(2024, 1, 2, 14, 30)
        )

    def test_wraps_to_next_day(self):
        expr = CronExpression.parse("0 0 * * *")
        after = datetime(2024, 1, 1, 0, 0)
        self.assertEqual(expr.next_fire(after), datetime(2024, 1, 2, 0, 0))

    def test_wraps_to_next_month(self):
        expr = CronExpression.parse("0 0 1 * *")
        after = datetime(2024, 1, 15, 12, 0)
        self.assertEqual(expr.next_fire(after), datetime(2024, 2, 1, 0, 0))

    def test_wraps_to_next_year(self):
        expr = CronExpression.parse("0 0 1 1 *")
        after = datetime(2024, 6, 1, 0, 0)
        self.assertEqual(expr.next_fire(after), datetime(2025, 1, 1, 0, 0))

    def test_leap_day(self):
        expr = CronExpression.parse("0 0 29 2 *")
        after = datetime(2023, 3, 1, 0, 0)
        self.assertEqual(expr.next_fire(after), datetime(2024, 2, 29, 0, 0))

    def test_weekday_expression(self):
        expr = CronExpression.parse("0 9 * * 1")
        # 2024-01-01 is a Monday; next Monday after that is the 8th.
        after = datetime(2024, 1, 1, 9, 0)
        self.assertEqual(expr.next_fire(after), datetime(2024, 1, 8, 9, 0))

    def test_seconds_are_truncated(self):
        expr = CronExpression.parse("5 4 * * *")
        after = datetime(2024, 1, 1, 4, 5, 59, 123456)
        self.assertEqual(
            expr.next_fire(after), datetime(2024, 1, 2, 4, 5)
        )

    def test_iter_fire_limit(self):
        expr = CronExpression.parse("0 * * * *")
        after = datetime(2024, 1, 1, 0, 0)
        times = list(expr.iter_fire(after, limit=3))
        self.assertEqual(
            times,
            [
                datetime(2024, 1, 1, 1, 0),
                datetime(2024, 1, 1, 2, 0),
                datetime(2024, 1, 1, 3, 0),
            ],
        )

    def test_iter_fire_inclusive(self):
        expr = CronExpression.parse("0 0 * * *")
        after = datetime(2024, 1, 1, 0, 0)
        times = list(expr.iter_fire(after, inclusive=True, limit=2))
        self.assertEqual(
            times,
            [datetime(2024, 1, 1, 0, 0), datetime(2024, 1, 2, 0, 0)],
        )

    def test_iter_fire_negative_limit(self):
        expr = CronExpression.parse("* * * * *")
        with self.assertRaises(ValueError):
            list(expr.iter_fire(datetime(2024, 1, 1), limit=-1))


if __name__ == "__main__":
    unittest.main()
