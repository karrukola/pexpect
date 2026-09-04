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
import unittest

import pexpect_test_case

import pexpect


class ExpectTestCase(pexpect_test_case.PexpectTestCase):
    """Tests for passing a raw file descriptor to pexpect.spawn()."""

    def setUp(self) -> None:
        """Announce the test id, then run the shared set-up."""
        print(self.id())
        pexpect_test_case.PexpectTestCase.setUp(self)

    def test_fd(self) -> None:
        """Read a file through spawn() until EOF."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = pexpect.spawn(fd)
        s.expect("This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == " END\n"

    def test_maxread(self) -> None:
        """Match across reads when maxread is smaller than the file."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = pexpect.spawn(fd)
        s.maxread = 100
        s.expect("2")
        s.expect("This is the end of test data:")
        s.expect(pexpect.EOF)
        assert s.before == " END\n"

    def test_fd_isalive(self) -> None:
        """Report isalive() as false once the descriptor is closed."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = pexpect.spawn(fd)
        assert s.isalive()
        os.close(fd)
        assert not s.isalive()

    def test_fd_isatty(self) -> None:
        """Report isatty() as false for a regular file."""
        fd = os.open("TESTDATA.txt", os.O_RDONLY)
        s = pexpect.spawn(fd)
        assert not s.isatty()
        os.close(fd)


if __name__ == "__main__":
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
