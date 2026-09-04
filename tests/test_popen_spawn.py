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

import subprocess
import unittest

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


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
