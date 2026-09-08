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

import multiprocessing
import re
import signal
import subprocess
import sys
import unittest
from typing import TYPE_CHECKING, Protocol, cast

import pytest

import pexpect

from . import pexpect_test_case
from .utils import no_coverage_env

if TYPE_CHECKING:
    from multiprocessing.context import BaseContext
    from multiprocessing.process import BaseProcess
    from types import FrameType

    from pexpect.spawnbase import _Pattern

pytestmark = pytest.mark.usefixtures("fast_sleep", "killed_pty_children")

# Python 3.14 changed the non-macOS POSIX default to forkserver
# but the code in this module does not work with it
# See https://github.com/python/cpython/issues/125714
mp_context: BaseContext
if multiprocessing.get_start_method() == "forkserver":
    mp_context = multiprocessing.get_context(method="fork")
else:
    mp_context = multiprocessing.get_context()

if TYPE_CHECKING:
    # A base class has to be a static name, and mp_context.Process is an
    # attribute of a value. Every context's Process is a BaseProcess subclass
    # differing only in how the child is started, so that is what the two
    # subclasses below are checked against.
    _Process = BaseProcess
else:
    _Process = mp_context.Process

# Many of these test cases blindly assume that sequential directory
# listings of the /bin directory will yield the same results.
# This may not be true, but seems adequate for testing now.
# I should fix this at some point.

# repr() of a printable character is three characters long: quote, char, quote.
_PRINTABLE_REPR_LEN = 3

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


class _Matcher(Protocol):
    """The bound expect() or expect_exact() method of a spawn.

    The paired tests below share one helper each and hand it the matcher its
    name claims, rather than substituting one method for the other.
    """

    def __call__(self, pattern: _Pattern | list[_Pattern], /, timeout: float | None = ...) -> int:
        """Match one pattern, or the first of a list, and return its index."""


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
        self._expect_order(p, p.expect)

    def test_expect_order_exact(self) -> None:
        """Like test_expect_order(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        self._expect_order(p, p.expect_exact)

    def _expect_order(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.sendline(b"1234")
        p.sendline(b"abcd")
        p.sendline(b"wxyz")
        p.sendline(b"7890")
        p.sendeof()
        patterns: list[_Pattern] = [b"1234", b"abcd", b"wxyz", pexpect.EOF, b"7890"]
        index = expect(patterns)
        assert patterns[index] == b"1234", (index, p.before, p.after)

        # The buffer pointer is not forwarded on a match, so the same
        # pattern_list matches 'abcd' first and only then 'wxyz'.
        patterns = [b"54321", pexpect.TIMEOUT, b"1234", b"abcd", b"wxyz", pexpect.EOF]
        index = expect(patterns, timeout=5)
        assert patterns[index] == b"abcd", (index, p.before, p.after)
        index = expect(patterns, timeout=5)
        assert patterns[index] == b"wxyz", (index, p.before, p.after)

        patterns = [pexpect.EOF, b"abcd", b"wxyz", b"7890"]
        index = expect(patterns)
        assert patterns[index] == b"7890", (index, p.before, p.after)

        patterns = [b"abcd", b"wxyz", b"7890", pexpect.EOF]
        index = expect(patterns)
        assert patterns[index] == pexpect.EOF, (index, p.before, p.after)

    def test_expect_setecho_off(self) -> None:
        """Toggle tty echo off half way through a session and keep matching."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        try:
            self._expect_echo_toggle(p, p.expect)
        except OSError:
            if sys.platform.lower().startswith("sunos"):
                msg = "Not supported on this platform."
                raise unittest.SkipTest(msg) from None
            raise

    def test_expect_setecho_off_exact(self) -> None:
        """Like test_expect_setecho_off(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        try:
            self._expect_echo_toggle(p, p.expect_exact)
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

    def test_expect_echo(self) -> None:
        """Match input twice over, because tty echo is on by default."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        self._expect_echo(p, p.expect)

    def test_expect_echo_exact(self) -> None:
        """Like test_expect_echo(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=True, timeout=5)
        self._expect_echo(p, p.expect_exact)

    def _expect_echo(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.sendline(b"1234")  # Should see this twice (once from tty echo and again from cat).
        index = expect([b"1234", b"abcd", b"wxyz", pexpect.EOF, pexpect.TIMEOUT])
        assert index == 0, f"index={index}\n{p.before!r}"
        index = expect([b"1234", b"abcd", b"wxyz", pexpect.EOF])
        assert index == 0, "index=" + str(index)

    def _expect_echo_toggle(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.sendline(b"1234")  # Should see this twice (once from tty echo and again from cat).
        index = expect([b"1234", b"abcd", b"wxyz", pexpect.EOF, pexpect.TIMEOUT])
        assert index == 0, f"index={index}\n{p.before!r}"
        index = expect([b"1234", b"abcd", b"wxyz", pexpect.EOF])
        assert index == 0, "index=" + str(index)
        p.setecho(state=False)  # Turn off tty echo
        p.waitnoecho()
        p.sendline(b"abcd")  # Now, should only see this once.
        p.sendline(b"wxyz")  # Should also be only once.
        patterns: list[_Pattern] = [pexpect.EOF, pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234"]
        index = expect(patterns)
        assert patterns[index] == b"abcd", "index=" + str(index)
        patterns = [pexpect.EOF, b"abcd", b"wxyz", b"7890"]
        index = expect(patterns)
        assert patterns[index] == b"wxyz", "index=" + str(index)
        p.setecho(state=True)  # Turn on tty echo
        p.sendline(b"7890")  # Should see this twice.
        index = expect(patterns)
        assert patterns[index] == b"7890", "index=" + str(index)
        index = expect(patterns)
        assert patterns[index] == b"7890", "index=" + str(index)
        p.sendeof()

    def test_expect_index(self) -> None:
        """Return the correct index for a mixed list of regexes, TIMEOUT and EOF."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        self._expect_index(p, p.expect)

    def test_expect_index_exact(self) -> None:
        """Like test_expect_index(), but using expect_exact()."""
        p = pexpect.spawn("cat", echo=False, timeout=5)
        self._expect_index(p, p.expect_exact)

    def _expect_index(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.sendline(b"1234")
        patterns: list[_Pattern] = [b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = expect(patterns)
        assert patterns[index] == b"1234", "index=" + str(index)
        p.sendline(b"abcd")
        patterns = [pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = expect(patterns)
        assert patterns[index] == b"abcd", "index=" + str(index) + str(p)
        p.sendline(b"wxyz")
        patterns = [b"54321", pexpect.TIMEOUT, b"abcd", b"wxyz", b"1234", pexpect.EOF]
        index = expect(patterns)
        assert patterns[index] == b"wxyz", "index=" + str(index)
        p.sendline(b"$*!@?")
        index = expect(patterns, timeout=0.01)
        assert patterns[index] == pexpect.TIMEOUT, "index=" + str(index)
        p.sendeof()
        index = expect(patterns)
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
            assert isinstance(p.before, bytes)
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
            assert isinstance(p.before, bytes)
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
        assert isinstance(p.before, bytes)
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
        p = pexpect.spawn("cat", timeout=0.01)
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

    def _before_after(self, p: pexpect.spawn[bytes], expect: _Matcher) -> None:
        p.timeout = 5

        expect(b"5")
        assert p.after == b"5"
        assert isinstance(p.before, bytes)
        assert p.before.startswith(b"[0, 1, 2"), p.before

        expect(b"50")
        assert p.after == b"50"
        assert isinstance(p.before, bytes)
        assert p.before.startswith(b", 6, 7, 8"), p.before[:20]
        assert p.before.endswith(b"48, 49, "), p.before[-20:]

        expect(pexpect.EOF)
        assert p.after == pexpect.EOF
        assert isinstance(p.before, bytes)
        assert p.before.startswith(b", 51, 52"), p.before[:20]
        assert p.before.endswith(b", 99]\r\n"), p.before[-20:]

    def test_before_after(self) -> None:
        """Check before/after for a few simple expect() matches."""
        p = pexpect.spawn(f"{self.PYTHONBIN} -Wi list100.py", env=no_coverage_env())
        self._before_after(p, p.expect)

    def test_before_after_exact(self) -> None:
        """Check the same simple before/after things for expect_exact().

        (Grahn broke it at one point.)
        """
        p = pexpect.spawn(f"{self.PYTHONBIN} -Wi list100.py", env=no_coverage_env())
        # drive the helper with expect_exact() instead
        self._before_after(p, p.expect_exact)

    def test_before_after_timeout(self) -> None:
        """Tests that timeouts do not truncate before, a bug in 4.4-4.7."""
        child = pexpect.spawn("cat", echo=False)
        # 101 sendlines below, each one paying delaybeforesend. Nothing is read
        # back between them, so there is no echo to race with.
        child.delaybeforesend = None
        child.sendline("BEGIN")
        for _i in range(100):
            child.sendline("foo" * 10)
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.001)
        assert e == 1
        child.sendline("xyzzy")
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=30)
        assert e == 0
        assert isinstance(child.before, bytes)
        assert child.before[0:5] == b"BEGIN"
        child.sendeof()
        child.expect(pexpect.EOF)

    def test_increasing_searchwindowsize(self) -> None:
        """Tests that the search window can be expanded, a bug in 4.4-4.7."""
        child = pexpect.spawn("cat", echo=False)
        # 101 sendlines below, each one paying delaybeforesend. Nothing is read
        # back between them, so there is no echo to race with.
        child.delaybeforesend = None
        child.sendline("BEGIN")
        for _i in range(100):
            child.sendline("foo" * 10)
        e = child.expect([b"xyzzy", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.01)
        assert e == 1
        e = child.expect([b"BEGIN", pexpect.TIMEOUT], searchwindowsize=10, timeout=0.01)
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

    def test_bad_arg(self) -> None:
        """Reject a pattern that is neither a string, a regex, EOF nor TIMEOUT."""
        p = pexpect.spawn("cat")
        # What is under test is the value the signatures already rule out, so
        # it reaches them through a name that claims to be a pattern.
        not_a_pattern = cast("_Pattern", 1)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect(not_a_pattern)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect([not_a_pattern, b"2"])
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact(not_a_pattern)
        with pytest.raises(TypeError, match=r".*must be one of"):
            p.expect_exact([not_a_pattern, b"2"])

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
        p = pexpect.spawn("sh", ["-c", "printf abc; sleep 0.02; printf def"], timeout=None)
        p.expect("abcdef")
        p.expect(pexpect.EOF)

    def test_signal_handling(self) -> None:
        """Keep expect() going across a signal interrupt.

        A SIGWINCH generated when a window is resized is the usual case, but
        in this test we are substituting an ALARM signal as this is much
        easier for testing and is treated the same as a SIGWINCH.

        To ensure that the alarm fires during the expect call, we are
        setting the signal to alarm after 10 ms while the spawned process
        sleeps for 30 ms prior to sending the expected output.
        """

        def noop(_signum: int, _frame: FrameType | None) -> None:
            pass

        original = signal.getsignal(signal.SIGALRM)

        def restore() -> None:
            """Take the alarm back off the process, in the only safe order.

            The timer is cancelled before the handler goes back, because an
            alarm still pending once SIGALRM is at its default disposition
            terminates the test runner.
            """
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, original)

        # SIGALRM and ITIMER_REAL are process-wide, and both are already spoken
        # for: pytest-timeout's signal method is what puts this suite's per-test
        # budget on them. Overwriting them is what the test is for -- it costs
        # this one test its timeout, from the 10 ms below until the item ends --
        # but it must not cost the next one, which the shuffle picks at random.
        # pytest-timeout happens to reset SIGALRM to SIG_DFL after every item,
        # so today the handler would not in fact escape; restoring it here is
        # what makes that a coincidence rather than the mechanism.
        self.addCleanup(restore)
        signal.signal(signal.SIGALRM, noop)

        p1 = pexpect.spawn(f"{self.PYTHONBIN} sleep_for.py 0.03", timeout=5)
        p1.expect("READY")
        signal.setitimer(signal.ITIMER_REAL, 0.01)
        p1.expect("END")

    def test_stdin_closed(self) -> None:
        """Ensure pexpect continues to operate even when stdin is closed."""

        class ClosedStdinProc(_Process):
            def run(self) -> None:
                assert sys.__stdin__ is not None
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

        class ClosedStdinStdoutProc(_Process):
            def run(self) -> None:
                assert sys.__stdin__ is not None
                assert sys.__stdout__ is not None
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
