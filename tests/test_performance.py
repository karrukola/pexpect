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

import platform
import sys
import time
import unittest

import pexpect

from . import pexpect_test_case

# This isn't exactly a unit test, but it fits in nicely with the rest of the tests.


class PerformanceTestCase(pexpect_test_case.PexpectTestCase):
    """Test the performance of expect, with emphasis on wading through long inputs."""

    @staticmethod
    def _iter_n(n: int) -> bytes:
        s = f"for n in range(1, {n}+1): print(n)"
        return s.encode("ascii")

    def plain_range(self, n: int) -> None:
        """Match the last line of a printed 1..n range with a regex."""
        e = pexpect.spawn(sys.executable, timeout=100)
        assert e.expect(b">>>") == 0
        e.sendline(self._iter_n(n))
        assert e.expect(rb"\.{3}") == 0
        e.sendline(b"")
        assert e.expect([b"inquisition", f"{n}"]) == 1

    def window_range(self, n: int) -> None:
        """Match the last line of a printed 1..n range within a small search window."""
        e = pexpect.spawn(sys.executable, timeout=100)
        assert e.expect(b">>>") == 0
        e.sendline(self._iter_n(n))
        assert e.expect(r"\.{3}") == 0
        e.sendline(b"")
        assert e.expect([b"inquisition", f"{n}"], searchwindowsize=20) == 1

    def exact_range(self, n: int) -> None:
        """Match the last line of a printed 1..n range with expect_exact."""
        e = pexpect.spawn(sys.executable, timeout=100)
        assert e.expect_exact([b">>>"]) == 0
        e.sendline(self._iter_n(n))
        assert e.expect_exact([b"..."]) == 0
        e.sendline(b"")
        assert e.expect_exact([b"inquisition", f"{n}"], timeout=520) == 1

    def ewin_range(self, n: int) -> None:
        """Match the last line of a printed 1..n range with expect_exact and a small window."""
        e = pexpect.spawn(sys.executable, timeout=100)
        assert e.expect_exact([b">>>"]) == 0
        e.sendline(self._iter_n(n))
        assert e.expect_exact([b"..."]) == 0
        e.sendline(b"")
        assert e.expect_exact([b"inquisition", f"{n}"], searchwindowsize=20) == 1

    def faster_range(self, n: int) -> None:
        """Match the tail of a single repr of list(range(1, n + 1))."""
        e = pexpect.spawn(sys.executable, timeout=100)
        assert e.expect(b">>>") == 0
        e.sendline(f"list(range(1, {n}+1))".encode("ascii"))
        assert e.expect([b"inquisition", f"{n}"]) == 1

    def test_100000(self) -> None:
        """Time every matching strategy against 100000 lines of child output."""
        if platform.python_implementation() == "PyPy":
            msg = "This test fails on PyPy because of REPL differences"
            raise unittest.SkipTest(msg)
        print()
        start_time = time.time()
        self.plain_range(100000)
        print("100000 calls to plain_range:", (time.time() - start_time))
        start_time = time.time()
        self.window_range(100000)
        print("100000 calls to window_range:", (time.time() - start_time))
        start_time = time.time()
        self.exact_range(100000)
        print("100000 calls to exact_range:", (time.time() - start_time))
        start_time = time.time()
        self.ewin_range(100000)
        print("100000 calls to ewin_range:", (time.time() - start_time))
        start_time = time.time()
        self.faster_range(100000)
        print("100000 calls to faster_range:", (time.time() - start_time))

    def test_large_stdout_stream(self) -> None:
        """Read 25 MiB of base64 through to EOF without matching the decoy pattern."""
        e = pexpect.spawn(f"openssl rand -base64 {1024 * 1024 * 25}", searchwindowsize=1000)
        resp = e.expect(["Password:", pexpect.EOF, pexpect.TIMEOUT])
        assert resp == 1  # index 1 == EOF


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(PerformanceTestCase)
