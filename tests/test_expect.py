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

import multiprocessing
import re
import signal
import subprocess
import sys
import time
import unittest
from collections.abc import Callable
from types import FrameType

import pytest

import pexpect

from . import pexpect_test_case
from .utils import no_coverage_env

# Python 3.14 changed the non-macOS POSIX default to forkserver
# but the code in this module does not work with it
# See https://github.com/python/cpython/issues/125714
if multiprocessing.get_start_method() == "forkserver":
    mp_context = multiprocessing.get_context(method="fork")
else:
    mp_context = multiprocessing.get_context()

# Many of these test cases blindly assume that sequential directory
# listings of the /bin directory will yield the same results.
# This may not be true, but seems adequate for testing now.
# I should fix this at some point.

# repr() of a printable character is three characters long: quote, char, quote.
_PRINTABLE_REPR_LEN = 3

# echo_wait.py turns ECHO off two seconds after it starts.
_ECHO_OFF_AFTER = 2
# ... so waitnoecho(timeout=10) must return within that window.
_ECHO_OFF_BEFORE = 10
# A plain `cat` never turns ECHO off, so waitnoecho(timeout=4) must block
# for very nearly the whole timeout before giving up.
_ECHO_STAYS_ON_MIN_WAIT = 3

# `head -500` in the command spawned by test_before_across_chunks.
_HEAD_LINES = 500

FILTER = "".join(chr(x) if len(repr(chr(x))) == _PRINTABLE_REPR_LEN else "." for x in range(256))


def hex_dump(src: bytes, length: int = 16) -> str:
    """Render bytes as rows of offset, hex bytes and printable characters."""
    result = []
    for i in range(0, len(src), length):
        chunk = src[i : i + length]
        hexa = " ".join(f"{byte:02X}" for byte in chunk)
        printable = "".join(FILTER[byte] for byte in chunk)
        result.append(f"{i:04X}   {hexa:<{length * 3}}   {printable}\n")
    return "".join(result)


def hex_diff(left: bytes, right: bytes) -> str:
    """Return the hex dump rows that differ between ``left`` and ``right``."""
    diff = [
        f"< {_left}\n> {_right}"
        for _left, _right in zip(
            hex_dump(left).splitlines(), hex_dump(right).splitlines(), strict=False
        )
        if _left != _right
    ]
    return "\n" + "\n".join(
        diff,
    )


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Cover expect(), expect_exact() and the before/after buffers they set."""

    def test_expect_basic(self) -> None:
        """Match three patterns in the order they were sent, then EOF."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.sendline(b"Hello")
        p.sendline(b"there")
        p.sendline(b"Mr. Python")
        p.expect(b"Hello")
        p.expect(b"there")
        p.expect(b"Mr. Python")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_expect_exact_basic(self) -> None:
        """Like test_expect_basic(), but matching literals with expect_exact()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.sendline(b"Hello")
        p.sendline(b"there")
        p.sendline(b"Mr. Python")
        p.expect_exact(b"Hello")
        p.expect_exact(b"there")
        p.expect_exact(b"Mr. Python")
        p.sendeof()
        p.expect_exact(pexpect.EOF)

    def test_expect_ignore_case(self) -> None:
        """Match patterns of differing case using the regex (?i) directive."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.sendline(b"HELLO")
        p.sendline(b"there")
        p.expect(b"(?i)hello")
        p.expect(b"(?i)THERE")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_expect_ignore_case_flag(self) -> None:
        """Match patterns of differing case once the ignorecase flag is set."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.ignorecase = True
        p.sendline(b"HELLO")
        p.sendline(b"there")
        p.expect(b"hello")
        p.expect(b"THERE")
        p.sendeof()
        p.expect(pexpect.EOF)

    def test_coerce_expect_re_enc_none(self) -> None:
        """Coerce a str pattern to bytes when the spawn has no encoding."""
        p = pexpect.spawn("true")
        c = pexpect.spawnbase.SpawnBase._coerce_expect_re(p, re.compile("String"))
        assert isinstance(c.pattern, bytes)
        p.expect(pexpect.EOF)

    def test_coerce_expect_re_enc_ascii(self) -> None:
        """Coerce a bytes pattern to str when the spawn has ascii encoding."""
        p = pexpect.spawn("true", encoding="ascii")
        c = pexpect.spawnbase.SpawnBase._coerce_expect_re(p, re.compile(b"String"))
        assert isinstance(c.pattern, str)
        p.expect(pexpect.EOF)

    def test_coerce_expect_re_enc_utf8(self) -> None:
        """Coerce a bytes pattern to str when the spawn has utf-8 encoding."""
        p = pexpect.spawn("true", encoding="utf-8")
        c = pexpect.spawnbase.SpawnBase._coerce_expect_re(p, re.compile(b"String"))
        assert isinstance(c.pattern, str)
        p.expect(pexpect.EOF)

    def test_expect_regex_enc_none(self) -> None:
        """Accept a regex compiled from str on a bytes mode spawn (encoding=None)."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.sendline('We are the Knights who say "Ni!"')
        index = p.expect(
            [re.compile('We are the Knights who say "Ni!"'), pexpect.EOF, pexpect.TIMEOUT]
        )
        assert index == 0
        p.sendeof()
        p.expect_exact(pexpect.EOF)

    def test_expect_regex_enc_utf8(self) -> None:
        """Accept a regex compiled from bytes on a str mode spawn (encoding='utf-8')."""
        p = pexpect.spawn("cat", echo=False, timeout=5, encoding="utf-8")
        p.sendline('We are the Knights who say "Ni!"')
        index = p.expect(
            [re.compile(b'We are the Knights who say "Ni!"'), pexpect.EOF, pexpect.TIMEOUT]
        )
        assert index == 0
        p.sendeof()
        p.expect_exact(pexpect.EOF)

    def test_expect_order(self) -> None:
        """Match patterns in the same order as given in the pattern_list.

        (Or does it?  Doesn't it also pass if expect() always chooses
        (one of the) the leftmost matches in the input? -- grahn)
        ... agreed! -jquast, the buffer ptr isn't forwarded on match, see first two test cases
        """
        p = pexpect.spawn("cat", echo=False, timeout=5)
        self._expect_order(p)

    def test_expect_order_exact(self) -> None:
        """Like test_expect_order(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.expect = p.expect_exact
        self._expect_order(p)

    def _expect_order(self, p: pexpect.spawn) -> None:
        p.sendline(b"1234")
        p.sendline(b"abcd")
        p.sendline(b"wxyz")
        p.sendline(b"7890")
        p.sendeof()
        patterns = [b"1234", b"abcd", b"wxyz", pexpect.EOF, b"7890"]
        index = p.expect(patterns)
        assert patterns[index] == b"1234", (index, p.before, p.after)

        # The buffer pointer is not forwarded on a match, so the same
        # pattern_list matches 'abcd' first and only then 'wxyz'.
        patterns = [b"54321", pexpect.TIMEOUT, b"1234", b"abcd", b"wxyz", pexpect.EOF]
        index = p.expect(patterns, timeout=5)
        assert patterns[index] == b"abcd", (index, p.before, p.after)
        index = p.expect(patterns, timeout=5)
        assert patterns[index] == b"wxyz", (index, p.before, p.after)

        patterns = [pexpect.EOF, b"abcd", b"wxyz", b"7890"]
        index = p.expect(patterns)
        assert patterns[index] == b"7890", (index, p.before, p.after)

        patterns = [b"abcd", b"wxyz", b"7890", pexpect.EOF]
        index = p.expect(patterns)
        assert patterns[index] == pexpect.EOF, (index, p.before, p.after)

    def test_expect_setecho_off(self) -> None:
        """Toggle tty echo off half way through a session and keep matching."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        try:
            self._expect_echo_toggle(p)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise

    def test_expect_setecho_off_exact(self) -> None:
        """Like test_expect_setecho_off(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        p.expect = p.expect_exact
        try:
            self._expect_echo_toggle(p)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise

    def test_waitnoecho(self) -> None:
        """Tests setecho(False) followed by waitnoecho()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        try:
            p.setecho(state=False)
            p.waitnoecho()
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise

    def test_waitnoecho_order(self) -> None:
        """Wait on a child process to set echo mode.

        For example, this tests that we could wait for SSH to set ECHO False
        when asking of a password. This makes use of an external script
        echo_wait.py.
        """
        p1 = pexpect.spawn(f"{self.PYTHONBIN} echo_wait.py")
        start = time.time()
        try:
            p1.waitnoecho(timeout=10)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise

        end_time = time.time() - start
        assert end_time > _ECHO_OFF_AFTER, "waitnoecho returned before ECHO was set off."
        assert end_time < _ECHO_OFF_BEFORE, (
            "waitnoecho did not set ECHO off in the expected window of time."
        )

        # test that we actually timeout and return False if ECHO is never set off.
        p1 = pexpect.spawn("cat")
        start = time.time()
        retval = p1.waitnoecho(timeout=4)
        end_time = time.time() - start
        assert end_time > _ECHO_STAYS_ON_MIN_WAIT, (
            f"waitnoecho should have waited for its whole timeout, retval={retval}"
        )
        assert not retval, f"retval should be False, retval={retval}"

        # This one is mainly here to test default timeout for code coverage.
        p1 = pexpect.spawn(f"{self.PYTHONBIN} echo_wait.py")
        start = time.time()
        p1.waitnoecho()
        end_time = time.time() - start
        assert end_time < _ECHO_OFF_BEFORE, (
            "waitnoecho did not set ECHO off in the expected window of time."
        )

    def test_expect_echo(self) -> None:
        """Match input twice over, because tty echo is on by default."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        self._expect_echo(p)

    def test_expect_echo_exact(self) -> None:
        """Like test_expect_echo(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        p.expect = p.expect_exact
        self._expect_echo(p)

    def _expect_echo(self, p: pexpect.spawn) -> None:
        p.sendline(b"1234")  # Should see this twice (once from tty echo and again from cat).
        index = p.expect([b"1234", b"abcd", b"wxyz", pexpect.EOF, pexpect.TIMEOUT])
        assert index == 0, "index=" + str(index) + "\n" + p.before
        index = p.expect([b"1234", b"abcd", b"wxyz", pexpect.EOF])
        assert index == 0, "index=" + str(index)

    def _expect_echo_toggle(self, p: pexpect.spawn) -> None:
        p.sendline(b"1234")  # Should see this twice (once from tty echo and again from cat).
        index = p.expect([b"1234", b"abcd", b"wxyz", pexpect.EOF, pexpect.TIMEOUT])
        assert index == 0, "index=" + str(index) + "\n" + p.before
        index = p.expect([b"1234", b"abcd", b"wxyz", pexpect.EOF])
        assert index == 0, "index=" + str(index)
        p.setecho(0)  # Turn off tty echo
        p.waitnoecho()
        p.sendline(b"abcd")  # Now, should only see this once.
        p.sendline(b"wxyz")  # Should also be only once.
        patterns = [pexpect.EOF, pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234"]
        index = p.expect(patterns)
        assert patterns[index] == b"abcd", "index=" + str(index)
        patterns = [pexpect.EOF, b"abcd", b"wxyz", b"7890"]
        index = p.expect(patterns)
        assert patterns[index] == b"wxyz", "index=" + str(index)
        p.setecho(1)  # Turn on tty echo
        p.sendline(b"7890")  # Should see this twice.
        index = p.expect(patterns)
        assert patterns[index] == b"7890", "index=" + str(index)
        index = p.expect(patterns)
        assert patterns[index] == b"7890", "index=" + str(index)
        p.sendeof()

    def test_expect_index(self) -> None:
        """Return the correct index for a mixed list of regexes, TIMEOUT and EOF."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        self._expect_index(p)

    def test_expect_index_exact(self) -> None:
        """Like test_expect_index(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        p.expect = p.expect_exact
        self._expect_index(p)

    def _expect_index(self, p: pexpect.spawn) -> None:
        p.sendline(b"1234")
        patterns = [b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = p.expect(patterns)
        assert patterns[index] == b"1234", "index=" + str(index)
        p.sendline(b"abcd")
        patterns = [pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = p.expect(patterns)
        assert patterns[index] == b"abcd", "index=" + str(index) + str(p)
        p.sendline(b"wxyz")
        patterns = [b"54321", pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = p.expect(patterns)
        assert patterns[index] == b"wxyz", "index=" + str(index)
        p.sendline(b"$*!@?")
        index = p.expect(patterns, timeout=1)
        assert patterns[index] == pexpect.TIMEOUT, "index=" + str(index)
        p.sendeof()
        index = p.expect(patterns)
        assert patterns[index] == pexpect.EOF, "index=" + str(index)

    def test_expect(self) -> None:
        """Read `ls -l /bin` line by line and compare it with subprocess output."""
        the_old_way = (
            subprocess.Popen(
                args=["ls", "-l", "/bin"],  # noqa: S607  # PATH-resolved ls is the comparison
                stdout=subprocess.PIPE,
            )
            .communicate()[0]
            .rstrip()
        )
        p = pexpect.spawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect([b"\n", pexpect.EOF])
            the_new_way = the_new_way + p.before
            if i == 1:
                break
        the_new_way = the_new_way.rstrip()
        the_new_way = (
            the_new_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        the_old_way = (
            the_old_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        assert the_old_way == the_new_way, hex_diff(the_old_way, the_new_way)

    def test_expect_exact(self) -> None:
        """Like test_expect(), but with expect_exact(), including a literal '.?'."""
        the_old_way = (
            subprocess.Popen(
                args=["ls", "-l", "/bin"],  # noqa: S607  # PATH-resolved ls is the comparison
                stdout=subprocess.PIPE,
            )
            .communicate()[0]
            .rstrip()
        )
        p = pexpect.spawn("ls -l /bin")
        the_new_way = b""
        while 1:
            i = p.expect_exact([b"\n", pexpect.EOF])
            the_new_way = the_new_way + p.before
            if i == 1:
                break
        the_new_way = (
            the_new_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        the_old_way = (
            the_old_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        assert the_old_way == the_new_way, hex_diff(the_old_way, the_new_way)
        p = pexpect.spawn("echo hello.?world")
        i = p.expect_exact(b".?")
        assert p.before == b"hello"
        assert p.after == b".?"

    def test_expect_eof(self) -> None:
        """Read everything `ls -l /bin` prints by expecting EOF."""
        the_old_way = (
            subprocess.Popen(args=["/bin/ls", "-l", "/bin"], stdout=subprocess.PIPE)
            .communicate()[0]
            .rstrip()
        )
        p = pexpect.spawn("/bin/ls -l /bin")
        p.expect(
            pexpect.EOF
        )  # This basically tells it to read everything. Same as pexpect.run() function.
        the_new_way = p.before
        the_new_way = (
            the_new_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        the_old_way = (
            the_old_way.replace(b"\r\n", b"\n")
            .replace(b"\r", b"\n")
            .replace(b"\n\n", b"\n")
            .rstrip()
        )
        assert the_old_way == the_new_way, hex_diff(the_old_way, the_new_way)

    def test_expect_timeout(self) -> None:
        """Set `after` to TIMEOUT when TIMEOUT is the pattern that matched."""
        p = pexpect.spawn("cat", timeout=5)
        p.expect(pexpect.TIMEOUT)  # This tells it to wait for timeout.
        assert p.after == pexpect.TIMEOUT

    def test_unexpected_eof(self) -> None:
        """Raise EOF when the child exits before the pattern is seen."""
        p = pexpect.spawn("ls -l /bin")
        try:
            p.expect("_Z_XY_XZ")  # Probably never see this in ls output.
        except pexpect.EOF:
            pass
        else:
            self.fail("Expected an EOF exception.")

    def test_buffer_interface(self) -> None:
        """Leave unread data in `buffer`, which may also be assigned to."""
        p = pexpect.spawn("cat", timeout=5)
        p.sendline(b"Hello")
        p.expect(b"Hello")
        assert len(p.buffer) > 0
        p.buffer = b"Testing"
        p.sendeof()

    def test_before_across_chunks(self) -> None:
        """Accumulate `before` across many reads, larger than searchwindowsize.

        See https://github.com/pexpect/pexpect/issues/478.
        """
        child = pexpect.spawn(
            '/bin/sh -c "openssl rand -base64 '
            f"{1024 * 1024 * 2} 2>/dev/null | head -{_HEAD_LINES} | nl -n rz -w 5 2>&1 ; "
            "echo 'PATTERN!!!'\"",
            searchwindowsize=128,
        )
        child.expect(["PATTERN"])
        assert len(child.before.splitlines()) == _HEAD_LINES
        assert child.after == b"PATTERN"
        assert child.buffer == b"!!!\r\n"

    def _before_after(self, p: pexpect.spawn) -> None:
        p.timeout = 5

        p.expect(b"5")
        assert p.after == b"5"
        assert p.before.startswith(b"[0, 1, 2"), p.before

        p.expect(b"50")
        assert p.after == b"50"
        assert p.before.startswith(b", 6, 7, 8"), p.before[:20]
        assert p.before.endswith(b"48, 49, "), p.before[-20:]

        p.expect(pexpect.EOF)
        assert p.after == pexpect.EOF
        assert p.before.startswith(b", 51, 52"), p.before[:20]
        assert p.before.endswith(b", 99]\r\n"), p.before[-20:]

    def test_before_after(self) -> None:
        """Check before/after for a few simple expect() matches."""
        p = pexpect.spawn(f"{self.PYTHONBIN} -Wi list100.py", env=no_coverage_env())
        self._before_after(p)

    def test_before_after_exact(self) -> None:
        """Check the same simple before/after things for expect_exact().

        (Grahn broke it at one point.)
        """
        p = pexpect.spawn(f"{self.PYTHONBIN} -Wi list100.py", env=no_coverage_env())
        # mangle the spawn so we test expect_exact() instead
        p.expect = p.expect_exact
        self._before_after(p)

    def test_before_after_timeout(self) -> None:
        """Tests that timeouts do not truncate before, a bug in 4.4-4.7."""
        child = pexpect.spawn("cat", echo=False)
        child.sendline("BEGIN")
        for _i in range(100):
            child.sendline("foo" * 10)
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.001)
        assert e == 1
        child.sendline("xyzzy")
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=30)
        assert e == 0
        assert child.before[0:5] == b"BEGIN"
        child.sendeof()
        child.expect(pexpect.EOF)

    def test_increasing_searchwindowsize(self) -> None:
        """Tests that the search window can be expanded, a bug in 4.4-4.7."""
        child = pexpect.spawn("cat", echo=False)
        child.sendline("BEGIN")
        for _i in range(100):
            child.sendline("foo" * 10)
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.5)
        assert e == 1
        e = child.expect([b"BEGIN", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.5)
        assert e == 1
        e = child.expect([b"BEGIN", pexpect.TIMEOUT], searchwindowsize=40000, timeout=30.0)
        assert e == 0
        child.sendeof()
        child.expect(pexpect.EOF)

    def test_searchwindowsize(self) -> None:
        """Tests that we don't match outside the window, a bug in 4.4-4.7."""
        p = pexpect.spawn("echo foobarbazbop")
        e = p.expect([b"bar", b"bop"], searchwindowsize=6)
        assert e == 1

    def _ordering(self, p: pexpect.spawn) -> None:
        p.timeout = 20
        p.expect(b">>> ")

        p.sendline("list(range(4*3))")
        assert p.expect([b"5,", b"5,"]) == 0
        p.expect(b">>> ")

        p.sendline(b"list(range(4*3))")
        assert p.expect([b"7,", b"5,"]) == 1
        p.expect(b">>> ")

        p.sendline(b"list(range(4*3))")
        assert p.expect([b"5,", b"7,"]) == 0
        p.expect(b">>> ")

        p.sendline(b"list(range(4*5))")
        assert p.expect([b"2,", b"12,"]) == 0
        p.expect(b">>> ")

        p.sendline(b"list(range(4*5))")
        assert p.expect([b"12,", b"2,"]) == 1

    def test_ordering(self) -> None:
        """Check which pattern expect() returns when many may eventually match.

        I (Grahn) am a bit confused about what should happen, but this test
        passes with pexpect 2.1.
        """
        p = pexpect.spawn(self.PYTHONBIN)
        self._ordering(p)

    def test_ordering_exact(self) -> None:
        """Check which pattern expect_exact() returns when many may match.

        I (Grahn) am a bit confused about what should happen, but this test
        passes for the expect() method with pexpect 2.1.
        """
        p = pexpect.spawn(self.PYTHONBIN)
        # mangle the spawn so we test expect_exact() instead
        p.expect = p.expect_exact
        self._ordering(p)

    def _greed(self, expect: Callable[[list[bytes]], int]) -> None:
        # End at the same point: the one with the earliest start should win
        assert expect([b"3, 4", b"2, 3, 4"]) == 1

        # Start at the same point: first pattern passed wins
        assert expect([b"5,", b"5, 6"]) == 0

        # Same pattern passed twice: first instance wins
        assert expect([b"7, 8", b"7, 8, 9", b"7, 8"]) == 0

    def _greed_read1(self, expect: Callable[[list[bytes]], int]) -> None:
        # Here, one has an earlier start and a later end. When processing
        # one character at a time, the one that finishes first should win,
        # because we don't know about the other match when it wins.
        # If maxread > 1, this behaviour is currently undefined, although in
        # most cases the one that starts first will win.
        assert expect([b"1, 2, 3", b"2,"]) == 1

    def test_greed(self) -> None:
        """Check which of several overlapping patterns expect() prefers."""
        p = pexpect.spawn(self.PYTHONBIN + " list100.py")
        self._greed(p.expect)

        p = pexpect.spawn(self.PYTHONBIN + " list100.py", maxread=1)
        self._greed_read1(p.expect)

    def test_greed_exact(self) -> None:
        """Like test_greed(), but for expect_exact()."""
        p = pexpect.spawn(self.PYTHONBIN + " list100.py")
        self._greed(p.expect_exact)

        p = pexpect.spawn(self.PYTHONBIN + " list100.py", maxread=1)
        self._greed_read1(p.expect_exact)

    def test_bad_arg(self) -> None:
        """Reject a pattern that is neither a string, a regex, EOF nor TIMEOUT."""
        p = pexpect.spawn("cat")
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect([1, b"2"])
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact(1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact([1, b"2"])

    def test_legacy_async_keyword(self) -> None:
        """Accept the pre-3.7 spelling of the async_ flag.

        Given the three expect methods, which took a keyword literally named
        "async" before it became a reserved word,
        When each is called with that keyword set to False,
        Then the call behaves like a plain synchronous match.
        """
        p = pexpect.spawn("echo abcdef")
        assert p.expect("abc", **{"async": False}) == 0
        assert p.expect_exact("de", **{"async": False}) == 0
        assert p.expect_list([re.compile(b"f")], **{"async": False}) == 0

    def test_unknown_keyword_arguments(self) -> None:
        """Reject keyword arguments the expect methods do not know.

        Given the three expect methods,
        When each is called with an unknown keyword argument,
        Then :exc:`TypeError` is raised naming the unknown arguments.
        """
        p = pexpect.spawn("cat")
        with pytest.raises(TypeError, match=r"Unknown keyword arguments"):
            p.expect("abc", nonexistent=1)
        with pytest.raises(TypeError, match=r"Unknown keyword arguments"):
            p.expect_exact("abc", nonexistent=1)
        with pytest.raises(TypeError, match=r"Unknown keyword arguments"):
            p.expect_list([re.compile(b"abc")], nonexistent=1)

    def test_expect_loop(self) -> None:
        """Match with a searcher handed straight to the expect loop.

        Given a spawn and a searcher built by hand,
        When :meth:`pexpect.spawn.expect_loop` is called with that searcher and
        an explicit timeout, which this method needs because it does not
        translate the -1 default into the spawn timeout,
        Then the index of the matching pattern is returned.
        """
        p = pexpect.spawn("echo abcdef")
        assert p.expect_loop(pexpect.searcher_string([b"abc"]), timeout=10) == 0
        assert p.expect_loop(pexpect.searcher_re([re.compile(b"def")]), timeout=10) == 0

    def test_timeout_none(self) -> None:
        """Match without a timeout when timeout=None."""
        p = pexpect.spawn("echo abcdef", timeout=None)
        p.expect("abc")
        p.expect_exact("def")
        p.expect(pexpect.EOF)

    def test_timeout_none_across_reads(self) -> None:
        """Keep reading without a timeout until the pattern is complete.

        Given a child that prints half of the pattern, pauses and then prints
        the rest, and a spawn created with timeout=None,
        When the whole pattern is expected,
        Then the read loop goes round again with no deadline to recompute and
        matches once the second half arrives.
        """
        p = pexpect.spawn("sh", ["-c", "printf abc; sleep 0.3; printf def"], timeout=None)
        p.expect("abcdef")
        p.expect(pexpect.EOF)

    def test_signal_handling(self) -> None:
        """Keep expect() going across a signal interrupt.

        A SIGWINCH generated when a window is resized is the usual case, but
        in this test we are substituting an ALARM signal as this is much
        easier for testing and is treated the same as a SIGWINCH.

        To ensure that the alarm fires during the expect call, we are
        setting the signal to alarm after 1 second while the spawned process
        sleeps for 2 seconds prior to sending the expected output.
        """

        def noop(_signum: int, _frame: FrameType | None) -> None:
            pass

        signal.signal(signal.SIGALRM, noop)

        p1 = pexpect.spawn(f"{self.PYTHONBIN} sleep_for.py 2", timeout=5)
        p1.expect("READY")
        signal.alarm(1)
        p1.expect("END")

    def test_stdin_closed(self) -> None:
        """Ensure pexpect continues to operate even when stdin is closed."""

        class ClosedStdinProc(mp_context.Process):
            def run(self) -> None:
                sys.__stdin__.close()
                cat = pexpect.spawn("cat")
                cat.sendeof()
                cat.expect(pexpect.EOF)

        proc = ClosedStdinProc()
        proc.start()
        proc.join()
        assert proc.exitcode == 0

    def test_stdin_stdout_closed(self) -> None:
        """Ensure pexpect continues to operate even when stdin and stdout is closed."""

        class ClosedStdinStdoutProc(mp_context.Process):
            def run(self) -> None:
                sys.__stdin__.close()
                sys.__stdout__.close()
                cat = pexpect.spawn("cat")
                cat.sendeof()
                cat.expect(pexpect.EOF)

        proc = ClosedStdinStdoutProc()
        proc.start()
        proc.join()
        assert proc.exitcode == 0


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
