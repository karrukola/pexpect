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

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from typing import TYPE_CHECKING
from unittest import mock

import pytest

import pexpect
from pexpect.popen_spawn import PopenSpawn

from . import pexpect_test_case

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [
    pytest.mark.usefixtures("fast_sleep"),
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="drives cat, echo, sleep and ls, plus SIGKILL and SIGTERM delivery",
    ),
]


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for expect and expect_exact on a PopenSpawn child."""

    @staticmethod
    def _ls_bin() -> bytes:
        """Return the output of ``ls -l /bin``, the reference the reads are compared to."""
        proc = subprocess.Popen(
            args=["ls", "-l", "/bin"],  # noqa: S607  # `ls` from PATH is the reference output
            stdout=subprocess.PIPE,
        )
        return proc.communicate()[0].rstrip()

    def _spawn(self, cmd: str | list[str], timeout: float | None = 30) -> PopenSpawn[bytes]:
        """Return a PopenSpawn on *cmd* that is closed when the test ends.

        Nothing else closes one. A PopenSpawn holds two pipes and a reader
        thread, and dropping it leaves all three to the garbage collector,
        which reports them as unclosed files and a still-running subprocess --
        against whichever later test happened to trigger the collection. The
        lingering reader thread is the more expensive half: a multi-threaded
        process cannot fork without a DeprecationWarning, so one abandoned
        spawn here makes every child a later module starts warn.

        close() is safe to reach for a second time, so a test is free to close
        the spawn itself and let this cleanup find the work already done.
        """
        p = PopenSpawn(cmd, timeout=timeout)
        self.addCleanup(p.close)
        return p

    def test_expect_basic(self) -> None:
        """Match successive lines echoed back by ``cat``."""
        p = self._spawn("cat", timeout=5)
        p.sendline(b"Hello")
        p.sendline(b"there")
        p.sendline(b"Mr. Python")
        p.expect(b"Hello")
        p.expect(b"there")
        p.expect(b"Mr. Python")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_expect_exact_basic(self) -> None:
        """Match successive lines echoed back by ``cat`` using expect_exact."""
        p = self._spawn("cat", timeout=5)
        p.sendline(b"Hello")
        p.sendline(b"there")
        p.sendline(b"Mr. Python")
        p.expect_exact(b"Hello")
        p.expect_exact(b"there")
        p.expect_exact(b"Mr. Python")
        p.sendeof()
        p.expect_exact(pexpect.EOF)

    def test_expect(self) -> None:
        """Read a child line by line and recover the same bytes subprocess sees."""
        the_old_way = self._ls_bin()
        p = self._spawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect([b"\n", pexpect.EOF])
            assert isinstance(p.before, bytes)
            the_new_way = the_new_way + p.before
            if i == 1:
                break
            the_new_way += b"\n"
        the_new_way = the_new_way.rstrip()
        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)

    def test_expect_exact(self) -> None:
        """Read a child line by line with expect_exact, treating metacharacters literally."""
        the_old_way = self._ls_bin()
        p = self._spawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect_exact([b"\n", pexpect.EOF])
            assert isinstance(p.before, bytes)
            the_new_way = the_new_way + p.before
            if i == 1:
                break
            the_new_way += b"\n"
        the_new_way = the_new_way.rstrip()

        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)
        p = self._spawn("echo hello.?world")
        i = p.expect_exact(b".?")
        assert p.before == b"hello"
        assert p.after == b".?"

    def test_expect_eof(self) -> None:
        """Read a child's whole output by expecting EOF."""
        the_old_way = self._ls_bin()
        p = self._spawn("ls -l /bin")
        # This basically tells it to read everything. Same as pexpect.run()
        # function.
        p.expect(pexpect.EOF)
        assert isinstance(p.before, bytes)
        the_new_way = p.before.rstrip()
        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)

    def test_expect_timeout(self) -> None:
        """Wait for TIMEOUT and find it reported back in ``after``."""
        p = self._spawn("cat", timeout=0.01)
        p.expect(pexpect.TIMEOUT)  # This tells it to wait for timeout.
        assert p.after == pexpect.TIMEOUT

    def test_unexpected_eof(self) -> None:
        """Raise EOF when the pattern never appears before the child ends."""
        p = self._spawn("ls -l /bin")
        try:
            p.expect("_Z_XY_XZ")  # Probably never see this in ls output.
        except pexpect.EOF:
            pass
        else:
            self.fail("Expected an EOF exception.")

    def test_bad_arg(self) -> None:
        """Reject a pattern that is neither str, bytes nor a compiled regex."""
        p = self._spawn("cat")
        # What is under test is the argument the signatures already rule out, so
        # the matchers are called through names that accept anything.
        expect: Callable[..., int] = p.expect
        expect_exact: Callable[..., int] = p.expect_exact
        with pytest.raises(TypeError, match=r".*must be one of"):
            expect(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            expect([1, b"2"])
        with pytest.raises(TypeError, match=r".*must be one of"):
            expect_exact(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            expect_exact([1, b"2"])

    def test_timeout_none(self) -> None:
        """Match without a timeout, blocking until the data arrives."""
        p = self._spawn("echo abcdef", timeout=None)
        p.expect("abc")
        p.expect_exact("def")
        p.expect(pexpect.EOF)

    def test_crlf(self) -> None:
        """Read a child's output as bytes ending in the platform line terminator."""
        p = self._spawn("echo alpha beta")
        assert p.read() == b"alpha beta" + p.crlf

    def test_crlf_encoding(self) -> None:
        """Read a child's output as text when an encoding is given."""
        p = PopenSpawn("echo alpha beta", encoding="utf-8")
        self.addCleanup(p.close)
        assert p.read() == "alpha beta" + p.crlf

    def test_command_as_a_list(self) -> None:
        """Start a child from an already split command line.

        Given a command given as a list of arguments rather than as one string,
        When a PopenSpawn is created from it,
        Then the list is passed through unsplit and the child runs.
        """
        p = self._spawn(["echo", "alpha beta"])
        assert p.read() == b"alpha beta" + p.crlf

    def test_write_and_writelines(self) -> None:
        """Send data to the child with the file-like write methods.

        Given a ``cat`` child,
        When :meth:`PopenSpawn.write` and :meth:`PopenSpawn.writelines` are
        used to send data,
        Then the child echoes everything back in the order it was sent.
        """
        p = self._spawn("cat", timeout=5)
        p.write(b"alpha")
        p.writelines([b" beta", b" gamma", b"\n"])
        p.expect_exact(b"alpha beta gamma")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_wait_reports_the_exit_status(self) -> None:
        """Report the exit code of a child that exited on its own.

        Given a child that exits with status 1,
        When :meth:`PopenSpawn.wait` is called,
        Then it returns that status and records it on the spawn.
        """
        p = self._spawn([sys.executable, "exit1.py"])
        p.expect(pexpect.EOF)

        assert p.wait() == 1
        assert p.exitstatus == 1
        assert p.signalstatus is None
        assert p.terminated

    def test_wait_reports_the_signal_that_killed_the_child(self) -> None:
        """Report the signal a child was killed by.

        Given a ``cat`` child that is sent SIGKILL,
        When :meth:`PopenSpawn.wait` is called,
        Then the signal is reported instead of an exit status.
        """
        p = self._spawn("cat")
        p.kill(signal.SIGKILL)

        assert p.wait() == -signal.SIGKILL
        assert p.exitstatus is None
        assert p.signalstatus == signal.SIGKILL
        assert p.terminated

    def test_context_manager_closes_the_child(self) -> None:
        """Use PopenSpawn as a context manager, which needs close().

        Given a ``cat`` child used in a ``with`` block,
        When the block exits,
        Then ``SpawnBase.__exit__`` can call :meth:`PopenSpawn.close` -- which
        used to be missing, raising AttributeError -- and the child is gone.
        """
        with PopenSpawn("cat", timeout=5) as p:
            p.sendline(b"hi")
            p.expect(b"hi")

        assert p.closed
        assert not p.isalive()

    def test_close_after_sendeof_does_not_raise(self) -> None:
        """Close a child whose stdin is already closed, twice.

        Given a ``cat`` child that has already seen EOF on its own via
        :meth:`sendeof`,
        When :meth:`PopenSpawn.close` is called, and then called again,
        Then neither call raises, the second is a no-op, and the exit status
        of the child is recorded.
        """
        p = self._spawn("cat", timeout=5)
        p.sendeof()
        p.expect(pexpect.EOF)

        p.close()
        assert p.closed
        assert p.exitstatus == 0
        assert p.terminated

        p.close()  # a second call must be a no-op, like the other spawn classes
        assert p.closed

    def test_close_terminates_a_child_that_ignores_stdin_eof(self) -> None:
        """Close a child that stdin EOF alone cannot end.

        Given a ``sleep`` child, which never reads its stdin so closing it
        does nothing,
        When :meth:`PopenSpawn.close` is called,
        Then it does not block for the full sleep -- it falls through to
        SIGTERM, which returns promptly -- and the signal is recorded.
        """
        p = self._spawn("sleep 5")
        p.delayafterclose = 0.05
        p.delayafterterminate = 0.05

        p.close()

        assert p.closed
        assert not p.isalive()
        assert p.exitstatus is None
        assert p.signalstatus == signal.SIGTERM
        assert p.terminated

    def test_close_kills_a_child_that_ignores_sigterm(self) -> None:
        """Escalate to SIGKILL for a child that ignores SIGTERM too.

        Given a child that ignores both stdin EOF and SIGTERM,
        When :meth:`PopenSpawn.close` is called,
        Then it escalates all the way to SIGKILL, which the child cannot
        ignore, and that signal is recorded.
        """
        ignores_sigterm = (
            "import signal, sys, time\n"
            "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
            "print('ready')\n"
            "sys.stdout.flush()\n"
            "time.sleep(5)\n"
        )
        p = self._spawn([sys.executable, "-c", ignores_sigterm])
        # Wait for the handler to actually be installed before close() sends
        # SIGTERM, or a slow interpreter start-up would race it: the signal
        # would arrive -- and be handled by the *default* action -- before
        # the child's own call to signal.signal() ran.
        p.expect(b"ready")
        p.delayafterclose = 0.05
        p.delayafterterminate = 0.05

        p.close()

        assert p.closed
        assert not p.isalive()
        assert p.exitstatus is None
        assert p.signalstatus == signal.SIGKILL
        assert p.terminated

    def test_isalive_while_running(self) -> None:
        """Report a running child as alive without touching its exit status.

        Given a ``cat`` child that has not been asked to exit,
        When :meth:`PopenSpawn.isalive` is called,
        Then it returns True and leaves exitstatus/signalstatus untouched.
        """
        p = self._spawn("cat", timeout=5)
        try:
            assert p.isalive()
            assert p.exitstatus is None
            assert p.signalstatus is None
        finally:
            p.kill(signal.SIGKILL)
            p.proc.wait()

    def test_isalive_records_exit_status(self) -> None:
        """Record the exit status of a child that exited on its own.

        Given a child that has exited with status 1,
        When :meth:`PopenSpawn.isalive` is called,
        Then it returns False and records exitstatus/terminated, the way
        :meth:`wait` does.
        """
        p = self._spawn([sys.executable, "exit1.py"])
        p.expect(pexpect.EOF)
        p.proc.wait()  # make sure the OS has reaped it before polling

        assert p.isalive() is False
        assert p.exitstatus == 1
        assert p.signalstatus is None
        assert p.terminated

    def test_isalive_records_signal_status(self) -> None:
        """Record the signal that killed a child.

        Given a ``cat`` child sent SIGKILL,
        When :meth:`PopenSpawn.isalive` is called,
        Then it returns False and records signalstatus/terminated.
        """
        p = self._spawn("cat")
        p.kill(signal.SIGKILL)
        p.proc.wait()  # make sure the OS has reaped it before polling

        assert p.isalive() is False
        assert p.exitstatus is None
        assert p.signalstatus == signal.SIGKILL
        assert p.terminated

    def test_read_after_eof_drains_the_buffer(self) -> None:
        """Hand out what is left in the buffer before reporting EOF.

        Given a child whose pipe has closed, with characters still buffered.
        The buffer is seeded here because read_nonblocking() never leaves
        anything behind once it has seen the end of the child's output, so this
        guard is otherwise unreachable,
        When read_nonblocking() is called for fewer characters than the buffer
        holds, and then called until the buffer is empty,
        Then the buffered characters come out first and EOF is only raised once
        nothing is left.
        """
        p = self._spawn("echo alpha")
        p.expect(pexpect.EOF)
        assert p._read_reached_eof

        p._buf = b"beta"
        assert p.read_nonblocking(size=2, timeout=5) == b"be"
        assert p.read_nonblocking(size=2, timeout=5) == b"ta"
        with pytest.raises(pexpect.EOF):
            p.read_nonblocking(size=2, timeout=5)

    def test_read_nonblocking_with_the_default_timeout(self) -> None:
        """Read with the timeout the spawn was created with.

        Given a PopenSpawn created with a timeout of its own,
        When read_nonblocking() is called with the -1 default, meaning "use the
        spawn timeout", until the reader thread has queued the child's output,
        Then that output is returned.
        """
        p = self._spawn("echo alpha", timeout=5)

        deadline = time.time() + 5
        data = b""
        while not data and time.time() < deadline:
            data = p.read_nonblocking(size=1000, timeout=-1)

        assert b"alpha" in data

    def test_read_nonblocking_of_nothing(self) -> None:
        """Return at once when no characters were asked for.

        Given a running child,
        When read_nonblocking() is asked for zero characters,
        Then it returns an empty result without waiting for the child.
        """
        p = self._spawn("cat", timeout=5)
        assert p.read_nonblocking(size=0, timeout=5) == b""
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_read_nonblocking_raises_timeout_when_nothing_arrives(self) -> None:
        """Raise TIMEOUT instead of returning empty when nothing arrives.

        Given a ``cat`` child that has been sent nothing to echo back,
        When read_nonblocking() is called with a timeout,
        Then it raises TIMEOUT once that timeout passes -- the behaviour
        every other spawn class's read_nonblocking() has -- rather than
        returning an empty string as if it were EOF.

        A real, small slice of wall-clock time is spent here: Queue.get()
        waits on the un-monkeypatched clock even under the fast_sleep
        fixture, which is exactly why the timeout below is kept short.
        """
        p = self._spawn("cat", timeout=5)
        try:
            with pytest.raises(pexpect.TIMEOUT):
                p.read_nonblocking(size=10, timeout=0.05)
        finally:
            p.kill(signal.SIGKILL)
            p.proc.wait()

    def test_read_nonblocking_raises_timeout_immediately_for_a_zero_timeout(self) -> None:
        """Raise TIMEOUT without waiting when a zero timeout is given.

        Given a ``cat`` child with nothing queued yet,
        When read_nonblocking() is called with ``timeout=0``,
        Then it raises TIMEOUT straight away rather than making a blocking
        call to the reader queue.
        """
        p = self._spawn("cat", timeout=5)
        try:
            with pytest.raises(pexpect.TIMEOUT):
                p.read_nonblocking(size=10, timeout=0)
        finally:
            p.kill(signal.SIGKILL)
            p.proc.wait()

    def test_expect_matches_promptly_instead_of_waiting_out_the_timeout(self) -> None:
        """Match quickly rather than busy-polling for the whole timeout.

        Given a ``cat`` child that echoes back a line right away,
        When expect() waits for it with a generous timeout,
        Then the match comes back almost immediately -- this is the
        regression guard for the trap in this fix: waiting for *size*
        characters instead of the first one turned a millisecond-scale match
        into the full timeout. Timed with perf_counter(), which fast_sleep
        does not fake, unlike time.time().
        """
        p = self._spawn("cat", timeout=5)
        p.sendline(b"hello")

        started = time.perf_counter()
        p.expect(b"hello")
        elapsed = time.perf_counter() - started

        assert elapsed < 1.0
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_reader_thread_survives_a_read_error(self) -> None:
        """Treat a failed read of the child's pipe as the end of its output.

        Given a reader whose next read of the child's pipe fails,
        When the reader loop runs,
        Then the error is logged and the loop reports the end of the output by
        queueing the None sentinel.
        """
        p = self._spawn("cat")

        with mock.patch.object(os, "read", side_effect=OSError("read failed")):
            p._read_incoming()

        assert p._read_queue.get_nowait() is None
        p.kill(signal.SIGKILL)
        p.wait()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
