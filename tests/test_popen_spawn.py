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

import os
import signal
import subprocess
import sys
import time
import unittest
from unittest import mock

import pytest

import pexpect
from pexpect.popen_spawn import PopenSpawn

from . import pexpect_test_case


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

    def test_expect_basic(self) -> None:
        """Match successive lines echoed back by ``cat``."""
        p = PopenSpawn("cat", timeout=5)
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
        p = PopenSpawn("cat", timeout=5)
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
        p = PopenSpawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect([b"\n", pexpect.EOF])
            the_new_way = the_new_way + p.before
            if i == 1:
                break
            the_new_way += b"\n"
        the_new_way = the_new_way.rstrip()
        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)

    def test_expect_exact(self) -> None:
        """Read a child line by line with expect_exact, treating metacharacters literally."""
        the_old_way = self._ls_bin()
        p = PopenSpawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect_exact([b"\n", pexpect.EOF])
            the_new_way = the_new_way + p.before
            if i == 1:
                break
            the_new_way += b"\n"
        the_new_way = the_new_way.rstrip()

        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)
        p = PopenSpawn("echo hello.?world")
        i = p.expect_exact(b".?")
        assert p.before == b"hello"
        assert p.after == b".?"

    def test_expect_eof(self) -> None:
        """Read a child's whole output by expecting EOF."""
        the_old_way = self._ls_bin()
        p = PopenSpawn("ls -l /bin")
        # This basically tells it to read everything. Same as pexpect.run()
        # function.
        p.expect(pexpect.EOF)
        the_new_way = p.before.rstrip()
        assert the_old_way == the_new_way, len(the_old_way) - len(the_new_way)

    def test_expect_timeout(self) -> None:
        """Wait for TIMEOUT and find it reported back in ``after``."""
        p = PopenSpawn("cat", timeout=5)
        p.expect(pexpect.TIMEOUT)  # This tells it to wait for timeout.
        assert p.after == pexpect.TIMEOUT

    def test_unexpected_eof(self) -> None:
        """Raise EOF when the pattern never appears before the child ends."""
        p = PopenSpawn("ls -l /bin")
        try:
            p.expect("_Z_XY_XZ")  # Probably never see this in ls output.
        except pexpect.EOF:
            pass
        else:
            self.fail("Expected an EOF exception.")

    def test_bad_arg(self) -> None:
        """Reject a pattern that is neither str, bytes nor a compiled regex."""
        p = PopenSpawn("cat")
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect([1, b"2"])
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact([1, b"2"])

    def test_timeout_none(self) -> None:
        """Match without a timeout, blocking until the data arrives."""
        p = PopenSpawn("echo abcdef", timeout=None)
        p.expect("abc")
        p.expect_exact("def")
        p.expect(pexpect.EOF)

    def test_crlf(self) -> None:
        """Read a child's output as bytes ending in the platform line terminator."""
        p = PopenSpawn("echo alpha beta")
        assert p.read() == b"alpha beta" + p.crlf

    def test_crlf_encoding(self) -> None:
        """Read a child's output as text when an encoding is given."""
        p = PopenSpawn("echo alpha beta", encoding="utf-8")
        assert p.read() == "alpha beta" + p.crlf

    def test_command_as_a_list(self) -> None:
        """Start a child from an already split command line.

        Given a command given as a list of arguments rather than as one string,
        When a PopenSpawn is created from it,
        Then the list is passed through unsplit and the child runs.
        """
        p = PopenSpawn(["echo", "alpha beta"])
        assert p.read() == b"alpha beta" + p.crlf

    def test_write_and_writelines(self) -> None:
        """Send data to the child with the file-like write methods.

        Given a ``cat`` child,
        When :meth:`PopenSpawn.write` and :meth:`PopenSpawn.writelines` are
        used to send data,
        Then the child echoes everything back in the order it was sent.
        """
        p = PopenSpawn("cat", timeout=5)
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
        p = PopenSpawn([sys.executable, "exit1.py"])
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
        p = PopenSpawn("cat")
        p.kill(signal.SIGKILL)

        assert p.wait() == -signal.SIGKILL
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
        p = PopenSpawn("echo alpha")
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
        p = PopenSpawn("echo alpha", timeout=5)

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
        p = PopenSpawn("cat", timeout=5)
        assert p.read_nonblocking(size=0, timeout=5) == b""
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_reader_thread_survives_a_read_error(self) -> None:
        """Treat a failed read of the child's pipe as the end of its output.

        Given a reader whose next read of the child's pipe fails,
        When the reader loop runs,
        Then the error is logged and the loop reports the end of the output by
        queueing the None sentinel.
        """
        p = PopenSpawn("cat")

        with mock.patch.object(os, "read", side_effect=OSError("read failed")):
            p._read_incoming()

        assert p._read_queue.get_nowait() is None
        p.kill(signal.SIGKILL)
        p.wait()


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
