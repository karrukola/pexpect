#!/usr/bin/env python
"""Tests that pexpect exceptions survive a pickle round-trip."""

import pickle
import unittest

from pexpect import ExceptionPexpect


class PickleTest(unittest.TestCase):
    """Tests for pickling ExceptionPexpect."""

    def test_picking(self) -> None:
        """Round-trip an ExceptionPexpect through pickle and keep its value."""
        e = ExceptionPexpect("Oh noes!")
        clone = pickle.loads(pickle.dumps(e))  # noqa: S301  # our own pickle is the test
        assert e.value == clone.value


if __name__ == "__main__":
    unittest.main()
