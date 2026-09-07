"""Tests for terminate() escalating through the signals it tries in turn.

A child that ignores SIGHUP, SIGCONT and SIGINT makes terminate() walk all four
signals, waiting delayafterterminate after each one. Those waits are the one
kind of sleep the suite cannot fake away, because no clock offset will make a
process exit and be reaped, so a full escalation costs four real settling delays
on top of starting the Python child that does the ignoring.
"""

import unittest

import pytest

import pexpect
from tests import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep")


class TerminateTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for terminate() against a child that only SIGKILL will stop."""

    def test_terminate_a_child_that_ignores_the_polite_signals(self) -> None:
        """Report failure when the child survives everything but SIGKILL.

        Given a child that ignores SIGHUP, SIGCONT and SIGINT,
        When :meth:`pexpect.spawn.terminate` is called without force, so that
        SIGKILL is never sent,
        Then it returns False and the child is still alive.
        """
        child = pexpect.spawn(self.PYTHONBIN + " needs_kill.py")
        child.expect("READY")

        assert not child.terminate()
        assert child.isalive()

        child.terminate(force=True)

    def test_forced_terminate(self) -> None:
        """End a child that traps the polite signals with terminate(force=True)."""
        p = pexpect.spawn(self.PYTHONBIN, ["needs_kill.py"])
        p.expect("READY")
        assert p.terminate(force=True)
        p.expect(pexpect.EOF)
        assert not p.isalive()

    ### Some platforms allow this. Some reset status after call to waitpid.
    ### probably not necessary, isalive() returns early when terminate is False.


if __name__ == "__main__":
    unittest.main()
