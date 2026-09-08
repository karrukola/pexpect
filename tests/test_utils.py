"""Tests for the helpers in :mod:`pexpect.utils`."""

import errno
import os
import select
import sys
import unittest
from unittest import mock

import pytest

from pexpect import utils

# a call that is interrupted once is made twice in total
_CALLS_AFTER_ONE_INTERRUPT = 2


class SelectIgnoreInterruptsTestCase(unittest.TestCase):
    """Tests for :func:`pexpect.utils.select_ignore_interrupts`."""

    def test_interrupted_select_is_retried(self) -> None:
        """Retry a select() that a signal interrupted.

        Given a select() that is interrupted once before it reports a ready
        file descriptor,
        When :func:`utils.select_ignore_interrupts` is called with a timeout,
        Then it retries and returns the ready file descriptor.
        """
        ready: tuple[list[int], list[int], list[int]] = ([1], [], [])
        with mock.patch.object(
            select, "select", side_effect=[InterruptedError(errno.EINTR, "interrupted"), ready]
        ) as fake_select:
            assert utils.select_ignore_interrupts([1], [], [], timeout=10) == ready

        assert fake_select.call_count == _CALLS_AFTER_ONE_INTERRUPT

    def test_interrupted_select_is_retried_without_timeout(self) -> None:
        """Retry an interrupted select() that was called without a timeout.

        Given a select() with no timeout that is interrupted once,
        When :func:`utils.select_ignore_interrupts` is called,
        Then it retries with no timeout and returns the ready file descriptor.
        """
        ready: tuple[list[int], list[int], list[int]] = ([1], [], [])
        with mock.patch.object(
            select, "select", side_effect=[InterruptedError(errno.EINTR, "interrupted"), ready]
        ) as fake_select:
            assert utils.select_ignore_interrupts([1], [], [], timeout=None) == ready

        assert [call.args[-1] for call in fake_select.call_args_list] == [None, None]

    def test_interrupted_select_gives_up_when_the_timeout_expired(self) -> None:
        """Report nothing ready when the interrupt used up the whole timeout.

        Given a select() that is interrupted by a signal,
        When the timeout has already expired by the time the interrupt arrives,
        Then empty lists are returned instead of retrying.
        """
        with mock.patch.object(
            select, "select", side_effect=InterruptedError(errno.EINTR, "interrupted")
        ):
            assert utils.select_ignore_interrupts([1], [], [], timeout=-1) == ([], [], [])

    def test_other_interrupt_errors_are_raised(self) -> None:
        """Pass on an interruption that is not EINTR.

        Given a select() that fails with an errno other than EINTR,
        When :func:`utils.select_ignore_interrupts` is called,
        Then the error is raised instead of being retried.
        """
        with (
            mock.patch.object(
                select, "select", side_effect=InterruptedError(errno.EIO, "input/output error")
            ),
            pytest.raises(InterruptedError),
        ):
            utils.select_ignore_interrupts([1], [], [], timeout=10)


class PollIgnoreInterruptsTestCase(unittest.TestCase):
    """Tests for :func:`pexpect.utils.poll_ignore_interrupts`."""

    @staticmethod
    def _fake_poll(*side_effect: object) -> mock.MagicMock:
        """Return a mock of :func:`select.poll` whose poll() has *side_effect*."""
        poller = mock.MagicMock()
        poller.poll.side_effect = side_effect
        return mock.MagicMock(return_value=poller)

    def test_poll_without_timeout(self) -> None:
        """Poll without a timeout, so that poll() blocks until something is ready.

        Given a poll() that reports a ready file descriptor,
        When :func:`utils.poll_ignore_interrupts` is called without a timeout,
        Then poll() is called with no timeout and the ready descriptor is
        returned.
        """
        fake_poll = self._fake_poll([(1, select.POLLIN)])
        with mock.patch.object(select, "poll", fake_poll):
            assert utils.poll_ignore_interrupts([1]) == [1]

        fake_poll.return_value.poll.assert_called_once_with(None)

    def test_interrupted_poll_is_retried(self) -> None:
        """Retry a poll() that a signal interrupted.

        Given a poll() that is interrupted once before it reports a ready file
        descriptor,
        When :func:`utils.poll_ignore_interrupts` is called with a timeout,
        Then it retries and returns the ready file descriptor.
        """
        fake_poll = self._fake_poll(
            InterruptedError(errno.EINTR, "interrupted"), [(1, select.POLLIN)]
        )
        with mock.patch.object(select, "poll", fake_poll):
            assert utils.poll_ignore_interrupts([1], timeout=10) == [1]

        assert fake_poll.return_value.poll.call_count == _CALLS_AFTER_ONE_INTERRUPT

    def test_interrupted_poll_is_retried_without_timeout(self) -> None:
        """Retry an interrupted poll() that was called without a timeout.

        Given a poll() with no timeout that is interrupted once,
        When :func:`utils.poll_ignore_interrupts` is called,
        Then it retries with no timeout and returns the ready file descriptor.
        """
        fake_poll = self._fake_poll(
            InterruptedError(errno.EINTR, "interrupted"), [(1, select.POLLIN)]
        )
        with mock.patch.object(select, "poll", fake_poll):
            assert utils.poll_ignore_interrupts([1], timeout=None) == [1]

        assert fake_poll.return_value.poll.call_args_list == [mock.call(None), mock.call(None)]

    def test_interrupted_poll_gives_up_when_the_timeout_expired(self) -> None:
        """Report nothing ready when the interrupt used up the whole timeout.

        Given a poll() that is interrupted by a signal,
        When the timeout has already expired by the time the interrupt arrives,
        Then an empty list is returned instead of retrying.
        """
        fake_poll = self._fake_poll(InterruptedError(errno.EINTR, "interrupted"))
        with mock.patch.object(select, "poll", fake_poll):
            assert utils.poll_ignore_interrupts([1], timeout=-1) == []

    def test_other_interrupt_errors_are_raised(self) -> None:
        """Pass on an interruption that is not EINTR.

        Given a poll() that fails with an errno other than EINTR,
        When :func:`utils.poll_ignore_interrupts` is called,
        Then the error is raised instead of being retried.
        """
        fake_poll = self._fake_poll(InterruptedError(errno.EIO, "input/output error"))
        with mock.patch.object(select, "poll", fake_poll), pytest.raises(InterruptedError):
            utils.poll_ignore_interrupts([1], timeout=10)


class IsExecutableFileTestCase(unittest.TestCase):
    """Tests for :func:`pexpect.utils.is_executable_file` on Solaris."""

    def test_root_on_solaris_looks_at_the_permission_bits(self) -> None:
        """Judge executability from the mode bits when running as root on Solaris.

        Given a Solaris-like platform and a process running as root, where
        ``os.access`` reports every file as executable,
        When :func:`utils.is_executable_file` is asked about a file that has no
        executable bit and about the Python interpreter, which has one,
        Then only the file carrying an executable bit is reported executable.
        """
        with (
            mock.patch.object(sys, "platform", "sunos5"),
            mock.patch.object(os, "getuid", return_value=0),
        ):
            assert not utils.is_executable_file(__file__)
            assert utils.is_executable_file(sys.executable)


if __name__ == "__main__":
    unittest.main()
