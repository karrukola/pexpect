#!/usr/bin/env python
"""PEXPECT LICENSE.

This license is approved by the OSI and FSF as GPL-compatible.
http://opensource.org/licenses/isc-license.txt

Copyright (c) 2012, Noah Spurrier <noah@noah.org>
PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""

import signal
import sys
import time
import unittest

import pytest

import pexpect

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")
KILL_SIGNAL = 9  # SIGKILL, spelled as a number because that is what kill(1) takes


class IsAliveTestCase(pexpect_test_case.PexpectTestCase):
    """Various tests for the running status of processes."""

    def test_expect_wait(self) -> None:
        """Ensure consistency in wait() and isalive()."""
        p = pexpect.spawn("sleep 0.05")
        assert p.isalive()
        assert p.wait() == 0
        assert not p.isalive()
        # In previous versions of ptyprocess/pexpect, calling wait() a second
        # time would raise an exception, but not since v4.0
        assert p.wait() == 0

    def test_expect_wait_after_termination(self) -> None:
        """Ensure wait on a process terminated by kill -9."""
        p = pexpect.spawn("sleep 3")
        assert p.isalive()
        p.kill(KILL_SIGNAL)
        time.sleep(1)

        # when terminated, the exitstatus is None, but p.signalstatus
        # and p.terminated reflects that the kill -9 nature.
        assert p.wait() is None
        assert p.signalstatus == KILL_SIGNAL
        assert p.terminated
        assert not p.isalive()

    def test_signal_wait(self) -> str | None:
        """Test calling wait with a process terminated by a signal."""
        if not hasattr(signal, "SIGALRM"):
            return "SKIP"
        p = pexpect.spawn(self.PYTHONBIN, ["alarm_die.py"])
        p.wait()
        assert p.exitstatus is None
        assert p.signalstatus == signal.SIGALRM
        return None

    def test_expect_isalive_dead_after_normal_termination(self) -> None:
        """Report a child that ran to completion as no longer alive."""
        p = pexpect.spawn("ls", timeout=15)
        p.expect(pexpect.EOF)
        assert not p.isalive()

    def test_expect_isalive_dead_after_sighup(self) -> None:
        """Report a child that honours the SIGHUP from terminate() as no longer alive."""
        p = pexpect.spawn("cat", timeout=5, ignore_sighup=False)
        assert p.isalive()
        force = False
        if sys.platform.lower().startswith("sunos"):
            # On Solaris (SmartOs), and only when executed from cron(1), SIGKILL
            # is required to end the sub-process. This is done using force=True
            force = True
        assert p.terminate(force)
        p.expect(pexpect.EOF)
        assert not p.isalive()

    def test_expect_isalive_dead_after_sigint(self) -> None:
        """Report a child that ignores SIGHUP as no longer alive once terminate() escalates."""
        p = pexpect.spawn("cat", timeout=5)
        assert p.isalive()
        force = False
        if sys.platform.lower().startswith("sunos"):
            # On Solaris (SmartOs), and only when executed from cron(1), SIGKILL
            # is required to end the sub-process. This is done using force=True
            force = True
        assert p.terminate(force)
        p.expect(pexpect.EOF)
        assert not p.isalive()

    def test_expect_isalive_dead_after_sigkill(self) -> None:
        """Report a child killed outright with signal 9 as no longer alive."""
        p = pexpect.spawn("cat", timeout=5)
        assert p.isalive()
        p.kill(KILL_SIGNAL)
        p.expect(pexpect.EOF)
        assert not p.isalive()

    def test_expect_isalive_consistent_multiple_calls(self) -> None:
        """Return the same value from repeated isalive() calls."""
        p = pexpect.spawn("cat")
        assert p.isalive()
        assert p.isalive()
        p.sendeof()
        p.expect(pexpect.EOF)
        assert not p.isalive()
        assert not p.isalive()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(IsAliveTestCase)
