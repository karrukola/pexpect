"""Tests for awaiting a pexpect match across a garbage collection.

Starting a Python child and then running a full collection while it is mid-run
costs more than the suite's time budget, and a partial collection would not be
the thing worth testing.
"""

import gc
import unittest

import pytest

import pexpect
from tests import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep")


class AsyncTests(pexpect_test_case.AsyncPexpectTestCase):
    """Tests for expect_exact awaited across a collection."""

    async def test_async_and_gc(self) -> None:
        """Keep an awaited match working across a garbage collection."""
        p = pexpect.spawn(f"{self.PYTHONBIN} sleep_for.py 0.05", encoding="utf8")
        assert await p.expect_exact("READY", async_=True) == 0
        gc.collect()
        assert await p.expect_exact("END", async_=True) == 0


if __name__ == "__main__":
    unittest.main()
