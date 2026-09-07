"""Tests for spawn behaviour that needs more than one Python child.

``ignore_sighup`` has to be watched on a child that honours SIGHUP and on one
that does not, which is two interpreters plus the polling in between: past the
suite's time budget on its own.
"""

import signal
import time
import unittest

import pytest

import pexpect
from tests import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep")
# How many times the test looks at the child after signalling it. Each look is
# a poll of isalive() with a pause after it.
_SIGHUP_POLLS = 3


class TestCaseMisc(pexpect_test_case.PexpectTestCase):
    """Tests for the ignore_sighup argument of spawn."""

    def test_sighup(self) -> None:
        """Validate argument `ignore_sighup=True` and `ignore_sighup=False`."""
        getch = self.PYTHONBIN + " getch.py"
        child = pexpect.spawn(getch, ignore_sighup=True)
        child.expect("READY")
        child.kill(signal.SIGHUP)
        for _ in range(_SIGHUP_POLLS):
            if not child.isalive():
                self.fail("Child process should not have exited.")
            time.sleep(0.1)

        child = pexpect.spawn(getch, ignore_sighup=False)
        child.expect("READY")
        child.kill(signal.SIGHUP)
        for _ in range(_SIGHUP_POLLS):
            if not child.isalive():
                break
            time.sleep(0.1)
        else:
            self.fail("Child process should have exited.")


if __name__ == "__main__":
    unittest.main()
