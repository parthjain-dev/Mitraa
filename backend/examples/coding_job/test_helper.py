"""Select this file as input, then run it after proposing value() -> 2."""
import unittest
from helper import value


class TestValue(unittest.TestCase):
    def test_returns_two(self):
        self.assertEqual(value(), 2)
