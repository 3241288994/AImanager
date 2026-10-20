import json
import unittest
from decimal import Decimal

from quota import remaining_percent


class QuotaTests(unittest.TestCase):
    def test_zero_is_full(self):
        self.assertEqual(remaining_percent(0), 100.0)

    def test_used_is_empty(self):
        self.assertEqual(remaining_percent(1), 0.0)

    def test_missing_is_unknown(self):
        self.assertIsNone(remaining_percent(None))

    def test_valid_floats(self):
        cases = [(0.0, 100.0), (1.0, 0.0), (0.5, 50.0), (0.333, 66.7), (0.25, 75.0)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(remaining_percent(value), expected)

    def test_returns_float(self):
        for value in (0, 1, 0.5):
            with self.subTest(value=value):
                self.assertIs(type(remaining_percent(value)), float)

    def test_non_numeric_types_are_unknown(self):
        for value in (True, False, "0.5", "", Decimal("0.5"), [0.5], {}):
            with self.subTest(value=value):
                self.assertIsNone(remaining_percent(value))

    def test_nonfinite_is_unknown(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                self.assertIsNone(remaining_percent(value))

    def test_json_nonfinite_is_unknown(self):
        # json.loads accepts NaN/Infinity by default and yields floats.
        for text in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(text=text):
                self.assertIsNone(remaining_percent(json.loads(text)))

    def test_out_of_range_is_unknown(self):
        for value in (-0.01, 1.01, -1, 2):
            with self.subTest(value=value):
                self.assertIsNone(remaining_percent(value))

    def test_huge_ints_are_unknown_without_overflow(self):
        for value in (10 ** 400, -(10 ** 400)):
            with self.subTest(sign=value > 0):
                self.assertIsNone(remaining_percent(value))


if __name__ == '__main__':
    unittest.main()
