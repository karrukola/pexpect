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

import io
import os
import re
import signal
import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from unittest import mock

import pytest

import pexpect
from pexpect import pty_spawn

from . import pexpect_test_case

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")

# the program cat(1) may display ^D\x08\x08 when \x04 (EOF, Ctrl-D) is sent
_CAT_EOF = b"^D\x08\x08"

# The shortest read_nonblocking() timeout pexpect accepts on Irix. pexpect ships
# 2 seconds; the test patches this shorter value in, because what it checks is
# that a shorter timeout gets stretched to the minimum, not what the minimum is.
_IRIX_MIN_TIMEOUT = 0.02

# read_nonblocking() raises this once the spawn has been closed
_CLOSED_FILE_ERRMSG = re.escape("I/O operation on closed file.")


class TestCaseMisc(pexpect_test_case.PexpectTestCase):
    """Cover spawn's file-like read/write API, lifecycle and argument checking."""

    def test_isatty(self) -> None:
        """Test isatty() is True after spawning process on most platforms."""
        child = pexpect.spawn("cat")
        if not child.isatty() and sys.platform.lower().startswith("sunos"):
            msg = "Not supported on this platform."
            raise unittest.SkipTest(msg)
        assert child.isatty()

    def test_isatty_poll(self) -> None:
        """Test isatty() is True after spawning process on most platforms."""
        child = pexpect.spawn("cat", use_poll=True)
        if not child.isatty() and sys.platform.lower().startswith("sunos"):
            msg = "Not supported on this platform."
            raise unittest.SkipTest(msg)
        assert child.isatty()

    def test_read(self) -> None:
        """Test spawn.read by calls of various size."""
        child = pexpect.spawn("cat")
        child.sendline("abc")
        child.sendeof()
        assert child.read(0) == b""
        assert child.read(1) == b"a"
        assert child.read(1) == b"b"
        assert child.read(1) == b"c"
        assert child.read(2) == b"\r\n"
        remaining = child.read().replace(_CAT_EOF, b"")
        assert remaining == b"abc\r\n"

    def test_read_poll(self) -> None:
        """Test spawn.read by calls of various size."""
        child = pexpect.spawn("cat", use_poll=True)
        child.sendline("abc")
        child.sendeof()
        assert child.read(0) == b""
        assert child.read(1) == b"a"
        assert child.read(1) == b"b"
        assert child.read(1) == b"c"
        assert child.read(2) == b"\r\n"
        remaining = child.read().replace(_CAT_EOF, b"")
        assert remaining == b"abc\r\n"

    def test_read_poll_timeout(self) -> None:
        """Test use_poll properly times out."""
        child = pexpect.spawn("sleep 5", use_poll=True)
        with pytest.raises(pexpect.TIMEOUT):
            child.expect(pexpect.EOF, timeout=0.01)

    def test_readline_bin_echo(self) -> None:
        """Test spawn('echo')."""
        # given,
        child = pexpect.spawn("echo", ["alpha", "beta"])

        # exercise,
        assert child.readline() == b"alpha beta" + child.crlf

    def test_readline(self) -> None:
        """Test spawn.readline()."""
        # when argument 0 is sent, nothing is returned.
        # Otherwise the argument value is meaningless.
        child = pexpect.spawn("cat", echo=False)
        child.sendline("alpha")
        child.sendline("beta")
        child.sendline("gamma")
        child.sendline("delta")
        child.sendeof()
        assert child.readline(0) == b""
        assert child.readline().rstrip() == b"alpha"
        assert child.readline(1).rstrip() == b"beta"
        assert child.readline(2).rstrip() == b"gamma"
        assert child.readline().rstrip() == b"delta"
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0

    def test_iter(self) -> None:
        """Iterating over lines of spawn.__iter__()."""
        child = pexpect.spawn("cat", echo=False)
        child.sendline("abc")
        child.sendline("123")
        child.sendeof()
        # Don't use ''.join() because we want to test __iter__().
        page = b""
        for line in child:
            page += line
        page = page.replace(_CAT_EOF, b"")
        assert page == b"abc\r\n123\r\n"

    def test_readlines(self) -> None:
        """Reading all lines of spawn.readlines()."""
        child = pexpect.spawn("cat", echo=False)
        child.sendline("abc")
        child.sendline("123")
        child.sendeof()
        page = b"".join(child.readlines()).replace(_CAT_EOF, b"")
        assert page == b"abc\r\n123\r\n"
        child.expect(pexpect.EOF)
        assert not child.isalive()
        assert child.exitstatus == 0

    def test_write(self) -> None:
        """Write a character and return it in return."""
        child = pexpect.spawn("cat", echo=False)
        child.write("a")
        child.write("\r")
        assert child.readline() == b"a\r\n"

    def test_writelines(self) -> None:
        """spawn.writelines()."""
        child = pexpect.spawn("cat")
        # notice that much like file.writelines, we do not delimit by newline
        # -- it is equivalent to calling write(''.join([args,]))
        child.writelines(["abc", "123", "xyz", "\r"])
        child.sendeof()
        line = child.readline()
        assert line == b"abc123xyz\r\n"

    def test_eof(self) -> None:
        """Call to expect() after EOF is received raises pexpect.EOF."""
        child = pexpect.spawn("cat")
        child.sendeof()
        with pytest.raises(pexpect.EOF):
            child.expect("the unexpected")

    def test_with(self) -> None:
        """Spawn can be used as a context manager."""
        with pexpect.spawn(self.PYTHONBIN + " echo_w_prompt.py") as p:
            p.expect("<in >")
            p.sendline(b"alpha")
            p.expect(b"<out>alpha")
            assert p.isalive()

        assert not p.isalive()

    def test_terminate(self) -> None:
        """Test force terminate always succeeds (SIGKILL)."""
        child = pexpect.spawn("cat")
        child.terminate(force=1)
        assert child.terminated

    def test_write_to_stdout_without_a_buffer(self) -> None:
        """Write bytes to a stdout that has no binary buffer.

        Given a spawn in bytes mode and a stdout replacement that offers no
        .buffer attribute, as a captured text stream does,
        When :meth:`pexpect.spawn.write_to_stdout` is called,
        Then the bytes are decoded and written to the text stream.
        """
        child = pexpect.spawn("cat")
        stdout = io.StringIO()
        with mock.patch.object(sys, "stdout", stdout):
            child.write_to_stdout(b"hello")

        assert stdout.getvalue() == "hello"

    def test_read_stops_at_the_delimiter(self) -> None:
        """Return everything read when EOF arrives before the requested size.

        Given a child that prints a few characters and exits,
        When :meth:`pexpect.spawn.read` is asked for far more characters than
        the child produced,
        Then everything the child printed is returned.
        """
        child = pexpect.spawn("echo abc")
        assert child.read(1000) == b"abc\r\n"

    def test_eof_flag(self) -> None:
        """Report whether an EOF was ever seen on the child's pty.

        Given a freshly spawned child,
        When it is sent an EOF and the EOF exception has been raised,
        Then :meth:`pexpect.spawn.eof` changes from False to True.
        """
        child = pexpect.spawn("cat")
        assert not child.eof()

        child.sendeof()
        child.expect(pexpect.EOF)
        assert child.eof()

    def test_terminate_a_child_that_is_already_dead(self) -> None:
        """Report success when there is nothing left to terminate.

        Given a child that has already exited,
        When :meth:`pexpect.spawn.terminate` is called,
        Then it returns True without sending any signal.
        """
        child = pexpect.spawn("cat")
        child.sendeof()
        child.expect(pexpect.EOF)
        assert child.terminate()

    def test_terminate_when_the_kernel_reports_a_dead_child_as_alive(self) -> None:
        """Fall back to one last liveness check when signalling fails.

        Given a child that isalive() reports as alive but that the kernel has
        already reaped, so that sending a signal raises OSError,
        When :meth:`pexpect.spawn.terminate` is called,
        Then the error is swallowed and the result is the answer of one final
        liveness check.
        """
        child = pexpect.spawn("cat")
        child.sendeof()
        child.expect(pexpect.EOF)

        with (
            mock.patch.object(child, "isalive", side_effect=[True, False]),
            mock.patch.object(child, "kill", side_effect=OSError("no such process")),
        ):
            assert child.terminate()

    def test_read_nonblocking_on_a_braindead_platform(self) -> None:
        """Raise EOF when the child is gone and nothing is left to read.

        Given a dead child whose pty never becomes readable, which is how
        platforms such as Solaris behave,
        When :meth:`pexpect.spawn.read_nonblocking` is called with the default
        timeout,
        Then :exc:`pexpect.EOF` is raised.
        """
        child = pexpect.spawn("cat")
        with (
            mock.patch.object(child, "isalive", return_value=False),
            mock.patch.object(child, "_ready", return_value=False),
            pytest.raises(pexpect.EOF, match="Braindead platform"),
        ):
            child.read_nonblocking()

    def test_read_nonblocking_on_a_very_slow_platform(self) -> None:
        """Raise EOF when the child only admits to being dead after the wait.

        Given a child that isalive() first reports as alive and then, after the
        read timed out, reports as dead,
        When :meth:`pexpect.spawn.read_nonblocking` is called,
        Then :exc:`pexpect.EOF` is raised instead of a timeout.
        """
        child = pexpect.spawn("cat")
        with (
            mock.patch.object(child, "isalive", side_effect=[True, False]),
            pytest.raises(pexpect.EOF, match="Very slow platform"),
        ):
            child.read_nonblocking(timeout=0.01)

    def test_read_nonblocking_raises_the_irix_minimum_timeout(self) -> None:
        """Wait at least two seconds for a read on Irix.

        Given a spawn created while the platform claims to be Irix,
        When :meth:`pexpect.spawn.read_nonblocking` is called with a timeout
        below the two second Irix minimum,
        Then the wait is stretched to that minimum before TIMEOUT is raised.
        """
        with mock.patch.object(sys, "platform", "irix6.5"):
            child = pexpect.spawn("cat")

        started = time.time()
        with (
            mock.patch.object(pty_spawn, "_IRIX_MIN_TIMEOUT", _IRIX_MIN_TIMEOUT),
            pytest.raises(pexpect.TIMEOUT),
        ):
            child.read_nonblocking(timeout=_IRIX_MIN_TIMEOUT / 2)

        assert time.time() - started >= _IRIX_MIN_TIMEOUT

    def test_interact_stops_at_a_bsd_style_eof(self) -> None:
        """Stop copying the child's output when a read returns nothing.

        Given a spawn whose pty reports EOF as an empty read, which is how the
        BSDs behave, rather than as an EIO error,
        When interact() copies a chunk from the child to stdout,
        Then the copy reports that there is nothing more to read.
        """
        child = pexpect.spawn("cat")
        with mock.patch.object(child, "_spawn__interact_read", return_value=b""):
            assert child._spawn__interact_child_to_stdout(None) is False

    def test_spawn_refuses_to_start_a_second_child(self) -> None:
        """Refuse to spawn again over a running child.

        Given a spawn that already has a child process,
        When _spawn() is called again,
        Then :exc:`pexpect.ExceptionPexpect` complains about the pid member.
        """
        child = pexpect.spawn("cat")
        with pytest.raises(pexpect.ExceptionPexpect, match="pid member must be None"):
            child._spawn("cat")

    def test_spawn_refuses_an_unresolved_command(self) -> None:
        """Refuse to spawn when the command could not be resolved.

        Given a spawn subclass whose command resolution leaves the command
        unset,
        When _spawn() is called,
        Then :exc:`pexpect.ExceptionPexpect` complains about the command member.
        """

        class UnresolvingSpawn(pexpect.spawn):
            """A spawn that never works out what to run."""

            def _resolve_command(self, command: str, args: list[str]) -> None:
                """Leave the command unresolved."""

        child = UnresolvingSpawn(None)
        with pytest.raises(pexpect.ExceptionPexpect, match="command member must not be None"):
            child._spawn("cat")

    def test_ignore_sighup_wraps_the_preexec_function(self) -> None:
        """Ignore SIGHUP in the child before running the caller's preexec_fn.

        Given a spawn asked to ignore SIGHUP and a preexec_fn of its own,
        When the wrapper that _spawn() would hand to ptyprocess is run,
        Then SIGHUP is set to be ignored and the caller's preexec_fn is called.
        """
        called = []

        def preexec() -> None:
            """Record that the caller's preexec_fn ran."""
            called.append(signal.getsignal(signal.SIGHUP))

        child = pexpect.spawn(None, ignore_sighup=True)
        wrapper = child._ptyproc_kwargs(preexec, None)["preexec_fn"]

        original = signal.getsignal(signal.SIGHUP)
        try:
            wrapper()
            assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
        finally:
            signal.signal(signal.SIGHUP, original)

        assert called == [signal.SIG_IGN]

    def test_ignore_sighup_without_a_preexec_function(self) -> None:
        """Ignore SIGHUP in the child when there is no preexec_fn to call.

        Given a spawn asked to ignore SIGHUP but given no preexec_fn,
        When the wrapper that _spawn() would hand to ptyprocess is run,
        Then SIGHUP is set to be ignored and nothing else is called.
        """
        child = pexpect.spawn(None, ignore_sighup=True)
        wrapper = child._ptyproc_kwargs(None, None)["preexec_fn"]

        original = signal.getsignal(signal.SIGHUP)
        try:
            wrapper()
            assert signal.getsignal(signal.SIGHUP) == signal.SIG_IGN
        finally:
            signal.signal(signal.SIGHUP, original)

    def test_read_nonblocking_reads_what_a_dead_child_left_behind(self) -> None:
        """Read the output a child left in the pty after it exited.

        Given a child that has exited with output still unread, and a pty that
        only reports itself readable on the second look,
        When :meth:`pexpect.spawn.read_nonblocking` is called,
        Then the output is returned rather than EOF being raised.
        """
        child = pexpect.spawn("echo alpha")
        deadline = time.time() + 5
        while child.isalive() and time.time() < deadline:
            time.sleep(0.05)

        with (
            mock.patch.object(child, "isalive", return_value=False),
            mock.patch.object(child, "_ready", side_effect=[False, True]),
        ):
            assert child.read_nonblocking(size=5) == b"alpha"

    def test_waitnoecho_without_a_timeout(self) -> None:
        """Wait for echo to be switched off with no deadline of its own.

        Given a child that turns echo off shortly after it starts,
        When :meth:`pexpect.spawn.waitnoecho` is called with timeout=None, so
        that it blocks until echo goes away,
        Then it returns True.
        """
        child = pexpect.spawn(self.PYTHONBIN + " getch.py", echo=False)
        assert child.waitnoecho(timeout=None)

    def test_bad_child_pid(self) -> None:
        """Assert bad condition error in isalive()."""
        expect_errmsg = re.escape("isalive() encountered condition where ")
        child = pexpect.spawn("cat")
        child.terminate(force=1)
        # Force an invalid state to test isalive
        child.ptyproc.terminated = 0
        try:
            with pytest.raises(pexpect.ExceptionPexpect, match=".*" + expect_errmsg):
                child.isalive()
        finally:
            # Force valid state for child for __del__
            child.terminated = 1

    def test_bad_arguments_suggest_fdpsawn(self) -> None:
        """Assert custom exception for spawn(int)."""
        expect_errmsg = "maybe you want to use fdpexpect.fdspawn"
        with pytest.raises(pexpect.ExceptionPexpect, match=".*" + expect_errmsg):
            pexpect.spawn(1)

    def test_bad_arguments_second_arg_is_list(self) -> None:
        """Second argument to spawn, if used, must be only a list."""
        with pytest.raises(TypeError):
            pexpect.spawn("ls", "-la")

        with pytest.raises(TypeError):
            # not even a tuple,
            pexpect.spawn("ls", ("-la",))

    def test_read_after_close_raises_value_error(self) -> None:
        """Calling read_nonblocking after close raises ValueError."""
        # as read_nonblocking underlies all other calls to read,
        # ValueError should be thrown for all forms of read.
        p = pexpect.spawn("cat")
        p.close()
        with pytest.raises(ValueError, match=_CLOSED_FILE_ERRMSG):
            p.read_nonblocking()

        p = pexpect.spawn("cat")
        p.close()
        with pytest.raises(ValueError, match=_CLOSED_FILE_ERRMSG):
            p.read()

        p = pexpect.spawn("cat")
        p.close()
        with pytest.raises(ValueError, match=_CLOSED_FILE_ERRMSG):
            p.readline()

        p = pexpect.spawn("cat")
        p.close()
        with pytest.raises(ValueError, match=_CLOSED_FILE_ERRMSG):
            p.readlines()

    def test_isalive(self) -> None:
        """Check isalive() before and after EOF. (True, False)."""
        child = pexpect.spawn("cat")
        assert child.isalive() is True
        child.sendeof()
        child.expect(pexpect.EOF)
        assert child.isalive() is False

    def test_bad_type_in_expect(self) -> None:
        """expect() does not accept dictionary arguments."""
        child = pexpect.spawn("cat")
        with pytest.raises(TypeError):
            child.expect({})

    def test_cwd(self) -> None:
        """Check keyword argument `cwd=' of pexpect.run()."""
        tmp_dir = os.path.realpath(tempfile.gettempdir())
        default = pexpect.run("pwd")
        pwd_tmp = pexpect.run("pwd", cwd=tmp_dir).rstrip()
        assert default != pwd_tmp
        assert tmp_dir == pwd_tmp.decode("utf-8")

    def _test_searcher_as(
        self,
        searcher: type[pexpect.searcher_string] | type[pexpect.searcher_re],
        plus: type[pexpect.EOF] | type[pexpect.TIMEOUT] | None = None,
    ) -> None:
        # given,
        given_words = [
            "alpha",
            "beta",
            "gamma",
            "delta",
        ]
        given_search = given_words
        if searcher == pexpect.searcher_re:
            given_search = [re.compile(word) for word in given_words]
        if plus is not None:
            given_search = [*given_search, plus]
        search_string = searcher(given_search)
        basic_fmt = "\n    {0}: {1}"
        fmt = basic_fmt
        if searcher is pexpect.searcher_re:
            fmt = "\n    {0}: re.compile({1})"
        expected_output = f"{searcher.__name__}:"
        idx = 0
        for word in given_words:
            expected_output += fmt.format(idx, f"'{word}'")
            idx += 1
        if plus is not None:
            if plus == pexpect.EOF:
                expected_output += basic_fmt.format(idx, "EOF")
            elif plus == pexpect.TIMEOUT:
                expected_output += basic_fmt.format(idx, "TIMEOUT")

        # exercise,
        assert search_string.__str__() == expected_output

    def test_searcher_as_string(self) -> None:
        """Check searcher_string(..).__str__()."""
        self._test_searcher_as(pexpect.searcher_string)

    def test_searcher_as_string_with_eof(self) -> None:
        """Check searcher_string(..).__str__() that includes EOF."""
        self._test_searcher_as(pexpect.searcher_string, plus=pexpect.EOF)

    def test_searcher_as_string_with_timeout(self) -> None:
        """Check searcher_string(..).__str__() that includes TIMEOUT."""
        self._test_searcher_as(pexpect.searcher_string, plus=pexpect.TIMEOUT)

    def test_searcher_re_as_string(self) -> None:
        """Check searcher_re(..).__str__()."""
        self._test_searcher_as(pexpect.searcher_re)

    def test_searcher_re_as_string_with_eof(self) -> None:
        """Check searcher_re(..).__str__() that includes EOF."""
        self._test_searcher_as(pexpect.searcher_re, plus=pexpect.EOF)

    def test_searcher_re_as_string_with_timeout(self) -> None:
        """Check searcher_re(..).__str__() that includes TIMEOUT."""
        self._test_searcher_as(pexpect.searcher_re, plus=pexpect.TIMEOUT)

    def test_nonnative_pty_fork(self) -> None:
        """Test forced self.__fork_pty() and __pty_make_controlling_tty."""

        # given,
        class SpawnOurPtyFork(pexpect.spawn):
            def _spawn(
                self,
                command: str,
                args: list[str] | None = None,
                preexec_fn: Callable[[], None] | None = None,
                dimensions: tuple[int, int] | None = None,
            ) -> None:
                if args is None:
                    args = []
                self.use_native_pty_fork = False
                pexpect.spawn._spawn(self, command, args, preexec_fn, dimensions)

        # exercise,
        p = SpawnOurPtyFork("cat", echo=False)
        # verify,
        p.sendline("abc")
        p.expect("abc")
        p.sendeof()
        p.expect(pexpect.EOF)
        assert not p.isalive()

    def test_exception_tb(self) -> None:
        """Test get_trace() filters away pexpect/__init__.py calls."""
        p = pexpect.spawn("sleep 0.01")
        try:
            p.expect("BLAH")
        except pexpect.ExceptionPexpect as e:
            # get_trace should filter out frames in pexpect's own code
            tb = e.get_trace()
            # exercise,
            assert "raise " not in tb
            assert "pexpect/__init__.py" not in tb
        else:
            msg = "Should have raised an exception."
            raise AssertionError(msg)


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(TestCaseMisc)
